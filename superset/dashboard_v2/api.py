# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""
REST API of the persisted Dashboard v2 document.

The whole resource sits behind the ``DASHBOARD_V2`` feature flag (see
:mod:`superset.dashboard_v2.feature`). Reads are gated by
``Dashboard.raise_for_access``, writes by ``raise_for_editorship``, and every
update carries the revision it was based on.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import g, request, Response
from flask_appbuilder.api import expose, protect, safe
from marshmallow import ValidationError

from superset.commands.dashboard_v2.exceptions import (
    DashboardV2BadRequestError,
    DashboardV2ConflictError,
    DashboardV2InvalidError,
    DashboardV2PayloadTooLargeError,
    DashboardV2RevisionRequiredError,
)
from superset.commands.dashboard_v2.get import GetDashboardV2Command
from superset.commands.dashboard_v2.save import (
    CreateDashboardV2Command,
    UpdateDashboardV2Command,
)
from superset.commands.exceptions import CommandException
from superset.dashboard_v2.document import (
    current_limits,
    DocumentValidationError,
    parse_strict_json,
)
from superset.dashboard_v2.schemas import (
    DashboardV2PostSchema,
    DashboardV2PutSchema,
    DashboardV2ResponseSchema,
)
from superset.extensions import event_logger
from superset.views.base_api import BaseSupersetApi, statsd_metrics

# One entity tag holding a revision: "3", W/"3" or a bare 3.
_IF_MATCH_PATTERN = re.compile(r'^(?:W/)?"?(\d{1,18})"?$')


def revision_etag(revision: int) -> str:
    """The entity tag a revision is exposed as."""
    return f'"{revision}"'


def load_request_body() -> dict[str, Any]:
    """
    Read the request body as a strict JSON object within the size limit.

    :raises DashboardV2PayloadTooLargeError: If the body exceeds
        ``DASHBOARD_V2_MAX_DOCUMENT_BYTES``
    :raises DashboardV2BadRequestError: If the body is not a JSON object, or
        holds duplicate keys, non-finite numbers or excessive nesting
    """
    max_bytes = current_limits().max_bytes
    message = f"The request body is larger than {max_bytes} bytes."
    if (request.content_length or 0) > max_bytes:
        raise DashboardV2PayloadTooLargeError(message)
    raw = request.get_data()
    if len(raw) > max_bytes:
        raise DashboardV2PayloadTooLargeError(message)
    try:
        body = parse_strict_json(raw, current_limits().max_value_depth + 8)
    except DocumentValidationError as ex:
        raise DashboardV2BadRequestError(str(ex)) from ex
    if not isinstance(body, dict):
        raise DashboardV2BadRequestError("The request body must be a JSON object.")
    return body


def strict_json_body(
    handler: Callable[..., Response],
) -> Callable[..., Response]:
    """
    Parse the request body strictly before the wrapped handler runs and leave
    it in ``g.dashboard_v2_body``; answer 400/413 when it is unacceptable.

    Applied outside the event logger on purpose: the logger re-reads the body
    with a lenient recursive parser, so a body this decorator refuses (deeply
    nested, oversized) must never reach it.
    """

    @wraps(handler)
    def wrapper(self: BaseSupersetApi, *args: Any, **kwargs: Any) -> Response:
        try:
            g.dashboard_v2_body = load_request_body()
        except CommandException as ex:
            return command_error_response(self, ex)
        return handler(self, *args, **kwargs)

    return wrapper


def read_base_revision(body: dict[str, Any]) -> int:
    """
    The revision an update is based on, from the ``If-Match`` header or the
    ``base_revision`` body field (removed from ``body``).

    :raises DashboardV2BadRequestError: If the header is not a single
        revision, or disagrees with the body field
    :raises DashboardV2RevisionRequiredError: If neither is present
    """
    from_body: int | None = body.pop("base_revision", None)
    from_header: int | None = None
    if (header := request.headers.get("If-Match")) is not None:
        match = _IF_MATCH_PATTERN.match(header.strip())
        if match is None:
            raise DashboardV2BadRequestError(
                'If-Match must carry exactly one revision, for example "3".'
            )
        from_header = int(match.group(1))
    if from_header is not None and from_body is not None and from_header != from_body:
        raise DashboardV2BadRequestError(
            "If-Match and base_revision name different revisions."
        )
    revision = from_header if from_header is not None else from_body
    if revision is None:
        raise DashboardV2RevisionRequiredError()
    return revision


def command_error_response(api: BaseSupersetApi, ex: CommandException) -> Response:
    """Turn a command error into its JSON response."""
    payload: dict[str, Any] = {"message": str(ex.message)}
    if isinstance(ex, DashboardV2InvalidError) and ex.errors:
        payload["errors"] = ex.errors
    if isinstance(ex, DashboardV2ConflictError):
        payload["current_revision"] = ex.current_revision
    response = api.response(ex.status, **payload)
    if isinstance(ex, DashboardV2ConflictError):
        response.headers["ETag"] = revision_etag(ex.current_revision)
    return response


def dashboard_response(
    api: BaseSupersetApi, status: int, result: dict[str, Any], with_id: bool = False
) -> Response:
    """A v2 dashboard response carrying its revision as an ``ETag``."""
    payload: dict[str, Any] = {"result": DashboardV2ResponseSchema().dump(result)}
    if with_id:
        payload["id"] = result["id"]
    response = api.response(status, **payload)
    response.headers["ETag"] = revision_etag(result["revision"])
    return response


class DashboardV2RestApi(BaseSupersetApi):
    """Persisted Dashboard v2 documents (experimental)."""

    resource_name = "dashboard_v2"
    allow_browser_login = True
    class_permission_name = "Dashboard"
    method_permission_name = {
        "post": "write",
        "put": "write",
        "get": "read",
        "get_by_embedded": "read",
    }
    openapi_spec_tag = "Dashboard v2 (experimental)"
    openapi_spec_component_schemas = (
        DashboardV2PostSchema,
        DashboardV2PutSchema,
        DashboardV2ResponseSchema,
    )

    @expose("/", methods=("POST",))
    @protect()
    @safe
    @statsd_metrics
    @strict_json_body
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.post",
        log_to_statsd=False,
    )
    def post(self) -> Response:
        """Create a Dashboard v2 from a document.
        ---
        post:
          summary: Create a Dashboard v2
          description: >-
            Stores the document at revision 1 with the caller as editor.
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/DashboardV2PostSchema'
          responses:
            201:
              description: Dashboard v2 created
              headers:
                ETag:
                  description: The document revision, quoted
                  schema:
                    type: string
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      id:
                        type: integer
                      result:
                        $ref: '#/components/schemas/DashboardV2ResponseSchema'
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            404:
              $ref: '#/components/responses/404'
            413:
              description: The request body exceeds the document size limit
            422:
              $ref: '#/components/responses/422'
        """
        try:
            body = DashboardV2PostSchema().load(g.dashboard_v2_body)
        except ValidationError as error:
            return self.response_400(message=error.messages)
        try:
            dashboard = CreateDashboardV2Command(body).run()
            result = GetDashboardV2Command(str(dashboard.id)).run()
        except CommandException as ex:
            return command_error_response(self, ex)
        return dashboard_response(self, 201, result, with_id=True)

    @expose("/<int:pk>", methods=("PUT",))
    @protect()
    @safe
    @statsd_metrics
    @strict_json_body
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.put",
        log_to_statsd=False,
    )
    def put(self, pk: int) -> Response:
        """Replace a Dashboard v2's document.
        ---
        put:
          summary: Update a Dashboard v2
          description: >-
            Replaces the document if it is still at the revision the change
            was based on, and stores it at that revision plus one. The base
            revision is required, in the If-Match header or as base_revision.
          parameters:
          - in: path
            schema:
              type: integer
            name: pk
          - in: header
            name: If-Match
            schema:
              type: string
            description: The revision the change is based on, for example "3"
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/DashboardV2PutSchema'
          responses:
            200:
              description: Dashboard v2 updated
              headers:
                ETag:
                  description: The new document revision, quoted
                  schema:
                    type: string
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      id:
                        type: integer
                      result:
                        $ref: '#/components/schemas/DashboardV2ResponseSchema'
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
            409:
              description: >-
                The stored document is at another revision; nothing was
                written
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      message:
                        type: string
                      current_revision:
                        type: integer
            413:
              description: The request body exceeds the document size limit
            422:
              $ref: '#/components/responses/422'
            428:
              description: The base revision is missing
        """
        try:
            body = DashboardV2PutSchema().load(g.dashboard_v2_body)
            base_revision = read_base_revision(body)
        except ValidationError as error:
            return self.response_400(message=error.messages)
        except CommandException as ex:
            return command_error_response(self, ex)
        try:
            UpdateDashboardV2Command(pk, body, base_revision).run()
            result = GetDashboardV2Command(str(pk)).run()
        except CommandException as ex:
            return command_error_response(self, ex)
        return dashboard_response(self, 200, result, with_id=True)

    @expose("/<ref>", methods=("GET",))
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.get",
        log_to_statsd=False,
    )
    def get(self, ref: str) -> Response:
        """Get a Dashboard v2 with its document.
        ---
        get:
          summary: Get a Dashboard v2
          parameters:
          - in: path
            schema:
              type: string
            name: ref
            description: Embedded dashboard uuid, dashboard uuid, slug, or id
          responses:
            200:
              description: Dashboard v2
              headers:
                ETag:
                  description: The document revision, quoted
                  schema:
                    type: string
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        $ref: '#/components/schemas/DashboardV2ResponseSchema'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            result = GetDashboardV2Command(ref).run()
        except CommandException as ex:
            return command_error_response(self, ex)
        return dashboard_response(self, 200, result)

    @expose("/embedded/<uuid>", methods=("GET",))
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: (
            f"{self.__class__.__name__}.get_by_embedded"
        ),
        log_to_statsd=False,
    )
    def get_by_embedded(self, uuid: str) -> Response:
        """Get a Dashboard v2 by its embedded uuid (guest token friendly).
        ---
        get:
          summary: Get a Dashboard v2 by embedded uuid
          parameters:
          - in: path
            schema:
              type: string
            name: uuid
          responses:
            200:
              description: Dashboard v2
              headers:
                ETag:
                  description: The document revision, quoted
                  schema:
                    type: string
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        $ref: '#/components/schemas/DashboardV2ResponseSchema'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            result = GetDashboardV2Command(uuid, embedded_only=True).run()
        except CommandException as ex:
            return command_error_response(self, ex)
        return dashboard_response(self, 200, result)

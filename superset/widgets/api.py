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
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

from flask import make_response, request, Response
from flask_appbuilder.api import expose, protect, safe
from flask_babel import gettext as _
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError
from marshmallow import ValidationError

from superset import security_manager
from superset.commands.exceptions import CommandException
from superset.commands.widget.data import WidgetDataCommand, WidgetValuesCommand
from superset.commands.widget.exceptions import WidgetInvalidError
from superset.commands.widget.saved import (
    CreateSavedWidgetCommand,
    DEFAULT_LIST_PAGE_SIZE,
    DeleteSavedWidgetCommand,
    GetSavedWidgetCommand,
    ListSavedWidgetsCommand,
    UpdateSavedWidgetCommand,
)
from superset.commands.widget.utils import serialize_saved_widget
from superset.extensions import event_logger
from superset.utils import json
from superset.views.base_api import BaseSupersetApi, statsd_metrics
from superset.widgets.registry import registry
from superset.widgets.schema_tools import get_subtrees, SchemaPathError
from superset.widgets.schemas import (
    SavedWidgetPostSchema,
    SavedWidgetPutSchema,
    SavedWidgetResponseSchema,
    WidgetDataPostSchema,
    WidgetDataResponseSchema,
    WidgetValuesPostSchema,
)

logger = logging.getLogger(__name__)

# Bounds on the caller-sized lists the control-schema route accepts.
MAX_SCHEMA_PATHS = 200
MAX_SCHEMA_SERIES = 500


F = TypeVar("F", bound=Callable[..., Any])


def json_auth_errors(func: F) -> F:
    """
    Answer a missing, malformed or expired credential with the same JSON body
    every other widget error has: ``{"message": <text>}`` under 401.

    Without a session or a usable guest token the route falls through to the
    bearer-token check, whose own handler answers ``{"msg": ...}``. An
    embedding host maps statuses to messages, so the text is given under
    ``message`` too. Apply it directly above ``@protect()``.
    """

    @functools.wraps(func)
    def wrapper(self: BaseSupersetApi, *args: Any, **kwargs: Any) -> Any:
        try:
            return func(self, *args, **kwargs)
        except (JWTExtendedException, PyJWTError) as ex:
            text = str(ex) or "Not authorized"
            return self.response(401, message=text, msg=text)

    return wrapper  # type: ignore[return-value]


def _is_string_list(value: Any, limit: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= limit
        and all(isinstance(item, str) for item in value)
    )


def _control_schema_body_problem(
    control_values: Any, series: Any, paths: Any
) -> str | None:
    """What is wrong with a control-schema request body, if anything."""
    if paths is not None and not _is_string_list(paths, MAX_SCHEMA_PATHS):
        return f"'paths' must be an array of at most {MAX_SCHEMA_PATHS} strings."
    if series is not None and not _is_string_list(series, MAX_SCHEMA_SERIES):
        return f"'series' must be an array of at most {MAX_SCHEMA_SERIES} strings."
    if control_values is not None and not isinstance(control_values, dict):
        return "'control_values' must be an object."
    return None


class WidgetControlsRestApi(BaseSupersetApi):
    """
    Schema-driven controls for Dashboard V2 widgets (experimental).

    Serves the backend-owned control JSON Schema that drives both the dashboard
    Inspector's control panel and read-only MCP progressive disclosure. Widget
    data is fetched separately via the v1 chart-data path on the frontend, so
    there is no data endpoint here. The resource name ``widgets`` is
    a placeholder (see ``WIDGET_FRAMEWORK.md``).
    """

    resource_name = "widgets"
    allow_browser_login = True
    # Read-only schema serving; reuse the existing Chart permission so no new
    # permission is introduced.
    class_permission_name = "Chart"
    method_permission_name = {
        "types": "read",
        "control_schema": "read",
        "validate": "read",
    }
    openapi_spec_tag = "Dashboard Controls (experimental)"

    @expose("/types", methods=("GET",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.types",
        log_to_statsd=False,
    )
    def types(self) -> Response:
        """List registered building-widget control sets.
        ---
        get:
          summary: List widget types that have a schema-driven control panel
          responses:
            200:
              description: A list of widget types
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        type: array
                        items:
                          type: object
            401:
              $ref: '#/components/responses/401'
        """
        result = [
            {"id": cls.widget_type, "name": cls.name, "description": cls.description}
            for cls in registry.values()
        ]
        return self.response(200, result=result)

    @expose("/type/<widget_type>/control-schema", methods=("GET", "POST"))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: (
            f"{self.__class__.__name__}.control_schema"
        ),
        log_to_statsd=False,
    )
    def control_schema(self, widget_type: str) -> Response:
        """Return the control JSON Schema for a widget type (progressive
        disclosure).

        ``GET`` returns the base schema (no enrichment) — enough to discover a
        type's fields and required props without a CSRF-bearing request. ``POST``
        additionally accepts ``control_values``/``series`` to enrich x-dynamic
        fields, and an optional ``paths`` array to return just those subtrees
        (a ``{path: schema}`` map) instead of the whole schema.
        ---
        get:
          summary: Get the base control schema for a widget type
          parameters:
            - in: path
              name: widget_type
              required: true
              schema:
                type: string
          responses:
            200:
              description: Control JSON Schema
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        type: object
            404:
              $ref: '#/components/responses/404'
        post:
          summary: Get the enriched control schema (or requested subtrees)
          parameters:
            - in: path
              name: widget_type
              required: true
              schema:
                type: string
          requestBody:
            required: false
            content:
              application/json:
                schema:
                  type: object
                  properties:
                    control_values:
                      type: object
                    series:
                      type: array
                      items:
                        type: string
                    paths:
                      type: array
                      items:
                        type: string
                      description: >-
                        When given, return a `{path: schema}` map of just these
                        drill-in subtrees instead of the whole schema.
          responses:
            200:
              description: >-
                Control JSON Schema, or a `{path: schema}` map when `paths`
                was given.
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        type: object
                      warning:
                        type: string
            400:
              $ref: '#/components/responses/400'
            404:
              $ref: '#/components/responses/404'
        """
        widget = registry.get(widget_type)
        if widget is None:
            return self.response_404()
        # GET carries no body (and no CSRF); tolerate a missing/non-JSON body so
        # the base schema is returned for a plain read. A body that IS present
        # must be a JSON object.
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return self.response_400(message="Request body must be a JSON object.")
        control_values = body.get("control_values")
        series = body.get("series")
        paths = body.get("paths")
        if problem := _control_schema_body_problem(control_values, series, paths):
            return self.response_400(message=problem)
        if security_manager.is_guest_user():
            # Enrichment lists datasets and columns for an author's pickers; an
            # embedded guest renders widgets and never authors them.
            control_values = series = None

        warning: str | None = None
        try:
            schema = widget.get_control_schema(control_values, series)
        except Exception:  # pylint: disable=broad-except
            # Enrichment can fail (e.g. malformed dynamic values); showing the
            # base form is better than a hard error — mirror the Semantic Layer.
            warning = str(
                _(
                    "Could not enrich the controls for this widget; showing the "
                    "default form. See the server logs for details."
                )
            )
            logger.exception(
                "Error enriching control schema for widget type %s", widget_type
            )
            schema = widget.get_control_schema(None, None)

        # `paths` narrows the response to just those drill-in subtrees; without
        # it the whole (enriched) schema is returned.
        if paths:
            try:
                result: dict[str, Any] = get_subtrees(schema, paths)
            except SchemaPathError as ex:
                return self.response_400(message=str(ex))
        else:
            result = schema

        payload: dict[str, Any] = {"result": result}
        if warning:
            payload["warning"] = warning
        resp = make_response(json.dumps(payload, sort_keys=False), 200)
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
        return resp

    @expose("/type/<widget_type>/validate", methods=("POST",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.validate",
        log_to_statsd=False,
    )
    def validate(self, widget_type: str) -> Response:
        """Validate control values against a widget type's model.

        The commit-time gate: runs the widget's full model validation (including
        cross-field rules declared on the control model) and returns any errors
        as ``{"errors": [{"loc", "message"}]}`` (empty list when valid), so a
        caller can reject a bad edit with an actionable message rather than
        writing a silently-broken widget. Widget-agnostic — the rules live on
        each widget's control model, not here.

        On success also returns ``values``: the candidate as Pydantic actually
        parsed it (coerced, alias-keyed) rather than the raw request body — a
        caller that commits its own raw candidate instead can end up
        storing something subtly different from what this endpoint validated
        (e.g. a numeric field coerced from a string).
        ---
        post:
          summary: Validate control values for a widget type
          parameters:
            - in: path
              name: widget_type
              required: true
              schema:
                type: string
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  type: object
                  properties:
                    control_values:
                      type: object
          responses:
            200:
              description: Validation result
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        type: object
                        properties:
                          errors:
                            type: array
                            items:
                              type: object
                          values:
                            type: object
                            nullable: true
            400:
              $ref: '#/components/responses/400'
            404:
              $ref: '#/components/responses/404'
        """
        widget = registry.get(widget_type)
        if widget is None:
            return self.response_404()
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return self.response_400(message="Request body must be a JSON object.")
        control_values = body.get("control_values")
        if errors := widget.validate_control_values(control_values):
            return self.response(200, result={"errors": errors, "values": None})
        values = (
            widget.controls_class.model_validate(control_values).model_dump(
                by_alias=True
            )
            if control_values is not None
            else None
        )
        return self.response(200, result={"errors": [], "values": values})


def _command_error(api: BaseSupersetApi, ex: CommandException) -> Response:
    """
    Answer a failed command as JSON: ``{"message": <text>}`` under the
    command's own status (400, 403, 404, 409, 422, ...), plus
    ``errors: [{"loc", "message"}]`` when the widget props failed validation.
    """
    payload: dict[str, Any] = {"message": str(ex.message)}
    if isinstance(ex, WidgetInvalidError) and ex.errors:
        payload["errors"] = ex.errors
    return api.response(ex.status, **payload)


def _schema_errors(messages: Any) -> list[dict[str, Any]]:
    """Flatten marshmallow's nested messages into ``[{"loc", "message"}]``."""
    errors: list[dict[str, Any]] = []
    stack: list[tuple[list[str], Any]] = [([], messages)]
    while stack:
        loc, value = stack.pop()
        if isinstance(value, dict):
            stack.extend(
                (
                    loc if key == "_schema" else [*loc, str(key)],
                    item,
                )
                for key, item in reversed(list(value.items()))
            )
        elif isinstance(value, (list, tuple)):
            stack.extend((loc, item) for item in reversed(list(value)))
        else:
            errors.append({"loc": loc, "message": str(value)})
    return errors


def _bad_request(api: BaseSupersetApi, error: ValidationError) -> Response:
    """
    Answer a request body that failed its schema with a readable ``message``
    (the first problem) and every problem under ``errors``, the same shape a
    props validation failure uses.
    """
    errors = _schema_errors(error.messages) or [
        {"loc": [], "message": "Invalid request."}
    ]
    first = errors[0]
    location = ".".join(first["loc"])
    message = f"{location}: {first['message']}" if location else first["message"]
    return api.response(400, message=message, errors=errors)


def _page_argument(name: str, default: int) -> int:
    """An integer query argument; anything else is the caller's error."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not raw.isascii() or not raw.isdigit() or len(raw) > 9:
        raise WidgetInvalidError(f"{name} must be a non-negative integer.")
    return int(raw)


def _result_response(result: Any) -> Response:
    # Query rows can hold timestamps, decimals and NaN; serialize them the way
    # the chart data API does so embedded widgets see identical values.
    response = make_response(
        json.dumps({"result": result}, default=json.json_int_dttm_ser, ignore_nan=True),
        200,
    )
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    return response


def _dump(widget: Any) -> dict[str, Any]:
    return SavedWidgetResponseSchema().dump(serialize_saved_widget(widget))


class SavedWidgetRestApi(BaseSupersetApi):
    """Saved widgets and widget data for embedding (experimental)."""

    resource_name = "widget"
    allow_browser_login = True
    class_permission_name = "Chart"
    method_permission_name = {
        "get_list": "read",
        "get": "read",
        "post": "write",
        "put": "write",
        "delete": "write",
        "data": "read",
        "values": "read",
    }
    openapi_spec_tag = "Widgets (experimental)"
    openapi_spec_component_schemas = (
        SavedWidgetPostSchema,
        SavedWidgetPutSchema,
        SavedWidgetResponseSchema,
        WidgetDataPostSchema,
        WidgetDataResponseSchema,
        WidgetValuesPostSchema,
    )

    @expose("/", methods=("GET",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.get_list",
        log_to_statsd=False,
    )
    def get_list(self) -> Response:
        """List saved widgets.
        ---
        get:
          summary: List the saved widgets the caller may read
          description: >-
            Admins see every saved widget; anyone else their own and those
            that bind a dataset they can read. Most recently changed first.
          parameters:
          - in: query
            name: page
            description: Zero-based page index.
            schema:
              type: integer
              minimum: 0
              default: 0
          - in: query
            name: page_size
            description: Rows per page.
            schema:
              type: integer
              minimum: 1
              maximum: 100
              default: 25
          responses:
            200:
              description: One page of saved widgets
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      count:
                        type: integer
                        description: Readable saved widgets across all pages.
                      page:
                        type: integer
                      page_size:
                        type: integer
                      result:
                        type: array
                        items:
                          $ref: '#/components/schemas/SavedWidgetResponseSchema'
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            page = _page_argument("page", 0)
            page_size = _page_argument("page_size", DEFAULT_LIST_PAGE_SIZE)
            command = ListSavedWidgetsCommand(page, page_size)
            widgets = command.run()
        except CommandException as ex:
            return _command_error(self, ex)
        return self.response(
            200,
            count=command.count,
            page=page,
            page_size=page_size,
            result=[_dump(widget) for widget in widgets],
        )

    @expose("/", methods=("POST",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.post",
        log_to_statsd=False,
    )
    def post(self) -> Response:
        """Save a widget.
        ---
        post:
          summary: Save a widget
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/SavedWidgetPostSchema'
          responses:
            201:
              description: Widget saved
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        $ref: '#/components/schemas/SavedWidgetResponseSchema'
            400:
              $ref: '#/components/responses/400'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            body = SavedWidgetPostSchema().load(request.get_json(silent=True) or {})
        except ValidationError as error:
            return _bad_request(self, error)
        try:
            widget = CreateSavedWidgetCommand(body).run()
        except CommandException as ex:
            return _command_error(self, ex)
        return self.response(201, result=_dump(widget))

    @expose("/<uuid>", methods=("GET",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.get",
        log_to_statsd=False,
    )
    def get(self, uuid: str) -> Response:
        """Get a saved widget.
        ---
        get:
          summary: Get a saved widget
          parameters:
          - in: path
            schema:
              type: string
            name: uuid
          responses:
            200:
              description: Saved widget
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        $ref: '#/components/schemas/SavedWidgetResponseSchema'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            widget = GetSavedWidgetCommand(uuid).run()
        except CommandException as ex:
            return _command_error(self, ex)
        return self.response(200, result=_dump(widget))

    @expose("/<uuid>", methods=("PUT",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.put",
        log_to_statsd=False,
    )
    def put(self, uuid: str) -> Response:
        """Update a saved widget.
        ---
        put:
          summary: Update a saved widget
          parameters:
          - in: path
            schema:
              type: string
            name: uuid
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/SavedWidgetPutSchema'
          responses:
            200:
              description: Widget updated
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        $ref: '#/components/schemas/SavedWidgetResponseSchema'
            400:
              $ref: '#/components/responses/400'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            body = SavedWidgetPutSchema().load(request.get_json(silent=True) or {})
        except ValidationError as error:
            return _bad_request(self, error)
        try:
            widget = UpdateSavedWidgetCommand(uuid, body).run()
        except CommandException as ex:
            return _command_error(self, ex)
        return self.response(200, result=_dump(widget))

    @expose("/<uuid>", methods=("DELETE",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.delete",
        log_to_statsd=False,
    )
    def delete(self, uuid: str) -> Response:
        """Delete a saved widget.
        ---
        delete:
          summary: Delete a saved widget
          parameters:
          - in: path
            schema:
              type: string
            name: uuid
          responses:
            200:
              description: Widget deleted
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            DeleteSavedWidgetCommand(uuid).run()
        except CommandException as ex:
            return _command_error(self, ex)
        return self.response(200, message="OK")

    @expose("/data", methods=("POST",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.data",
        log_to_statsd=False,
    )
    def data(self) -> Response:
        """Run a widget's query.
        ---
        post:
          summary: Get a widget's data
          description: >-
            The widget is a saved widget (`id`) or an inline spec (`widget`).
            The query is built on the server from its props; the request can
            only AND structured column filters onto it.
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/WidgetDataPostSchema'
          responses:
            200:
              description: Query result
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        $ref: '#/components/schemas/WidgetDataResponseSchema'
            400:
              $ref: '#/components/responses/400'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            body = WidgetDataPostSchema().load(request.get_json(silent=True) or {})
        except ValidationError as error:
            return _bad_request(self, error)
        filters = body.pop("filters")
        try:
            result = WidgetDataCommand(body, filters).run()
        except CommandException as ex:
            return _command_error(self, ex)
        return _result_response(result)

    @expose("/values", methods=("POST",))
    @json_auth_errors
    @protect()
    @safe
    @statsd_metrics
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.values",
        log_to_statsd=False,
    )
    def values(self) -> Response:
        """Distinct values for a filter widget's column.
        ---
        post:
          summary: Get a filter widget's values
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/WidgetValuesPostSchema'
          responses:
            200:
              description: Distinct values
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        type: array
                        items:
                          oneOf:
                            - type: string
                            - type: integer
                            - type: number
                            - type: boolean
            400:
              $ref: '#/components/responses/400'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            body = WidgetValuesPostSchema().load(request.get_json(silent=True) or {})
        except ValidationError as error:
            return _bad_request(self, error)
        try:
            result = WidgetValuesCommand(body).run()
        except CommandException as ex:
            return _command_error(self, ex)
        return _result_response(result)

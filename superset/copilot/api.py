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

"""Authenticated browser routes and scoped tool callbacks for the agent."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any, cast, TYPE_CHECKING
from uuid import UUID, uuid4

import requests
from flask import abort, current_app, Flask, jsonify, request, Response
from flask_appbuilder.api import expose, protect
from flask_login import current_user
from pydantic import ValidationError
from werkzeug.exceptions import RequestEntityTooLarge

from superset import is_feature_enabled, security_manager
from superset.commands.dashboard_v2.save import CreateDashboardV2Command
from superset.commands.exceptions import CommandException
from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    SavedWidgetNotFoundError,
)
from superset.commands.widget.saved import GetSavedWidgetCommand
from superset.copilot.classic import create_classic_dashboard
from superset.copilot.contracts import (
    AggregateArguments,
    APPROVAL_AUDIENCE,
    APPROVAL_TTL,
    CopilotConversation,
    DashboardApproval,
    DashboardProposal,
    MAX_BODY_BYTES,
    ProfileArguments,
    RUN_AUDIENCE,
    RUN_TTL,
    RunIdentity,
    SavedWidgetArguments,
    sign_claims,
    ToolRequest,
    verify_claims,
)
from superset.copilot.semantic_catalog import (
    approve_semantic_dashboard,
    semantic_catalog_available,
    SemanticCatalogApprovalError,
    SemanticCatalogPreviewError,
    SemanticCatalogUnavailableError,
    stage_semantic_dashboard,
)
from superset.copilot.services import (
    aggregate_dataset,
    CopilotAccessError,
    CopilotToolError,
    profile_dataset,
    read_metadata,
    validate_dashboard_proposal,
    validate_proposal_references,
)
from superset.copilot.upload import CSV_MAX_BYTES, CSVUploadError, upload_csv_dataset
from superset.dashboard_v2.document import DocumentValidationError, parse_strict_json
from superset.exceptions import SupersetSecurityException
from superset.extensions import appbuilder, csrf
from superset.extensions.storage.persistent_dao import (
    ExtensionStorageDAO,
    ExtensionStorageListPayloadTooLarge,
    ExtensionStorageQuotaExceeded,
    ExtensionStorageValueTooLarge,
)
from superset.utils import json
from superset.utils.core import override_user
from superset.utils.decorators import transaction
from superset.views.base_api import BaseSupersetApi

if TYPE_CHECKING:
    from flask_appbuilder.security.sqla.models import User

logger = logging.getLogger(__name__)
TOOL_ROUTE = "/api/v1/nxtbi_copilot/internal/tools"
COPILOT_EXTENSION_ID = "nxtbi.ai-copilot"
HISTORY_RESOURCE_TYPE = "copilot_conversation"
HISTORY_RESOURCE_UUID = "0ce6e8ba-cf58-40e3-bca3-81f8a707c468"
HISTORY_PAGE_SIZE = 10
MAX_HISTORY_BODY_BYTES = 512 * 1024


def _body(max_bytes: int = MAX_BODY_BYTES) -> dict[str, Any]:
    """Bound bytes and reject ambiguous or deeply nested JSON before parsing."""
    if not request.is_json:
        abort(415)
    if request.content_length and request.content_length > max_bytes:
        abort(413)
    raw = request.stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        abort(413)
    try:
        value = parse_strict_json(raw, 24)
    except DocumentValidationError:
        abort(400)
    if not isinstance(value, dict):
        abort(400)
    return value


def _actor() -> User:
    """Require an active browser session, excluding embedded and JWT identities."""
    user = current_user._get_current_object()  # pylint: disable=protected-access
    if (
        not user.is_authenticated
        or not user.is_active
        or security_manager.is_guest_user()
    ):
        abort(401)
    return cast("User", user)


def _secret() -> str:
    """Read the Copilot secret from operator configuration."""
    return cast(str, current_app.config["NXTBI_COPILOT_SHARED_SECRET"])


def _require_widgets() -> None:
    """Require the feature flag for saved widgets and V2 proposals."""
    if not is_feature_enabled("DASHBOARD_V2"):
        abort(404)


def _relay(response: requests.Response) -> Iterator[bytes]:
    """Stream the response and close the agent connection on cancellation."""
    try:
        yield from response.iter_content(chunk_size=1024)
    except requests.RequestException:
        logger.info("Copilot agent stream closed before completion")
    finally:
        response.close()


def _tool_actor() -> User:
    """Resolve the actor from the verified internal run capability."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    try:
        if scheme.lower() != "bearer":
            raise ValueError
        claims = verify_claims(_secret(), token, RUN_AUDIENCE, RUN_TTL)
        if claims.get("host") != "superset":
            raise ValueError
        actor_id = int(claims["sub"])
        if not 0 < actor_id <= 2**31 - 1:
            raise ValueError
    except ValueError:
        abort(401)
    user = security_manager.get_user_by_id(actor_id)
    if not user or not user.is_active:
        abort(401)
    return cast("User", user)


def _preview_dashboard(arguments: dict[str, Any], user_id: int) -> Response:
    """Validate one proposal and bind its format to the approval capability."""
    proposal = DashboardProposal.model_validate(arguments)
    if proposal.dashboard_type == "v2":
        _require_widgets()
        validate_dashboard_proposal(proposal)
    else:
        validate_proposal_references(proposal)
    return jsonify(
        **proposal.model_dump(by_alias=True, exclude_none=True, exclude_unset=True),
        approvalToken=sign_claims(
            _secret(),
            {
                "aud": APPROVAL_AUDIENCE,
                "sub": str(user_id),
                "exp": int(time.time()) + APPROVAL_TTL,
                "uuid": str(uuid4()),
                "dashboard_type": proposal.dashboard_type,
            },
        ),
    )


def _internal_tools() -> Response:
    """Run a narrow operation for the current permissions of a verified actor."""
    user = _tool_actor()
    try:
        call = ToolRequest.model_validate(_body())
        with override_user(user):
            if call.name == "profile_dataset":
                return jsonify(
                    profile_dataset(ProfileArguments.model_validate(call.arguments))
                )
            if call.name == "aggregate_dataset":
                return jsonify(
                    aggregate_dataset(AggregateArguments.model_validate(call.arguments))
                )
            if call.name == "get_saved_widget":
                _require_widgets()
                if not security_manager.can_access("can_read", "Chart"):
                    abort(403)
                ref = str(UUID(SavedWidgetArguments.model_validate(call.arguments).id))
                try:
                    GetSavedWidgetCommand(ref).run()
                except (SavedWidgetForbiddenError, SavedWidgetNotFoundError):
                    abort(403)
                return jsonify(id=ref)
            if call.name != "propose_dashboard":
                return jsonify(read_metadata(user, call))
            return _preview_dashboard(call.arguments, user.id)
    except (CopilotAccessError, SupersetSecurityException):
        abort(403)
    except (ValidationError, CommandException, ValueError):
        abort(422)
    except CopilotToolError:
        abort(502)


class NxtbiCopilotRestApi(BaseSupersetApi):
    """Access the Copilot as the logged-in Superset browser user."""

    resource_name = "nxtbi_copilot"
    allow_browser_login = True
    class_permission_name = "Dashboard"
    method_permission_name = {
        "run": "read",
        "approve": "write",
        "semantic_catalog": "read",
        "draft_semantic_catalog": "write",
        "approve_semantic_catalog": "write",
        "get_history": "read",
        "save_history": "read",
        "upload_csv": "read",
    }

    @expose("/semantic_catalog", methods=("GET",))
    @protect()
    def semantic_catalog(self) -> Response:
        """Report availability for the authenticated dashboard author."""
        _actor()
        response = jsonify(available=semantic_catalog_available())
        response.cache_control.no_store = True
        return response

    @expose("/semantic_catalog/draft", methods=("POST",))
    @protect()
    def draft_semantic_catalog(self) -> Response:
        """Resolve a metric request and preview a bounded native dashboard draft."""
        actor = _actor()
        try:
            result = stage_semantic_dashboard(_body(4096), actor.id, _secret())
        except (SemanticCatalogUnavailableError, SupersetSecurityException):
            return self.response(404, message="The semantic catalog is unavailable.")
        except SemanticCatalogPreviewError:
            return self.response(502, message="The semantic preview could not run.")
        except ValueError:
            return self.response(422, message="Check the requested semantic metric.")
        response = jsonify(result)
        response.cache_control.no_store = True
        return response

    @expose("/semantic_catalog/approve", methods=("POST",))
    @protect()
    def approve_semantic_catalog(self) -> Response:
        """Save a confirmed semantic draft through native dashboard commands."""
        actor = _actor()
        try:
            dashboard_id, created = approve_semantic_dashboard(
                _body(4096), actor.id, _secret()
            )
        except SemanticCatalogUnavailableError:
            return self.response(404, message="The semantic catalog is unavailable.")
        except (SemanticCatalogApprovalError, SupersetSecurityException):
            return self.response(403, message="This dashboard approval is unavailable.")
        except CommandException as error:
            return self.response(error.status, message=str(error.message))
        except ValueError:
            return self.response(422, message="Check the semantic dashboard draft.")
        response = self.response(
            201 if created else 200, id=dashboard_id, url=f"/dashboard/{dashboard_id}/"
        )
        response.cache_control.no_store = True
        return response

    @expose("/upload/", methods=("POST",))
    @protect()
    def upload_csv(self) -> Response:
        """Import one CSV as the authenticated browser user."""
        user = _actor()
        if not security_manager.can_access("can_upload", "Database"):
            return self.response(403, message="Your account cannot upload data files.")
        if request.mimetype != "multipart/form-data":
            return self.response(415, message="Use a multipart CSV upload.")
        # Allow space for the form boundaries and upload identity while the
        # upload service checks the file's exact byte count separately.
        body_limit = CSV_MAX_BYTES + 64 * 1024
        if (
            request.max_content_length is None
            or request.max_content_length > body_limit
        ):
            request.max_content_length = body_limit
        request.max_form_parts = 2
        try:
            files = request.files.getlist("file")
            upload_ids = request.form.getlist("upload_id")
        except RequestEntityTooLarge:
            return self.response(413, message="The CSV exceeds the file size limit.")
        if len(files) != 1 or len(upload_ids) != 1:
            return self.response(422, message="Choose one CSV file to upload.")
        try:
            upload_id = UUID(upload_ids[0])
            if upload_id.version != 4:
                raise ValueError
        except ValueError:
            return self.response(422, message="Invalid CSV upload identity.")
        try:
            dataset = upload_csv_dataset(files[0], upload_id, user.id)
        except CSVUploadError as ex:
            return self.response(ex.status, message=str(ex), **ex.details)
        return self.response(201, **dataset)

    @expose("/history", methods=("GET",))
    @protect()
    def get_history(self) -> Response:
        """Return recent transcripts owned by the authenticated browser user."""
        user = _actor()
        try:
            entries, _ = ExtensionStorageDAO.list_entries(
                COPILOT_EXTENSION_ID,
                user_fk=user.id,
                resource_type=HISTORY_RESOURCE_TYPE,
                resource_uuid=HISTORY_RESOURCE_UUID,
                page_size=HISTORY_PAGE_SIZE,
            )
        except ExtensionStorageListPayloadTooLarge as ex:
            return self.response(ex.status, message=ex.message)

        conversations = []
        for entry in entries:
            if entry.codec != "json" or entry.value is None:
                continue
            try:
                conversation = CopilotConversation.model_validate(
                    json.loads(entry.value)
                )
            except ValueError:
                continue
            if conversation.thread_id == entry.key:
                conversations.append(
                    conversation.model_dump(by_alias=True, exclude_none=True)
                )
        response = jsonify(result=conversations)
        response.cache_control.no_store = True
        return response

    @expose("/history", methods=("PUT",))
    @protect()
    @transaction()
    def save_history(self) -> Response:
        """Store an encrypted transcript under its owner's account."""
        user = _actor()
        try:
            conversation = CopilotConversation.model_validate(
                _body(MAX_HISTORY_BODY_BYTES)
            )
            encoded = json.dumps(
                conversation.model_dump(by_alias=True, exclude_none=True),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (ValidationError, UnicodeEncodeError):
            return self.response(422, message="Invalid Copilot transcript.")
        try:
            ExtensionStorageDAO.set(
                COPILOT_EXTENSION_ID,
                conversation.thread_id,
                encoded,
                user_fk=user.id,
                resource_type=HISTORY_RESOURCE_TYPE,
                resource_uuid=HISTORY_RESOURCE_UUID,
                encrypt=True,
            )
        except (ExtensionStorageQuotaExceeded, ExtensionStorageValueTooLarge) as ex:
            return self.response(ex.status, message=ex.message)
        return Response(status=204)

    @expose("/run", methods=("POST",))
    @protect()
    def run(self) -> Response:
        """Start an authenticated AG-UI server-sent event stream."""
        user = _actor()
        body = _body()
        try:
            identity = RunIdentity.model_validate(body)
        except ValidationError:
            return self.response(422, message="Invalid Copilot run identity.")
        token = sign_claims(
            _secret(),
            {
                "aud": RUN_AUDIENCE,
                "host": "superset",
                "sub": str(user.id),
                "exp": int(time.time()) + RUN_TTL,
                "run_id": identity.run_id,
                "thread_id": identity.thread_id,
            },
        )
        try:
            response = requests.post(
                current_app.config["NXTBI_COPILOT_AGENT_URL"],
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "text/event-stream",
                },
                stream=True,
                timeout=(5, 125),
                allow_redirects=False,
            )
        except requests.RequestException:
            return self.response(503, message="The Copilot service is unavailable.")
        if (
            response.status_code != 200
            or "text/event-stream" not in response.headers.get("Content-Type", "")
        ):
            status = response.status_code
            response.close()
            if status == 429:
                return self.response(
                    429, message="The Copilot is busy. Try again shortly."
                )
            if status in (400, 413, 422):
                return self.response(422, message="The Copilot request is invalid.")
            return self.response(503, message="The Copilot could not start.")
        return Response(
            _relay(response),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @expose("/approve", methods=("POST",))
    @protect()
    def approve(self) -> Response:
        """Validate a confirmed proposal and create the dashboard exactly once."""
        user = _actor()
        try:
            proposal = DashboardApproval.model_validate(_body())
        except ValidationError:
            return self.response(422, message="Invalid dashboard proposal.")
        try:
            claims = verify_claims(
                _secret(), proposal.approval_token, APPROVAL_AUDIENCE, APPROVAL_TTL
            )
            if (
                claims["sub"] != str(user.id)
                or claims.get("dashboard_type", "v2") != proposal.dashboard_type
            ):
                raise ValueError
            approval_uuid = UUID(claims["uuid"])
        except (KeyError, ValueError):
            return self.response(
                403, message="This dashboard approval has expired or is unavailable."
            )
        if proposal.dashboard_type == "v2":
            _require_widgets()
        try:
            if proposal.dashboard_type == "v1":
                dashboard_id, created = create_classic_dashboard(
                    proposal, approval_uuid, validate_proposal_references(proposal)
                )
                url = f"/dashboard/{dashboard_id}/"
            else:
                document = validate_dashboard_proposal(proposal)
                command = CreateDashboardV2Command(
                    {
                        "dashboard_title": proposal.title,
                        "document": document,
                        "uuid": approval_uuid,
                    }
                )
                dashboard_id = command.run()["id"]
                created = command.created
                url = f"/dashboard/v2/{dashboard_id}/"
        except (CopilotAccessError, SupersetSecurityException):
            return self.response(403, message="You cannot save this dashboard.")
        except CommandException as err:
            return self.response(err.status, message=str(err.message))
        except ValueError:
            return self.response(
                422, message="Check the dashboard's dataset selections."
            )
        return self.response(
            201 if created else 200,
            id=dashboard_id,
            url=url,
        )


def register_copilot(app: Flask) -> None:
    """Register the opt-in gateway and its bearer-only CSRF-exempt callback."""
    if (
        not app.config.get("NXTBI_COPILOT_AGENT_URL")
        or len(app.config.get("NXTBI_COPILOT_SHARED_SECRET") or "") < 32
    ):
        raise ValueError("Configure the Copilot service URL and signing secret.")
    appbuilder.add_api(NxtbiCopilotRestApi)
    app.add_url_rule(
        TOOL_ROUTE, view_func=csrf.exempt(_internal_tools), methods=["POST"]
    )

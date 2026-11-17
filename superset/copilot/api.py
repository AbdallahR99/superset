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

from superset import is_feature_enabled, security_manager
from superset.commands.dashboard_v2.save import CreateDashboardV2Command
from superset.commands.exceptions import CommandException
from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    SavedWidgetNotFoundError,
)
from superset.commands.widget.saved import GetSavedWidgetCommand
from superset.copilot.contracts import (
    APPROVAL_AUDIENCE,
    APPROVAL_TTL,
    DashboardApproval,
    DashboardProposal,
    MAX_BODY_BYTES,
    RUN_AUDIENCE,
    RUN_TTL,
    RunIdentity,
    SavedWidgetArguments,
    sign_claims,
    ToolRequest,
    verify_claims,
)
from superset.copilot.services import (
    CopilotAccessError,
    CopilotToolError,
    read_metadata,
    validate_dashboard_proposal,
)
from superset.dashboard_v2.document import DocumentValidationError, parse_strict_json
from superset.exceptions import SupersetSecurityException
from superset.extensions import appbuilder, csrf
from superset.utils.core import override_user
from superset.views.base_api import BaseSupersetApi

if TYPE_CHECKING:
    from flask_appbuilder.security.sqla.models import User

logger = logging.getLogger(__name__)
TOOL_ROUTE = "/api/v1/nxtbi_copilot/internal/tools"


def _body() -> dict[str, Any]:
    """Bound bytes and reject ambiguous or deeply nested JSON before parsing."""
    if not request.is_json:
        abort(415)
    if request.content_length and request.content_length > MAX_BODY_BYTES:
        abort(413)
    raw = request.stream.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
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
    """Dashboard proposal and approval are available only with Dashboard V2."""
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


def _internal_tools() -> Response:
    """Run a narrow operation for the current permissions of a verified actor."""
    user = _tool_actor()
    try:
        call = ToolRequest.model_validate(_body())
        with override_user(user):
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
            _require_widgets()
            proposal = DashboardProposal.model_validate(call.arguments)
            validate_dashboard_proposal(proposal)
            return jsonify(
                **proposal.model_dump(by_alias=True, exclude_none=True),
                approvalToken=sign_claims(
                    _secret(),
                    {
                        "aud": APPROVAL_AUDIENCE,
                        "sub": str(user.id),
                        "exp": int(time.time()) + APPROVAL_TTL,
                        "uuid": str(uuid4()),
                    },
                ),
            )
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
    method_permission_name = {"run": "read", "approve": "write"}

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
        _require_widgets()
        user = _actor()
        try:
            proposal = DashboardApproval.model_validate(_body())
        except ValidationError:
            return self.response(422, message="Invalid dashboard proposal.")
        try:
            claims = verify_claims(
                _secret(), proposal.approval_token, APPROVAL_AUDIENCE, APPROVAL_TTL
            )
            if claims["sub"] != str(user.id):
                raise ValueError
            approval_uuid = UUID(claims["uuid"])
        except (KeyError, ValueError):
            return self.response(
                403, message="This dashboard approval has expired or is unavailable."
            )
        try:
            document = validate_dashboard_proposal(proposal)
            command = CreateDashboardV2Command(
                {
                    "dashboard_title": proposal.title,
                    "document": document,
                    "uuid": approval_uuid,
                }
            )
            saved = command.run()
        except (CopilotAccessError, SupersetSecurityException):
            return self.response(403, message="You cannot save this dashboard.")
        except CommandException as err:
            return self.response(err.status, message=str(err.message))
        except ValueError:
            return self.response(
                422, message="Check the dashboard's dataset selections."
            )
        return self.response(
            201 if command.created else 200,
            id=saved["id"],
            url=f"/dashboard/v2/{saved['id']}/",
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

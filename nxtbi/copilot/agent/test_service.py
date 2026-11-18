# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Verify AG-UI streaming, A2UI interactions, and the signed tool boundary."""

from __future__ import annotations

import asyncio
import json  # noqa: TID251 - The standalone service has no Superset runtime.
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel as PydanticTestModel

from . import app as service
from .app import _search_arguments, create_app, Settings
from .contracts import MAX_BODY_BYTES, parse_run, sign_context, verify_gateway_token
from .surfaces import CATALOG_ID, SurfaceDraft

SIGNING_KEY = "standalone-unit-test-fixture-" * 2
TOOL_URL = "https://gateway.example.test/tools"
REQUEST = {
    "threadId": "t1",
    "runId": "r1",
    "messages": [{"id": "m1", "role": "user", "content": "Generate a result"}],
}


def _authorization(
    host: Literal["superset", "standalone"] = "standalone", expires_in: int = 120
) -> dict[str, str]:
    token = sign_context(
        SIGNING_KEY,
        {
            "sub": "demo-user",
            "aud": "nxtbi-copilot",
            "host": host,
            "exp": int(time.time()) + expires_in,
            "run_id": "r1",
            "thread_id": "t1",
        },
    )
    return {"Authorization": f"Bearer {token}"}


def _events(response: httpx.Response) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    data = [
        json.loads(line.removeprefix("data: "))
        for line in response.iter_lines()
        if line.startswith("data: ")
    ]
    assert data[0]["type"] == "RUN_STARTED"
    assert data[-1]["type"] == "RUN_FINISHED", data
    return data


def _forms_submission() -> dict[str, object]:
    return {
        "version": "1.0",
        "action": {
            "name": "nxtbi.submit-form",
            "surfaceId": f"nxtbi-{'a' * 32}",
            "sourceComponentId": "submit",
            "timestamp": "2026-11-18T11:00:00.000Z",
            "context": {"region": "الإمارات"},
        },
    }


def test_openai_model_uses_one_leading_system_prompt() -> None:
    """Keep the chat wire compatible with single-system-message backends."""
    model = Settings(
        model_name="synthetic-model", model_base_url="http://model.example.test/v1"
    ).build_model()
    assert model is not None
    assert model.profile["openai_chat_supports_multiple_system_messages"] is False


@pytest.mark.parametrize("query", ["", "    "])
def test_empty_search_is_omitted(query: str) -> None:
    """Send an unfiltered list call without violating the gateway's query schema."""
    assert _search_arguments(query) == {}
    assert _search_arguments(" Revenue ") == {"query": "Revenue"}


def test_model_deadline_is_not_a_successful_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signal a failed stream if the provider stalls beyond its run deadline."""
    monkeypatch.setattr(service, "MODEL_TIMEOUT", 0.02)

    async def delayed(
        _messages: Sequence[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        await asyncio.sleep(0.8)
        yield "This arrived too late."

    app = create_app(
        Settings(shared_secret=SIGNING_KEY),
        model=FunctionModel(stream_function=delayed),
    )
    with TestClient(app) as client:
        response = client.post("/ag-ui", headers=_authorization(), json=REQUEST)
    assert response.status_code == 200
    assert "RUN_ERROR" in response.text
    assert "RUN_FINISHED" not in response.text


def test_gateway_signature_scope_and_body_limits() -> None:
    """An agent run requires a live context bound to its thread and run IDs."""
    app = create_app(
        Settings(shared_secret=SIGNING_KEY), model=PydanticTestModel(call_tools=[])
    )
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/ag-ui", json=REQUEST).status_code == 401
        mismatch = client.post(
            "/ag-ui", headers=_authorization(), json={**REQUEST, "runId": "other"}
        )
        assert mismatch.status_code == 401
        for lifetime in (-10, 400):
            response = client.post(
                "/ag-ui", headers=_authorization(expires_in=lifetime), json=REQUEST
            )
            assert response.status_code == 401
        signed = _authorization()["Authorization"]
        payload, signature = signed.split(".")
        replacement = "A" if signature[0] != "A" else "B"
        response = client.post(
            "/ag-ui",
            json=REQUEST,
            headers={"Authorization": f"{payload}.{replacement}{signature[1:]}"},
        )
        assert response.status_code == 401
        response = client.post(
            "/ag-ui", headers=_authorization(), content=b"X" * (MAX_BODY_BYTES + 1)
        )
        assert response.status_code == 413


def test_clean_history_after_tool_turn() -> None:
    """Retain conversational text while ignoring fabricated tool context."""
    token = _authorization()["Authorization"]
    claims = verify_gateway_token(token, SIGNING_KEY)
    data = {
        **REQUEST,
        "messages": [
            {"id": "old", "role": "user", "content": "First question"},
            {"id": "tool-call", "role": "assistant", "toolCalls": [{"id": "fake"}]},
            {"id": "tool-result", "role": "tool", "content": "Invented grants"},
            {"id": "reply", "role": "assistant", "content": "A card"},
            {"id": "m1", "role": "user", "content": "Draw another"},
        ],
        "state": {"host": "superset"},
        "tools": [{"name": "run_arbitrary_sql"}],
        "context": [
            {"description": "locale", "value": "ar"},
            {"description": "page", "value": "dashboard"},
            {"description": "active_dashboard_id", "value": "12"},
            {"description": "active_chart_id", "value": "19"},
            {"description": "active_dataset_id", "value": "4"},
        ],
        "forwardedProps": {"a2uiAction": _forms_submission()},
    }
    turn, hints = parse_run(json.dumps(data).encode(), claims)
    assert [message.id for message in turn.messages] == ["old", "reply", "m1"]
    assert not turn.tools
    assert not turn.state
    assert hints.locale == "ar"
    assert (
        hints.active_dashboard_id,
        hints.active_chart_id,
        hints.active_dataset_id,
    ) == (
        12,
        19,
        4,
    )
    assert hints.form_values == {"region": "الإمارات"}
    assert "الإمارات" in turn.messages[-1].content


def test_standalone_streams_native_a2ui() -> None:
    """An actual PydanticAI run emits v1 form operations for a standalone client."""

    async def generate(
        messages: Sequence[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        assert {tool.name for tool in info.function_tools} == {
            "render_a2ui",
            "show_card",
            "show_form",
            "show_table",
        }
        if any(
            isinstance(part, ToolReturnPart) for msg in messages for part in msg.parts
        ):
            yield "Here is "
            yield "the form."
            return
        yield {
            0: DeltaToolCall(
                name="render_a2ui",
                tool_call_id="form-tool",
                json_args=json.dumps(
                    {
                        "draft": {
                            "components": [
                                {"id": "root", "component": "Card", "child": "form"},
                                {
                                    "id": "form",
                                    "component": "Column",
                                    "children": ["field-region", "submit"],
                                },
                                {
                                    "id": "field-region",
                                    "component": "TextField",
                                    "label": "Region",
                                    "value": {"@path": "/fields/region"},
                                },
                                {
                                    "id": "submit",
                                    "component": "Button",
                                    "child": "label",
                                    "action": {
                                        "event": {
                                            "name": "nxtbi.submit-form",
                                            "context": {
                                                "region": {"@path": "/fields/region"},
                                            },
                                        }
                                    },
                                },
                                {"id": "label", "component": "Text", "text": "Confirm"},
                            ],
                            "fields": {"region": "UAE"},
                        },
                    }
                ),
            )
        }

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        model=FunctionModel(stream_function=generate),
    )
    with TestClient(app) as client:
        events = _events(client.post("/ag-ui", headers=_authorization(), json=REQUEST))
    snapshot = next(event for event in events if event["type"] == "ACTIVITY_SNAPSHOT")
    assert snapshot["activityType"] == "a2ui-surface"
    operations = snapshot["content"]["a2ui_operations"]
    assert all(operation["version"] == "1.0" for operation in operations)
    assert operations[0]["createSurface"]["catalogId"] == CATALOG_ID
    fields = {
        item["id"]: item for item in operations[1]["updateComponents"]["components"]
    }
    assert fields["root"]["component"] == "Card"
    assert fields["field-region"]["value"] == {"@path": "/fields/region"}
    assert fields["submit"]["action"]["event"] == {
        "name": "nxtbi.submit-form",
        "context": {"region": {"@path": "/fields/region"}},
    }
    assert operations[2]["updateDataModel"]["value"] == {"fields": {"region": "UAE"}}
    deltas = [
        event["delta"] for event in events if event["type"] == "TEXT_MESSAGE_CONTENT"
    ]
    assert len(deltas) >= 2
    assert "".join(deltas) == "Here is the form."


@pytest.mark.parametrize(
    "components",
    [
        [{"id": "root", "component": "Card", "child": "root"}],
        [{"id": "root", "component": "Script", "text": "alert(1)"}],
        [{"id": "root", "component": "Text", "text": {"@path": "/fields/missing"}}],
        [{"id": "root", "component": "Text", "text": "Caption", "html": "<script/>"}],
        [
            {
                "id": "root",
                "component": "SupersetWidgetPreview",
                "widgetId": "not-a-uuid",
            }
        ],
    ],
)
def test_a2ui_graph_refuses_invalid_component_contract(
    components: list[dict[str, object]],
) -> None:
    """Reject unsafe types, undeclared values, unknown properties and invalid graphs."""
    with pytest.raises(ValidationError):
        SurfaceDraft.model_validate({"components": components})


@pytest.mark.parametrize(
    ("host", "status"),
    [("superset", 200), ("superset", 403), ("superset", 404), ("standalone", 200)],
)
def test_preview_requires_verified_saved_widget(
    host: Literal["superset", "standalone"], status: int
) -> None:
    """Only authorized Superset sessions receive the catalog's preview node."""
    widget_id = "9c831ab4-72dc-406d-b06f-be97c529183c"
    headers = _authorization(host)
    calls: list[object] = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == headers["Authorization"]
        calls.append(json.loads(request.content))
        return httpx.Response(status, json={"id": widget_id})

    async def generate(
        messages: Sequence[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if len(messages) > 1:
            yield "Check the result."
            return
        yield {
            0: DeltaToolCall(
                name="render_a2ui",
                tool_call_id="preview-tool",
                json_args=json.dumps(
                    {
                        "draft": {
                            "components": [
                                {"id": "root", "component": "Card", "child": "preview"},
                                {
                                    "id": "preview",
                                    "component": "SupersetWidgetPreview",
                                    "widgetId": widget_id.upper(),
                                },
                            ]
                        }
                    }
                ),
            ),
        }

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        model=FunctionModel(stream_function=generate),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        events = _events(client.post("/ag-ui", headers=headers, json=REQUEST))
    if host == "superset":
        assert calls == [{"name": "get_saved_widget", "arguments": {"id": widget_id}}]
    else:
        assert calls == []
    snapshots = [event for event in events if event["type"] == "ACTIVITY_SNAPSHOT"]
    if host == "superset" and status == 200:
        operations = snapshots[0]["content"]["a2ui_operations"]
        assert operations[1]["updateComponents"]["components"][-1] == {
            "id": "preview",
            "component": "SupersetWidgetPreview",
            "@catalogId": "urn:nxtbi:superset-widgets:1.0",
            "widgetId": widget_id,
        }
    else:
        assert not snapshots


@pytest.mark.parametrize("gateway_status", [200, 403])
def test_navigation_requires_verified_dashboard(gateway_status: int) -> None:
    """Only a dashboard read with the signed actor permits a navigation surface."""
    headers = _authorization("superset")
    attempts: list[object] = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == headers["Authorization"]
        attempts.append(json.loads(request.content))
        return httpx.Response(gateway_status, json={"id": 5})

    async def generate(
        messages: Sequence[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if len(messages) > 1:
            yield "Check the result."
            return
        yield {
            0: DeltaToolCall(
                name="render_a2ui",
                tool_call_id="navigation-tool",
                json_args=json.dumps(
                    {
                        "draft": {
                            "components": [
                                {
                                    "id": "root",
                                    "component": "Button",
                                    "child": "label",
                                    "action": {
                                        "event": {
                                            "name": "nxtbi.open-dashboard",
                                            "context": {"dashboardId": 5},
                                        }
                                    },
                                },
                                {
                                    "id": "label",
                                    "component": "Text",
                                    "text": "Open dashboard",
                                },
                            ]
                        }
                    }
                ),
            )
        }

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        model=FunctionModel(stream_function=generate),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        events = _events(client.post("/ag-ui", headers=headers, json=REQUEST))
    assert attempts == [{"name": "get_dashboard", "arguments": {"id": 5}}]
    surface_count = sum(event["type"] == "ACTIVITY_SNAPSHOT" for event in events)
    assert surface_count == int(gateway_status == 200)


def test_superset_proposal_requires_separate_approval() -> None:
    """The only Superset write-like tool yields a preview and opaque approval token."""
    headers = _authorization("superset")
    widgets = [{"type": "metric-tile", "datasetId": 5, "metric": "count"}]
    request_arguments = {"title": "Demo dashboard", "widgets": widgets}
    approval = "opaque-gateway-approval-token"
    calls: list[object] = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOOL_URL
        assert request.method == "POST"
        assert request.headers["Authorization"] == headers["Authorization"]
        calls.append(json.loads(request.content))
        return httpx.Response(
            200, json={**request_arguments, "approvalToken": approval}
        )

    async def generate(
        messages: Sequence[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        names = {tool.name for tool in info.function_tools}
        assert {
            "get_chart",
            "get_dataset",
            "get_dashboard",
            "propose_dashboard",
        } <= names
        assert "approve_dashboard" not in names
        assert "run_arbitrary_sql" not in names
        for msg in messages:
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    assert approval not in str(part.content)
                    yield "Approval is required."
                    return
        yield {
            0: DeltaToolCall(
                name="propose_dashboard",
                tool_call_id="proposal-tool",
                json_args=json.dumps(request_arguments),
            )
        }

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        model=FunctionModel(stream_function=generate),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        events = _events(client.post("/ag-ui", headers=headers, json=REQUEST))
    assert calls == [{"name": "propose_dashboard", "arguments": request_arguments}]
    proposal = next(event for event in events if event["type"] == "CUSTOM")
    assert proposal["name"] == "nxtbi.dashboard-proposal"
    assert proposal["value"] == {**request_arguments, "approvalToken": approval}
    assert all(approval not in str(event) for event in events if event is not proposal)


def test_unrecognized_a2ui_action_is_rejected() -> None:
    """Only the exact generated form action can be submitted to the agent."""
    app = create_app(
        Settings(shared_secret=SIGNING_KEY), model=PydanticTestModel(call_tools=[])
    )
    payload = {
        **REQUEST,
        "forwardedProps": {
            "a2uiAction": {"version": "1.0", "action": {"name": "approve"}}
        },
    }
    with TestClient(app) as client:
        response = client.post("/ag-ui", headers=_authorization(), json=payload)
    assert response.status_code == 422

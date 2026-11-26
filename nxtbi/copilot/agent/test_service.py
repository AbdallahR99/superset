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
from pydantic import TypeAdapter, ValidationError
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel as PydanticTestModel

from . import app as service
from .app import _search_arguments, create_app, Settings
from .contracts import (
    DashboardDraft,
    MAX_BODY_BYTES,
    parse_run,
    sign_context,
    verify_gateway_token,
    WidgetDraft,
)
from .surfaces import CATALOG_ID, dashboard_evidence, SurfaceDraft

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


def test_caption_suggestions_use_only_captions_and_no_function_tools() -> None:
    request = {
        "sourceLocale": "en",
        "targetLocale": "ar",
        "captions": ["Sales", None, "Revenue", "Keep this abbreviation"],
    }

    def translate(messages: Sequence[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert not info.function_tools
        (output,) = info.output_tools
        prompts = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]
        (prompt,) = prompts
        assert isinstance(prompt, str)
        assert json.loads(prompt) == request
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output.name,
                    {
                        "captions": [
                            "المبيعات",
                            "لا عنوان",
                            "إجمالي الإيرادات",
                            "Keep this abbreviation",
                        ]
                    },
                )
            ]
        )

    client = TestClient(
        create_app(
            Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
            model=FunctionModel(function=translate),
        )
    )
    result = _events(
        client.post(
            "/ag-ui",
            headers=_authorization("superset"),
            json={
                **REQUEST,
                "context": [{"description": "page", "value": "A private page"}],
                "forwardedProps": {"dashboardLocalization": request},
            },
        )
    )

    assert [event["type"] for event in result] == [
        "RUN_STARTED",
        "CUSTOM",
        "RUN_FINISHED",
    ]
    assert result[1]["name"] == "nxtbi.dashboard-caption-suggestions"
    assert result[1]["value"] == {
        "targetLocale": "ar",
        "captions": ["المبيعات", None, "إجمالي الإيرادات", None],
    }


@pytest.mark.parametrize(
    ("source", "target", "supplied", "expected"),
    [
        (
            "en",
            "ar",
            ["Sales", "Unknown Name", "Revenue"],
            ["المبيعات", None, "الإيرادات"],
        ),
        ("ar", "en", ["المبيعات", None, "الإيرادات"], ["Sales", None, "Revenue"]),
    ],
)
def test_caption_suggestions_have_a_known_word_fallback(
    source: str, target: str, supplied: list[str | None], expected: list[str | None]
) -> None:
    client = TestClient(create_app(Settings(shared_secret=SIGNING_KEY)))
    events = _events(
        client.post(
            "/ag-ui",
            headers=_authorization("superset"),
            json={
                **REQUEST,
                "forwardedProps": {
                    "dashboardLocalization": {
                        "sourceLocale": source,
                        "targetLocale": target,
                        "captions": supplied,
                    }
                },
            },
        )
    )
    assert events[1]["value"] == {"targetLocale": target, "captions": expected}


@pytest.mark.parametrize(
    ("host", "extra", "context", "forwarded"),
    [
        ("standalone", {}, [], {}),
        ("superset", {"targetLocale": "en"}, [], {}),
        ("superset", {"targetLocale": "fr"}, [], {}),
        ("superset", {"captions": [" "]}, [], {}),
        ("superset", {"captions": ["Sales", True]}, [], {}),
        ("superset", {"captions": ["Sales", "x" * 257]}, [], {}),
        ("superset", {"captions": ["Sales"] * 10}, [], {}),
        ("superset", {"datasetId": 8}, [], {}),
        ("superset", {}, [], {"a2uiAction": None}),
        (
            "superset",
            {},
            [
                {"description": "uploaded_dataset_id", "value": "7"},
                {"description": "uploaded_dataset_action", "value": "draft"},
            ],
            {},
        ),
    ],
)
def test_caption_suggestions_reject_invalid_or_mixed_intent(
    host: Literal["superset", "standalone"],
    extra: dict[str, object],
    context: list[dict[str, str]],
    forwarded: dict[str, object],
) -> None:
    forwarded_props: dict[str, object] = {
        "dashboardLocalization": {
            "sourceLocale": "en",
            "targetLocale": "ar",
            "captions": ["Sales"],
            **extra,
        },
        **forwarded,
    }
    client = TestClient(create_app(Settings(shared_secret=SIGNING_KEY)))
    response = client.post(
        "/ag-ui",
        headers=_authorization(host),
        json={
            **REQUEST,
            "context": context,
            "forwardedProps": forwarded_props,
        },
    )
    assert response.status_code == 422


def _evidence_nodes(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Read the single native evidence surface emitted by a verified draft."""
    activities = [e for e in events if e["type"] == "ACTIVITY_SNAPSHOT"]
    if not activities:
        return {}
    (evidence,) = activities
    assert evidence["activityType"] == "a2ui-surface"
    operations = evidence["content"]["a2ui_operations"]
    assert all(operation["version"] == "1.0" for operation in operations)
    return {
        node["id"]: node for node in operations[1]["updateComponents"]["components"]
    }


@pytest.mark.parametrize(
    ("table_name", "description", "expected"),
    [
        (
            "copilot_csv_0123456789abcdef01234567",
            "Uploaded through Copilot from Demo orders.csv.",
            "Demo orders.csv",
        ),
        (
            "copilot_csv_0123456789abcdef01234567",
            "Uploaded through Copilot from private/orders.csv.",
            "copilot_csv_0123456789abcdef01234567",
        ),
        (
            "ordinary_orders",
            "Uploaded through Copilot from other.csv.",
            "ordinary_orders",
        ),
    ],
)
def test_evidence_uses_only_valid_copilot_upload_display_names(
    table_name: str, description: str, expected: str
) -> None:
    """Present a recognizable filename and retain the dataset reference."""
    surface = dashboard_evidence(
        {"table_name": table_name, "description": description},
        "Records",
        {"dataset_id": 47, "rows": [{"value": 1}]},
        None,
        locale="en",
    )
    assert surface is not None
    nodes = _evidence_nodes([surface.model_dump(mode="json", by_alias=True)])
    assert nodes["source"]["text"] == f"{expected} · #47"


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


@pytest.mark.parametrize(
    ("host", "value", "expected"),
    [
        ("superset", "47", 47),
        ("superset", "2147483648", None),
        ("superset", 47, None),
        ("superset", "47\nraw CSV", None),
        ("standalone", "47", None),
    ],
)
def test_uploaded_dataset_hint_accepts_only_scoped_numeric_ids(
    host: Literal["superset", "standalone"], value: object, expected: int | None
) -> None:
    """Accept a numeric Superset hint without allowing the context to authorize it."""
    authorization = _authorization(host)["Authorization"]
    claims = verify_gateway_token(authorization, SIGNING_KEY)
    request = {
        **REQUEST,
        "context": [{"description": "uploaded_dataset_id", "value": value}],
    }
    _, hints = parse_run(json.dumps(request).encode(), claims)
    assert hints.uploaded_dataset_id == expected


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
    token = _authorization("superset")["Authorization"]
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
            {"description": "content_locale", "value": "en"},
            {"description": "dashboard_type", "value": "v1"},
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
    assert hints.content_locale == "en"
    assert hints.dashboard_type == "v1"
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


@pytest.mark.parametrize(
    ("tool_name", "arguments", "evidence"),
    [
        (
            "profile_dataset",
            {"id": 4},
            {"dataset_id": 4, "row_count": 8, "columns": []},
        ),
        (
            "aggregate_dataset",
            {
                "id": 4,
                "metric": "population",
                "dimension": "district",
                "filter": {"column": "year", "value": 2024},
            },
            {
                "dataset_id": 4,
                "metric": "population",
                "dimension": "district",
                "rows": [{"group": "North", "value": 1400}],
                "truncated": False,
            },
        ),
    ],
)
def test_dataset_evidence_reaches_model(
    tool_name: str, arguments: dict[str, object], evidence: dict[str, object]
) -> None:
    """Read evidence through the signed gateway and preserve its scope and values."""
    headers = _authorization("superset")
    calls: list[object] = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == headers["Authorization"]
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=evidence)

    async def generate(
        messages: Sequence[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        for message in messages:
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    assert part.content == evidence
                    yield "The dataset was assessed."
                    return
        yield {
            0: DeltaToolCall(
                name=tool_name, tool_call_id="evidence", json_args=json.dumps(arguments)
            )
        }

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        model=FunctionModel(stream_function=generate),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        events = _events(client.post("/ag-ui", headers=headers, json=REQUEST))
    assert calls == [{"name": tool_name, "arguments": arguments}]
    assert any(event.get("delta") == "The dataset was assessed." for event in events)


def test_model_filter_decodes_only_strict_objects() -> None:
    """A quoted JSON object from the model becomes a typed gateway filter."""
    adapter = TypeAdapter(service.ModelFilter)
    expected = {"column": "census_year", "value": 2026}
    assert adapter.validate_python(json.dumps(expected)).model_dump() == expected
    for invalid in (
        "{",
        "[]",
        "null",
        " " * 2049,
        '{"column":"census_year","value":[]}',
        '{"column":"census_year","value":2026,"extra":true}',
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)


def test_model_title_translations_decode_only_supported_captions() -> None:
    """Only the model boundary can normalize a provider-encoded title object."""
    adapter = TypeAdapter(service.ModelTitleTranslations)
    assert adapter.validate_python('{"en":"Demo"}').en == "Demo"
    for invalid in ('{"en":23}', '{"fr":"Demo"}', "[]", "null"):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "metric-tile"},
        {"metric": "population"},
        {"dimension": None},
        {"metrics": []},
        {"metrics": [f"metric{i}" for i in range(7)]},
        {"dimensions": [f"group{i}" for i in range(5)]},
        {"dimensions": ["population"]},
        {"dimensions": None},
    ],
)
def test_grouped_table_requires_exclusive_bounded_arrays(
    overrides: dict[str, object],
) -> None:
    """Reject incompatible widget types and invalid grouped bindings."""
    valid = {
        "type": "ag-grid-table",
        "datasetId": 5,
        "metrics": ["population"],
        "dimensions": [],
    }
    assert WidgetDraft.model_validate(valid).dimensions == []
    with pytest.raises(ValidationError):
        WidgetDraft.model_validate({**valid, **overrides})


def test_dashboard_summary_is_bounded() -> None:
    """Only a short, nonempty summary is forwarded with a dashboard draft."""
    draft = {
        "title": "Demo dashboard",
        "widgets": [{"type": "metric-tile", "datasetId": 5, "metric": "population"}],
    }
    summary = "a" * 512
    assert (
        DashboardDraft.model_validate({**draft, "summary": summary}).summary == summary
    )
    for invalid in (" ", summary + "a"):
        with pytest.raises(ValidationError):
            DashboardDraft.model_validate({**draft, "summary": invalid})


@pytest.mark.parametrize("distinct_dates", [31, 634])
@pytest.mark.parametrize("use_shortcut", [False, True])
def test_uploaded_dashboard_uses_saved_amount_and_scoped_status(
    distinct_dates: int, use_shortcut: bool
) -> None:
    """The selected file yields verified metrics and avoids partial daily charts."""
    dataset_id = 47
    headers = _authorization("superset")
    calls: list[dict[str, Any]] = []
    metric = "sum_order_total"
    approval = "opaque-upload-approval-token"

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == headers["Authorization"]
        call = json.loads(request.content)
        name = call["name"]
        args = call["arguments"]
        calls.append(call)
        if name == "propose_dashboard":
            assert all(widget["datasetId"] == dataset_id for widget in args["widgets"])
            assert all("filter" not in widget for widget in args["widgets"])
            return httpx.Response(200, json={**args, "approvalToken": approval})
        assert args["id"] == dataset_id
        if name == "get_dataset":
            result = {
                "id": dataset_id,
                "table_name": "Demo orders",
                "metrics": ["count", "avg_order_total", metric],
                "metric_details": [
                    {"metric_name": metric, "verbose_name": "Total order value"}
                ],
                "groupable_columns": [
                    "order_id",
                    "customer_id",
                    "contact_status",
                    "order_date",
                    "status",
                ],
                "temporal_columns": ["order_date"],
            }
        elif name == "profile_dataset":
            assert args["columns"] == ["order_date", "status"]
            result = {
                "dataset_id": dataset_id,
                "row_count": 2_000,
                "columns": [
                    {"column_name": "order_date", "distinct_count": distinct_dates},
                    {"column_name": "status", "distinct_count": 3},
                ],
            }
        else:
            assert name == "aggregate_dataset"
            assert args["metric"] == metric
            dimension = args.get("dimension")
            assert dimension in (None, "status")
            result = {
                "dataset_id": dataset_id,
                "metric": metric,
                "dimension": dimension,
                "rows": (
                    [
                        {"group": "active", "value": 3_500_000},
                        {"group": "pending", "value": 2_939_445.27},
                    ]
                    if dimension
                    else [{"group": None, "value": 6_439_445.27}]
                ),
            }
        return httpx.Response(200, json=result)

    async def generate(
        messages: Sequence[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        assert "propose_uploaded_dataset_dashboard" in {
            tool.name for tool in info.function_tools
        }
        assert "User-selected uploaded dataset ID: 47." in str(messages)
        for message in messages:
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    assert approval not in str(part.content)
                    assert part.content["headline"]["rows"][0]["value"] == 6_439_445.27
                    yield "I verified the full-file order value."
                    return
        yield {
            0: DeltaToolCall(
                name="propose_uploaded_dataset_dashboard",
                tool_call_id="csv-dashboard",
                json_args='{"title":"Orders overview"}',
            )
        }

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        model=None if use_shortcut else FunctionModel(stream_function=generate),
        tool_transport=httpx.MockTransport(gateway),
    )
    context = [{"description": "uploaded_dataset_id", "value": "47"}]
    if use_shortcut:
        context.extend(
            [
                {"description": "uploaded_dataset_action", "value": "draft"},
                {"description": "locale", "value": "ar"},
                {"description": "content_locale", "value": "en"},
                {"description": "dashboard_type", "value": "v1"},
            ]
        )
    with TestClient(app) as client:
        events = _events(
            client.post(
                "/ag-ui",
                headers=headers,
                json={
                    **REQUEST,
                    "context": context,
                },
            )
        )
    proposal = next(event for event in events if event["type"] == "CUSTOM")
    assert proposal["name"] == "nxtbi.dashboard-proposal"
    assert proposal["value"]["approvalToken"] == approval
    nodes = _evidence_nodes(events)
    assert nodes["title"]["text"] == (
        "الأدلة المستخدمة" if use_shortcut else "Evidence used"
    )
    assert nodes["source"]["text"] == "Demo orders · #47"
    assert nodes["headline"]["value"] == "6,439,445.27"
    assert nodes["headline"]["label"] == "Total order value"
    assert nodes["headline"]["detail"] == (
        "كل الصفوف المتاحة (2,000)" if use_shortcut else "All accessible rows (2,000)"
    )
    assert nodes["comparison"]["rows"] == [
        {"group": "active", "value": "3,500,000"},
        {"group": "pending", "value": "2,939,445.27"},
    ]
    assert approval not in str(nodes)
    widgets = proposal["value"]["widgets"]
    assert [widget["metric"] for widget in widgets[:2]] == [metric, "count"]
    assert widgets[0]["titleTranslations"] == {
        "en": "Total order value",
        "ar": "إجمالي قيمة الطلبات",
    }
    assert widgets[1]["titleTranslations"] == {"en": "Records", "ar": "السجلات"}
    assert proposal["value"]["contentLocale"] == "en"
    assert proposal["value"].get("dashboardType", "v2") == (
        "v1" if use_shortcut else "v2"
    )
    assert widgets[-1]["dimension"] == "status"
    assert widgets[-1]["chartStyle"] == "bar"
    assert any(widget.get("chartStyle") == "line" for widget in widgets) == (
        distinct_dates == 31
    )
    assert [call["name"] for call in calls] == [
        "get_dataset",
        "profile_dataset",
        "aggregate_dataset",
        "aggregate_dataset",
        "propose_dashboard",
    ]


def test_registered_dataset_drafts_without_a_model() -> None:
    """Use named saved metrics from the signed actor's registered dataset."""
    headers = _authorization("superset")
    calls: list[str] = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == headers["Authorization"]
        call = json.loads(request.content)
        name, args = call["name"], call["arguments"]
        calls.append(name)
        if name == "get_dataset":
            assert args == {"id": 23}
            return httpx.Response(
                200,
                json={
                    "id": 23,
                    "table_name": "Budget execution",
                    "metrics": ["count", "spent"],
                    "metric_details": [
                        {"metric_name": "spent", "verbose_name": "Expenditure"}
                    ],
                    "groupable_columns": ["status"],
                },
            )
        if name == "profile_dataset":
            assert args == {"id": 23, "columns": ["status"]}
            return httpx.Response(
                200,
                json={
                    "dataset_id": 23,
                    "row_count": 17,
                    "columns": [{"column_name": "status", "distinct_count": 2}],
                },
            )
        if name == "aggregate_dataset":
            assert args["id"] == 23
            assert args["metric"] == "spent"
            dimension = args.get("dimension")
            return httpx.Response(
                200,
                json={
                    "dataset_id": 23,
                    "metric": "spent",
                    "dimension": dimension,
                    "rows": (
                        [
                            {"group": "Open", "value": 10},
                            {"group": "Closed", "value": 17},
                        ]
                        if dimension
                        else [{"group": None, "value": 27}]
                    ),
                },
            )
        assert name == "propose_dashboard"
        return httpx.Response(200, json={**args, "approvalToken": "existing-approval"})

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        events = _events(
            client.post(
                "/ag-ui",
                headers=headers,
                json={
                    **REQUEST,
                    "context": [
                        {"description": "dashboard_type", "value": "v1"},
                        {"description": "content_locale", "value": "ar"},
                        {"description": "active_dataset_id", "value": "99"},
                    ],
                    "forwardedProps": {"datasetDraft": {"datasetId": 23}},
                },
            )
        )

    proposal = next(event for event in events if event["type"] == "CUSTOM")
    assert proposal["name"] == "nxtbi.dashboard-proposal"
    assert proposal["value"]["approvalToken"] == "existing-approval"
    assert proposal["value"]["dashboardType"] == "v1"
    assert proposal["value"]["contentLocale"] == "ar"
    assert proposal["value"]["titleTranslations"]["en"] == "Budget execution overview"
    assert [widget["metric"] for widget in proposal["value"]["widgets"]] == [
        "spent",
        "spent",
    ]
    assert _evidence_nodes(events)["headline"]["value"] == "27"
    assert calls[0:2] == ["get_dataset", "profile_dataset"]
    assert calls[2:4] == ["aggregate_dataset", "aggregate_dataset"]
    assert calls[4:] == ["propose_dashboard"]


@pytest.mark.parametrize(
    ("metrics", "supported_metric", "expected_attempts", "expected_selected"),
    [
        (
            ["count", "initial", "spend"],
            "spend",
            ["initial", "spend"],
            "spend",
        ),
        (
            ["count", "initial", "spend", "other"],
            "count",
            ["initial", "spend", "count"],
            "count",
        ),
        (
            ["initial", "spend", "other", "later"],
            "later",
            ["initial", "spend", "other"],
            None,
        ),
    ],
)
def test_registered_dataset_draft_limits_saved_metric_fallback(
    metrics: list[str],
    supported_metric: str,
    expected_attempts: list[str],
    expected_selected: str | None,
) -> None:
    """Profile once and use only the bounded, authorized saved measures."""
    headers = _authorization("superset")
    profiles = []
    attempts = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == headers["Authorization"]
        call = json.loads(request.content)
        name, args = call["name"], call["arguments"]
        if name == "get_dataset":
            assert args == {"id": 23}
            return httpx.Response(
                200,
                json={
                    "id": 23,
                    "metrics": metrics,
                    "metric_details": [
                        {"metric_name": supported_metric, "verbose_name": "Observed"}
                    ],
                },
            )
        if name == "profile_dataset":
            profiles.append(args)
            return httpx.Response(
                200, json={"dataset_id": 23, "row_count": 17, "columns": []}
            )
        if name == "aggregate_dataset":
            metric = args["metric"]
            assert args == {"id": 23, "metric": metric}
            attempts.append(metric)
            return httpx.Response(
                200,
                json={
                    "dataset_id": 23,
                    "metric": metric,
                    "rows": [
                        {
                            "group": None,
                            "value": 0 if metric == supported_metric else None,
                        }
                    ],
                },
            )
        assert name == "propose_dashboard"
        assert expected_selected is not None
        return httpx.Response(200, json={**args, "approvalToken": "existing-approval"})

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        response = client.post(
            "/ag-ui",
            headers=headers,
            json={**REQUEST, "forwardedProps": {"datasetDraft": {"datasetId": 23}}},
        )

    assert profiles == [{"id": 23, "columns": []}]
    assert attempts == expected_attempts
    if expected_selected is None:
        assert response.status_code == 200, response.text
        assert '"type":"RUN_ERROR"' in response.text
        assert "approvalToken" not in response.text
    else:
        events = _events(response)
        proposal = next(event for event in events if event["type"] == "CUSTOM")
        assert [widget["metric"] for widget in proposal["value"]["widgets"]] == [
            expected_selected
        ]
        assert _evidence_nodes(events)["headline"]["label"] == "Observed"
        assert _evidence_nodes(events)["headline"]["value"] == "0"


@pytest.mark.parametrize(
    ("host", "action", "extra", "context"),
    [
        ("standalone", {"datasetId": 23}, {}, []),
        ("superset", {"datasetId": "23"}, {}, []),
        ("superset", {"datasetId": True}, {}, []),
        ("superset", {"datasetId": 0}, {}, []),
        ("superset", {"datasetId": 2**31}, {}, []),
        ("superset", {"datasetId": 23, "metric": "extra"}, {}, []),
        ("superset", {"datasetId": 23}, {"a2uiAction": None}, []),
        ("superset", {"datasetId": 23}, {"dashboardLocalization": None}, []),
        (
            "superset",
            {"datasetId": 23},
            {},
            [
                {"description": "uploaded_dataset_id", "value": "23"},
                {"description": "uploaded_dataset_action", "value": "draft"},
            ],
        ),
    ],
)
def test_registered_dataset_draft_rejects_invalid_or_mixed_intent(
    host: Literal["superset", "standalone"],
    action: dict[str, object],
    extra: dict[str, object],
    context: list[dict[str, str]],
) -> None:
    forwarded_props: dict[str, object] = {"datasetDraft": action, **extra}
    with TestClient(create_app(Settings(shared_secret=SIGNING_KEY))) as client:
        response = client.post(
            "/ag-ui",
            headers=_authorization(host),
            json={
                **REQUEST,
                "context": context,
                "forwardedProps": forwarded_props,
            },
        )
    assert response.status_code == 422


@pytest.mark.parametrize("status", [200, 403])
def test_registered_dataset_draft_does_not_stage_unavailable_data(status: int) -> None:
    """Check access, and stop before querying data when there is no saved measure."""
    attempts = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        attempts.append(json.loads(request.content))
        return httpx.Response(status, json={"id": 23, "metrics": []})

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        tool_transport=httpx.MockTransport(gateway),
    )
    body = {**REQUEST, "forwardedProps": {"datasetDraft": {"datasetId": 23}}}
    with TestClient(app) as client:
        assert client.post("/ag-ui", json=body).status_code == 401
        response = client.post("/ag-ui", headers=_authorization("superset"), json=body)

    assert response.status_code == 200
    assert "draft_unavailable" in response.text
    assert "approvalToken" not in response.text
    assert attempts == [{"name": "get_dataset", "arguments": {"id": 23}}]
    if status == 200:
        assert "This dataset has no saved metrics." in response.text


def test_upload_shortcut_requires_a_signed_superset_dataset() -> None:
    """Reject a missing selection and never stage a denied dataset."""
    shortcut = {"description": "uploaded_dataset_action", "value": "draft"}
    selected = {"description": "uploaded_dataset_id", "value": "47"}
    attempts = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        attempts.append(json.loads(request.content))
        return httpx.Response(403)

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        response = client.post(
            "/ag-ui",
            headers=_authorization("superset"),
            json={**REQUEST, "context": [shortcut]},
        )
        assert response.status_code == 422
        response = client.post(
            "/ag-ui",
            headers=_authorization(),
            json={**REQUEST, "context": [shortcut, selected]},
        )
        assert response.status_code == 503
        response = client.post(
            "/ag-ui",
            headers=_authorization("superset"),
            json={**REQUEST, "context": [shortcut, selected]},
        )
    assert response.status_code == 200
    assert "draft_unavailable" in response.text
    assert "RUN_FINISHED" not in response.text
    assert "approvalToken" not in response.text
    assert attempts == [{"name": "get_dataset", "arguments": {"id": 47}}]


@pytest.mark.parametrize(
    ("grouped", "validated"), [(False, True), (True, True), (True, False)]
)
def test_superset_proposal_requires_separate_approval(
    grouped: bool, validated: bool
) -> None:
    """The only Superset write-like tool yields a preview and opaque approval token."""
    headers = _authorization("superset")
    widgets = [
        {
            "type": "metric-tile",
            "datasetId": 5,
            "metric": "population",
            "filter": {"column": "year", "value": 2024},
        },
        {
            "type": "echarts",
            "datasetId": 5,
            "metric": "population",
            "dimension": "year",
            "chartStyle": "line",
        },
    ]
    request_arguments: dict[str, object] = {
        "title": "Demo dashboard",
        "widgets": widgets,
    }
    tool_arguments = request_arguments
    if grouped:
        table = {
            "type": "ag-grid-table",
            "datasetId": 5,
            "metrics": ["population", "households"],
            "dimensions": ["district", "year"],
            "title": "Population and households",
        }
        captions = {"en": "Demo dashboard", "ar": "لوحة تجريبية"}
        table_captions = {"en": "Population and households", "ar": "السكان والأسر"}
        summary = "The data compares population and households by district and year."
        tool_arguments = {
            "title": "Demo dashboard",
            "title_translations": json.dumps(captions),
            "summary": summary,
            "widgets": [{**table, "titleTranslations": json.dumps(table_captions)}],
        }
        request_arguments = {
            "title": "Demo dashboard",
            "titleTranslations": captions,
            "summary": summary,
            "contentLocale": "en",
            "dashboardType": "v2",
            "widgets": [{**table, "titleTranslations": table_captions}],
        }
    approval = "opaque-gateway-approval-token"
    calls: list[object] = []

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOOL_URL
        assert request.method == "POST"
        assert request.headers["Authorization"] == headers["Authorization"]
        calls.append(json.loads(request.content))
        if not validated:
            return httpx.Response(200, json=request_arguments)
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
            "profile_dataset",
            "aggregate_dataset",
            "get_dashboard",
            "propose_dashboard",
        } <= names
        assert "approve_dashboard" not in names
        assert "run_arbitrary_sql" not in names
        for msg in messages:
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    assert approval not in str(part.content)
                    if grouped:
                        raise RuntimeError("The provider failed during follow-up text")
                    yield "Approval is required."
                    return
        yield {
            0: DeltaToolCall(
                name="propose_dashboard",
                tool_call_id="proposal-tool",
                json_args=json.dumps(tool_arguments),
            )
        }

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        model=FunctionModel(stream_function=generate),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        response = client.post("/ag-ui", headers=headers, json=REQUEST)
    assert calls == [{"name": "propose_dashboard", "arguments": request_arguments}]
    if not validated:
        assert response.status_code == 200
        assert "RUN_ERROR" in response.text
        assert "RUN_FINISHED" not in response.text
        assert "nxtbi.dashboard-proposal" not in response.text
        return
    events = _events(response)
    proposal = next(event for event in events if event["type"] == "CUSTOM")
    assert proposal["name"] == "nxtbi.dashboard-proposal"
    assert proposal["value"] == {**request_arguments, "approvalToken": approval}
    assert all(approval not in str(event) for event in events if event is not proposal)
    result = next(event for event in events if event["type"] == "TOOL_CALL_RESULT")
    assert result["toolCallId"] == "proposal-tool"
    assert json.loads(result["content"])["status"] == "pending_approval"
    assert events.index(proposal) < events.index(result) < len(events) - 1
    assert events[-1]["outcome"]["type"] == "success"
    assert (
        any(event.get("delta") == "Approval is required." for event in events)
        != grouped
    )


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


@pytest.mark.parametrize("missing_groups", [False, True])
def test_snapshot_proposal_verifies_latest_temporal_scope(missing_groups: bool) -> None:
    """Use observed dates for all snapshot widgets and suppress unsupported previews."""
    requested = {
        "dataset_id": 23,
        "title": "Population",
        "temporal_column": "year_date",
        "headline_metric": "persons",
        "kpis": ["households"],
        "breakdowns": ["region_en", "gender"],
    }
    calls = []
    expected_filter = {"column": "year_date", "value": "2026-01-01"}

    async def gateway(request: httpx.Request) -> httpx.Response:
        call = json.loads(request.content)
        name = call["name"]
        args = call["arguments"]
        calls.append(name)
        if name == "get_dataset":
            result = {
                "id": 23,
                "table_name": "Population by region",
                "metrics": ["households", "persons"],
                "temporal_columns": ["year_date"],
                "groupable_columns": ["year_date", "region_en", "gender"],
                "filterable_columns": ["year_date"],
                "metric_details": [
                    {"metric_name": "persons", "verbose_name": "Population"}
                ],
            }
        elif name == "profile_dataset":
            result = {
                "dataset_id": 23,
                "row_count": 12,
                "columns": [{"column_name": "year_date", "latest": "2026-01-01"}],
            }
        elif name == "aggregate_dataset":
            assert args["filter"] == expected_filter
            group = args.get("dimension")
            rows = (
                [
                    {"group": "North", "value": 8},
                    {"group": "South", "value": 1},
                    {"group": "East", "value": 0.4},
                    {"group": "West", "value": 0.3},
                    {"group": "Coastal", "value": 0.2},
                    {"group": "Central", "value": 0.1},
                ]
                if group
                else [{"group": None, "value": 10}]
            )
            result = {
                "dataset_id": 23,
                "metric": "persons",
                "dimension": group,
                "rows": [] if missing_groups and group else rows,
            }
        else:
            assert name == "propose_dashboard"
            tile, line, bar, table = args["widgets"]
            assert table["type"] == "ag-grid-table"
            assert tile["filter"] == bar["filter"] == expected_filter
            assert "2026-01-01" in tile["title"]
            assert line["title"] == "Population over time"
            assert bar["title"] == "Population by region · 2026-01-01"
            assert line["chartStyle"] == "line"
            assert "filter" not in line
            result = {**args, "approvalToken": "opaque-test-approval"}
        return httpx.Response(200, json=result)

    async def generate(
        messages: Sequence[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        for msg in messages:
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    if not missing_groups:
                        widgets = part.content["proposal"]["widgets"]
                        assert [w["type"] for w in widgets] == [
                            "metric tile",
                            "line",
                            "bar",
                            "table",
                        ]
                        assert widgets[-1]["dimension"] == "gender"
                        assert "2026-01-01" in widgets[-1]["title"]
                    yield "Checked the latest observation."
                    return
        yield {
            0: DeltaToolCall(
                name="propose_snapshot_dashboard",
                tool_call_id="snapshot",
                json_args=json.dumps(requested),
            )
        }

    app = create_app(
        Settings(shared_secret=SIGNING_KEY, tool_url=TOOL_URL),
        model=FunctionModel(stream_function=generate),
        tool_transport=httpx.MockTransport(gateway),
    )
    with TestClient(app) as client:
        events = _events(
            client.post("/ag-ui", headers=_authorization("superset"), json=REQUEST)
        )
    assert calls.count("aggregate_dataset") == 2
    assert ("propose_dashboard" in calls) != missing_groups
    assert (
        any(e.get("name") == "nxtbi.dashboard-proposal" for e in events)
        != missing_groups
    )
    _assert_snapshot_evidence(events, expected=not missing_groups)


def _assert_snapshot_evidence(events: list[dict[str, Any]], *, expected: bool) -> None:
    """Show the measured headline and scope with the comparison rows capped."""
    nodes = _evidence_nodes(events)
    assert bool(nodes) == expected
    if not nodes:
        return
    assert nodes["source"]["text"] == "Population by region · #23"
    assert nodes["headline"]["label"] == "Population"
    assert nodes["headline"]["value"] == "10"
    assert nodes["headline"]["detail"] == "Snapshot · year_date = 2026-01-01"
    assert nodes["comparison"]["caption"] == "region_en · 5 of 6 groups shown"
    assert [row["group"] for row in nodes["comparison"]["rows"]] == [
        "North",
        "South",
        "East",
        "West",
        "Coastal",
    ]

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
"""Tests for the widget type discovery MCP tools."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastmcp import Client
from pydantic import ValidationError

from superset.mcp_service.app import mcp
from superset.mcp_service.privacy import (
    DATA_MODEL_METADATA_ERROR_TYPE,
    tool_requires_data_model_metadata_access,
)
from superset.mcp_service.widgets.schemas import (
    GetWidgetControlSchemaRequest,
    WidgetControlSchema,
    WidgetToolError,
    WidgetTypeList,
)
from superset.mcp_service.widgets.tool.get_widget_control_schema import (
    _get_widget_control_schema_impl,
)
from superset.mcp_service.widgets.tool.list_widget_types import (
    _list_widget_types_impl,
)
from superset.mcp_service.widgets.utils import WIDGET_TOOL_NAMES
from superset.utils import json

FLAG = "superset.mcp_service.widgets.utils.is_dashboard_v2_enabled"
CAN_VIEW_METADATA = (
    "superset.mcp_service.widgets.tool.get_widget_control_schema"
    ".user_can_view_data_model_metadata"
)


@pytest.fixture(autouse=True)
def mock_auth() -> Iterator[MagicMock]:
    """Mock authentication for client-based tool tests."""
    with patch("superset.mcp_service.auth.get_user_from_request") as mock_get_user:
        mock_user = Mock()
        mock_user.id = 1
        mock_user.username = "admin"
        mock_get_user.return_value = mock_user
        yield mock_get_user


@pytest.fixture(autouse=True)
def widgets_enabled() -> Iterator[MagicMock]:
    """DASHBOARD_V2 on, as every tool refuses to run without it."""
    with patch(FLAG, return_value=True) as flag:
        yield flag


@pytest.fixture(autouse=True)
def can_view_metadata() -> Iterator[MagicMock]:
    """The caller may see dataset details unless a test says otherwise."""
    with patch(CAN_VIEW_METADATA, return_value=True) as allowed:
        yield allowed


def _schema(**kwargs: object) -> WidgetControlSchema:
    result = _get_widget_control_schema_impl(GetWidgetControlSchemaRequest(**kwargs))
    assert isinstance(result, WidgetControlSchema)
    return result


def _schema_error(**kwargs: object) -> WidgetToolError:
    result = _get_widget_control_schema_impl(GetWidgetControlSchemaRequest(**kwargs))
    assert isinstance(result, WidgetToolError)
    return result


def test_list_widget_types_impl() -> None:
    result = _list_widget_types_impl()
    assert isinstance(result, WidgetTypeList)
    ids = [widget_type.id for widget_type in result.widget_types]
    assert {"metric-tile", "ag-grid-table", "echarts"} <= set(ids)
    assert ids == sorted(ids)
    assert result.count == len(ids)


def test_list_widget_types_requires_feature_flag(widgets_enabled: MagicMock) -> None:
    widgets_enabled.return_value = False
    result = _list_widget_types_impl()
    assert isinstance(result, WidgetToolError)
    assert result.error_type == "FeatureDisabled"


def test_get_widget_control_schema_is_minimal() -> None:
    result = _schema(widget_type="echarts")
    assert result.subtrees is None
    schema = result.control_schema
    assert schema is not None
    assert schema["x-disclosure"] == "minimal"
    assert schema["properties"]["customize"]["x-collapsed"] is True
    # Mandatory leaves are surfaced inline.
    assert (
        schema["properties"]["dataBinding"]["properties"]["datasetId"]["type"]
        == "integer"
    )


def test_get_widget_control_schema_unknown_type_error() -> None:
    error = _schema_error(widget_type="does-not-exist")
    assert error.error_type == "NotFound"
    assert "echarts" in error.errors["valid_widget_types"]


def test_get_widget_control_schema_drills_into_enriched_series() -> None:
    result = _schema(
        widget_type="echarts",
        paths=["customize/series"],
        control_values={
            "chartType": "bar",
            "dataBinding": {
                "datasetId": 1,
                "metrics": ["count", "sum__num"],
                "dimensions": ["g"],
            },
        },
    )
    assert result.control_schema is None
    assert result.subtrees is not None
    assert set(result.subtrees["customize/series"]["properties"]) == {
        "count",
        "sum__num",
    }


def test_get_widget_control_schema_expands_multiple_paths_at_once() -> None:
    result = _schema(widget_type="echarts", paths=["dataBinding", "customize"])
    assert result.subtrees is not None
    assert set(result.subtrees) == {"dataBinding", "customize"}
    assert "datasetId" in result.subtrees["dataBinding"]["properties"]
    assert "series" in result.subtrees["customize"]["properties"]


def test_get_widget_control_schema_bad_path_error() -> None:
    error = _schema_error(widget_type="echarts", paths=["nope/nope"])
    assert error.error_type == "ValidationError"


def test_get_widget_control_schema_falls_back_when_enrichment_fails() -> None:
    widget = Mock()
    widget.get_control_schema.side_effect = [
        RuntimeError("boom"),
        {"type": "object", "properties": {}},
    ]
    with patch(
        "superset.mcp_service.widgets.tool.get_widget_control_schema.resolve_widget",
        return_value=widget,
    ):
        result = _schema(widget_type="echarts", control_values={"a": 1})

    assert result.warning is not None
    assert "boom" not in result.warning
    assert widget.get_control_schema.call_args_list[-1].args == (None, None)


def test_get_widget_control_schema_requires_feature_flag(
    widgets_enabled: MagicMock,
) -> None:
    widgets_enabled.return_value = False
    assert _schema_error(widget_type="echarts").error_type == "FeatureDisabled"


def test_get_widget_control_schema_withheld_without_metadata_access(
    can_view_metadata: MagicMock,
) -> None:
    can_view_metadata.return_value = False
    error = _schema_error(widget_type="echarts")
    assert error.error_type == DATA_MODEL_METADATA_ERROR_TYPE


def test_control_schema_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GetWidgetControlSchemaRequest(widget_type="echarts", sql="SELECT 1")


@pytest.mark.asyncio
async def test_widget_tool_surface() -> None:
    """Exactly the read-only widget tools are registered, none taking SQL."""
    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    widget_tools = {name for name in tools if "widget" in name}
    assert widget_tools == set(WIDGET_TOOL_NAMES)
    for name in WIDGET_TOOL_NAMES:
        tool = tools[name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert "sql" not in json.dumps(tool.inputSchema).lower()


@pytest.mark.asyncio
async def test_widget_tools_carry_chart_read_permission() -> None:
    for name in WIDGET_TOOL_NAMES:
        tool = await mcp.get_tool(name)
        assert tool is not None
        assert getattr(tool.fn, "_class_permission_name", None) == "Chart"
        assert getattr(tool.fn, "_method_permission_name", None) == "read"

    schema_tool = await mcp.get_tool("get_widget_control_schema")
    assert schema_tool is not None
    assert tool_requires_data_model_metadata_access(schema_tool.fn)


@pytest.mark.asyncio
async def test_discovery_tools_are_callable_through_mcp() -> None:
    async with Client(mcp) as client:
        listed = await client.call_tool("list_widget_types", {})
        types = json.loads(listed.content[0].text)
        assert "metric-tile" in {entry["id"] for entry in types["widget_types"]}

        result = await client.call_tool(
            "get_widget_control_schema", {"request": {"widget_type": "metric-tile"}}
        )
        data = json.loads(result.content[0].text)
        assert data["control_schema"]["x-disclosure"] == "minimal"
        assert "dataBinding" in data["control_schema"]["properties"]

        drilled = await client.call_tool(
            "get_widget_control_schema",
            {"request": {"widget_type": "echarts", "paths": ["dataBinding"]}},
        )
        drilled_data = json.loads(drilled.content[0].text)
        assert "datasetId" in drilled_data["subtrees"]["dataBinding"]["properties"]


@pytest.mark.asyncio
async def test_discovery_tools_refuse_when_flag_is_off(
    widgets_enabled: MagicMock,
) -> None:
    widgets_enabled.return_value = False
    async with Client(mcp) as client:
        listed = await client.call_tool("list_widget_types", {})
        described = await client.call_tool(
            "get_widget_control_schema", {"request": {"widget_type": "metric-tile"}}
        )

    assert json.loads(listed.content[0].text)["error_type"] == "FeatureDisabled"
    assert json.loads(described.content[0].text)["error_type"] == "FeatureDisabled"

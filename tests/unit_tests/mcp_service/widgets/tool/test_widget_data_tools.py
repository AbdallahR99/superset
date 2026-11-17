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
"""Tests for the saved-widget and widget-data MCP tools."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastmcp import Client
from pydantic import ValidationError

from superset.commands.widget.exceptions import (
    SavedWidgetForbiddenError,
    SavedWidgetNotFoundError,
    WidgetInvalidError,
)
from superset.errors import ErrorLevel, SupersetError, SupersetErrorType
from superset.exceptions import SupersetSecurityException
from superset.mcp_service.app import mcp
from superset.mcp_service.widgets.schemas import (
    GetSavedWidgetRequest,
    GetWidgetDataRequest,
    ListSavedWidgetsRequest,
    SavedWidgetInfo,
    SavedWidgetList,
    WidgetDataResponse,
    WidgetToolError,
)
from superset.mcp_service.widgets.tool.get_saved_widget import (
    _get_saved_widget_impl,
)
from superset.mcp_service.widgets.tool.get_widget_data import _get_widget_data_impl
from superset.mcp_service.widgets.tool.list_saved_widgets import (
    _list_saved_widgets_impl,
)
from superset.utils import json

FLAG = "superset.mcp_service.widgets.utils.is_dashboard_v2_enabled"
TOOLS = "superset.mcp_service.widgets.tool"
DATA_COMMAND = "superset.commands.widget.data.WidgetDataCommand"
SAVED_COMMAND = "superset.commands.widget.saved.GetSavedWidgetCommand"
LIST_COMMAND = "superset.commands.widget.saved.ListSavedWidgetsCommand"
WIDGET_UUID = "cedf0501-fa36-4e19-9f84-e9da6d657dcc"

BAR_PROPS: dict[str, Any] = {
    "chartType": "bar",
    "dataBinding": {
        "datasetId": 17,
        "metrics": ["sum__num"],
        "dimensions": ["state"],
    },
}
INLINE_BAR = {"type": "echarts", "props": BAR_PROPS}


def saved_widget(uuid: str = WIDGET_UUID, title: str = "Births by state") -> Mock:
    """A stand-in for a ``SavedWidget`` row."""
    return Mock(
        uuid=uuid,
        widget_type="echarts",
        title=title,
        props_dict=BAR_PROPS,
        dataset_id=17,
        changed_on=datetime(2026, 9, 15),
    )


@pytest.fixture(autouse=True)
def mock_auth() -> Iterator[MagicMock]:
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
    allowed = MagicMock(return_value=True)
    with (
        patch(f"{TOOLS}.get_saved_widget.user_can_view_data_model_metadata", allowed),
        patch(f"{TOOLS}.list_saved_widgets.user_can_view_data_model_metadata", allowed),
    ):
        yield allowed


def test_data_request_takes_only_a_saved_widget_id() -> None:
    with pytest.raises(ValidationError):
        GetWidgetDataRequest()
    with pytest.raises(ValidationError):
        GetWidgetDataRequest(widget=INLINE_BAR)
    with pytest.raises(ValidationError):
        GetWidgetDataRequest(id=WIDGET_UUID, widget=INLINE_BAR)
    with pytest.raises(ValidationError):
        GetWidgetDataRequest(id=WIDGET_UUID, sql="SELECT 1")

    assert GetWidgetDataRequest(id=WIDGET_UUID).filters == []


def test_filters_reject_unknown_operators_and_fields() -> None:
    with pytest.raises(ValidationError):
        GetWidgetDataRequest(
            id=WIDGET_UUID,
            filters=[{"column": "state", "operator": "LIKE", "value": "C%"}],
        )
    with pytest.raises(ValidationError):
        GetWidgetDataRequest(
            id=WIDGET_UUID,
            filters=[
                {
                    "column": "state",
                    "operator": "EQUALS",
                    "value": "CA",
                    "sqlExpression": "1 = 1",
                }
            ],
        )


def test_get_widget_data_dispatches_saved_selector_and_filters() -> None:
    request = GetWidgetDataRequest(
        id=WIDGET_UUID,
        filters=[{"column": "state", "operator": "IN", "value": ["CA"]}],
    )
    with patch(DATA_COMMAND) as command:
        command.return_value.run.return_value = {
            "columns": ["state", "sum__num"],
            "rows": [{"state": "CA", "sum__num": Decimal("8998550")}],
        }
        result = _get_widget_data_impl(request)

    command.assert_called_once_with(
        {"id": WIDGET_UUID},
        [{"column": "state", "operator": "IN", "value": ["CA"]}],
    )
    assert isinstance(result, WidgetDataResponse)
    assert result.model_dump() == {
        "columns": ["state", "sum__num"],
        "rows": [{"state": "CA", "sum__num": 8998550}],
        "row_count": 1,
    }


def test_get_widget_data_serializes_datetimes() -> None:
    with patch(DATA_COMMAND) as command:
        command.return_value.run.return_value = {
            "columns": ["ds"],
            "rows": [{"ds": datetime(2020, 1, 1)}],
        }
        result = _get_widget_data_impl(GetWidgetDataRequest(id=WIDGET_UUID))

    assert isinstance(result, WidgetDataResponse)
    assert result.rows == [{"ds": "2020-01-01T00:00:00"}]


@pytest.mark.parametrize(
    ("exception", "error_type"),
    [
        (SavedWidgetNotFoundError(WIDGET_UUID), "NotFound"),
        (SavedWidgetForbiddenError(), "Forbidden"),
        (WidgetInvalidError("Unknown column 'nope'"), "ValidationError"),
        (RuntimeError("boom"), "UnexpectedError"),
    ],
)
def test_get_widget_data_maps_command_errors(
    exception: Exception, error_type: str
) -> None:
    with patch(DATA_COMMAND) as command:
        command.return_value.run.side_effect = exception
        result = _get_widget_data_impl(GetWidgetDataRequest(id=WIDGET_UUID))

    assert isinstance(result, WidgetToolError)
    assert result.error_type == error_type
    assert "boom" not in result.error


def test_validation_errors_carry_field_details() -> None:
    details = [{"loc": ["dataBinding", "datasetId"], "message": "required"}]
    with patch(DATA_COMMAND) as command:
        command.return_value.run.side_effect = WidgetInvalidError(
            "Widget props failed validation.", details
        )
        result = _get_widget_data_impl(GetWidgetDataRequest(id=WIDGET_UUID))

    assert isinstance(result, WidgetToolError)
    assert result.error_type == "ValidationError"
    assert result.errors == details


def test_get_widget_data_runs_the_shared_command_and_reports_denied_access() -> None:
    """The real command runs, so a dataset the caller cannot read is Forbidden."""
    denied = SupersetSecurityException(
        SupersetError(
            message="no access to dataset 17",
            error_type=SupersetErrorType.DATASOURCE_SECURITY_ACCESS_ERROR,
            level=ErrorLevel.WARNING,
        )
    )
    widget_cls = Mock()
    widget_cls.fetch_data.side_effect = denied
    context = Mock()
    with patch(
        "superset.commands.widget.data.resolve_widget",
        return_value=(widget_cls, BAR_PROPS, context),
    ) as resolve:
        result = _get_widget_data_impl(GetWidgetDataRequest(id=WIDGET_UUID))

    resolve.assert_called_once_with({"id": WIDGET_UUID})
    widget_cls.fetch_data.assert_called_once_with(BAR_PROPS, [], context)
    assert isinstance(result, WidgetToolError)
    assert result.error_type == "Forbidden"
    assert "dataset 17" not in result.error


def test_get_widget_data_requires_feature_flag(widgets_enabled: MagicMock) -> None:
    widgets_enabled.return_value = False
    with patch(DATA_COMMAND) as command:
        result = _get_widget_data_impl(GetWidgetDataRequest(id=WIDGET_UUID))

    command.assert_not_called()
    assert isinstance(result, WidgetToolError)
    assert result.error_type == "FeatureDisabled"


def test_get_saved_widget_serializes_model() -> None:
    with patch(SAVED_COMMAND) as command:
        command.return_value.run.return_value = saved_widget()
        result = _get_saved_widget_impl(GetSavedWidgetRequest(id=WIDGET_UUID))

    command.assert_called_once_with(WIDGET_UUID)
    assert isinstance(result, SavedWidgetInfo)
    assert result.uuid == WIDGET_UUID
    assert result.dataset_id == 17
    assert result.props == BAR_PROPS


def test_get_saved_widget_withholds_query_definition_without_metadata_access(
    can_view_metadata: MagicMock,
) -> None:
    can_view_metadata.return_value = False
    with patch(SAVED_COMMAND) as command:
        command.return_value.run.return_value = saved_widget()
        result = _get_saved_widget_impl(GetSavedWidgetRequest(id=WIDGET_UUID))

    assert isinstance(result, SavedWidgetInfo)
    assert result.title == "Births by state"
    assert result.props == {}
    assert result.dataset_id is None


def test_get_saved_widget_not_found() -> None:
    with patch(SAVED_COMMAND) as command:
        command.return_value.run.side_effect = SavedWidgetNotFoundError(WIDGET_UUID)
        result = _get_saved_widget_impl(GetSavedWidgetRequest(id=WIDGET_UUID))

    assert isinstance(result, WidgetToolError)
    assert result.error_type == "NotFound"


def test_get_saved_widget_requires_feature_flag(widgets_enabled: MagicMock) -> None:
    widgets_enabled.return_value = False
    with patch(SAVED_COMMAND) as command:
        result = _get_saved_widget_impl(GetSavedWidgetRequest(id=WIDGET_UUID))

    command.assert_not_called()
    assert isinstance(result, WidgetToolError)
    assert result.error_type == "FeatureDisabled"


def test_list_saved_widgets_asks_the_command_for_one_page() -> None:
    """The command pages (0-based) and counts; the tool passes its 1-based
    page through and reports the command's total, not the page length."""
    with patch(LIST_COMMAND) as command:
        command.return_value.run.return_value = [
            saved_widget(uuid="uuid-2"),
            saved_widget(uuid="uuid-3"),
        ]
        command.return_value.count = 5
        result = _list_saved_widgets_impl(ListSavedWidgetsRequest(page=2, page_size=2))

    command.assert_called_once_with(page=1, page_size=2)
    assert isinstance(result, SavedWidgetList)
    assert [widget.uuid for widget in result.widgets] == ["uuid-2", "uuid-3"]
    assert (result.count, result.total_count) == (2, 5)
    assert (result.page, result.page_size) == (2, 2)


def test_list_saved_widgets_defaults_to_the_first_page() -> None:
    with patch(LIST_COMMAND) as command:
        command.return_value.run.return_value = []
        command.return_value.count = 0
        result = _list_saved_widgets_impl(ListSavedWidgetsRequest())

    command.assert_called_once_with(page=0, page_size=25)
    assert isinstance(result, SavedWidgetList)
    assert (result.count, result.total_count, result.page) == (0, 0, 1)


def test_list_saved_widgets_reports_a_page_the_command_refuses() -> None:
    with patch(LIST_COMMAND) as command:
        command.return_value.run.side_effect = WidgetInvalidError("page too large")
        result = _list_saved_widgets_impl(ListSavedWidgetsRequest(page=10**9))

    assert isinstance(result, WidgetToolError)


def test_list_saved_widgets_withholds_props_without_metadata_access(
    can_view_metadata: MagicMock,
) -> None:
    can_view_metadata.return_value = False
    with patch(LIST_COMMAND) as command:
        command.return_value.run.return_value = [saved_widget()]
        command.return_value.count = 1
        result = _list_saved_widgets_impl(ListSavedWidgetsRequest())

    assert isinstance(result, SavedWidgetList)
    assert result.widgets[0].props == {}
    assert result.widgets[0].dataset_id is None


def test_list_saved_widgets_reports_forbidden() -> None:
    with patch(LIST_COMMAND) as command:
        command.return_value.run.side_effect = SavedWidgetForbiddenError()
        result = _list_saved_widgets_impl(ListSavedWidgetsRequest())

    assert isinstance(result, WidgetToolError)
    assert result.error_type == "Forbidden"


def test_list_saved_widgets_requires_feature_flag(widgets_enabled: MagicMock) -> None:
    widgets_enabled.return_value = False
    with patch(LIST_COMMAND) as command:
        result = _list_saved_widgets_impl(ListSavedWidgetsRequest())

    command.assert_not_called()
    assert isinstance(result, WidgetToolError)
    assert result.error_type == "FeatureDisabled"


def test_list_saved_widgets_request_bounds_page_size() -> None:
    with pytest.raises(ValidationError):
        ListSavedWidgetsRequest(page_size=1000)
    with pytest.raises(ValidationError):
        ListSavedWidgetsRequest(page=0)


def test_widget_data_is_refused_under_a_dashboard_filter_scope() -> None:
    """Dashboard filters cannot be mapped onto a widget, so rows are withheld."""
    # pylint: disable=import-outside-toplevel
    from superset.mcp_service.dashboard_scope import (
        MCPDashboardScopeError,
        SCOPE_NEUTRAL_TOOLS,
        SCOPE_REWRITERS,
    )

    with pytest.raises(MCPDashboardScopeError, match="get_widget_data"):
        SCOPE_REWRITERS["get_widget_data"](GetWidgetDataRequest(id=WIDGET_UUID), Mock())
    assert "get_widget_data" not in SCOPE_NEUTRAL_TOOLS


@pytest.mark.asyncio
async def test_tools_are_callable_through_mcp() -> None:
    async with Client(mcp) as client:
        with patch(DATA_COMMAND) as command:
            command.return_value.run.return_value = {
                "columns": ["state", "sum__num"],
                "rows": [{"state": "CA", "sum__num": 1}],
            }
            data = await client.call_tool(
                "get_widget_data",
                {"request": {"id": WIDGET_UUID, "filters": []}},
            )
        assert json.loads(data.content[0].text) == {
            "columns": ["state", "sum__num"],
            "rows": [{"state": "CA", "sum__num": 1}],
            "row_count": 1,
        }

        with patch(SAVED_COMMAND) as command:
            command.return_value.run.side_effect = SavedWidgetForbiddenError()
            saved = await client.call_tool(
                "get_saved_widget", {"request": {"id": WIDGET_UUID}}
            )
        assert json.loads(saved.content[0].text)["error_type"] == "Forbidden"

        with patch(LIST_COMMAND) as command:
            command.return_value.run.return_value = [saved_widget()]
            command.return_value.count = 1
            listed = await client.call_tool("list_saved_widgets", {})
        listing = json.loads(listed.content[0].text)
        assert listing["total_count"] == 1
        assert listing["widgets"][0]["uuid"] == WIDGET_UUID


@pytest.mark.asyncio
async def test_data_tool_rejects_inline_widget_definitions() -> None:
    async with Client(mcp) as client:
        with patch(DATA_COMMAND) as command:
            with pytest.raises(Exception, match="(?i)extra|forbid|not permitted"):
                await client.call_tool(
                    "get_widget_data",
                    {"request": {"id": WIDGET_UUID, "widget": INLINE_BAR}},
                )
            with pytest.raises(Exception):  # noqa: B017, PT011
                await client.call_tool(
                    "get_widget_data", {"request": {"widget": INLINE_BAR}}
                )
        command.assert_not_called()

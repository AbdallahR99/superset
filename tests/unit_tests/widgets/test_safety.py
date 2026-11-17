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
Server-side validation of authored ECharts options and AG Grid column
definitions.

SECURITY.md in-scope bullet: "A user causes a script to execute in another
user's browser through a field the codebase renders to that other user (XSS)".
Principal: a Gamma author ("Write objects: own charts and dashboards"); the
victims are any viewer of the widget, including visitors of an embedding page.
The control models reject executable or HTML-bearing settings, so no write
path stores them.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from superset.commands.widget.exceptions import WidgetInvalidError
from superset.commands.widget.saved import CreateSavedWidgetCommand
from superset.commands.widget.utils import validate_widget_props
from superset.widgets.builtin import AgGridTable, Echarts
from superset.widgets.safety import (
    column_defs_problem,
    echarts_option_problem,
    MAX_COLUMN_DEFS,
    MAX_OPTION_DEPTH,
    MAX_OPTION_NODES,
)

BINDING = {"datasetId": 1, "metrics": ["count"]}

SAFE_OPTION: dict[str, Any] = {
    "title": {"text": "Sales < target", "link": "https://example.com/report"},
    "legend": {"orient": "vertical", "formatter": "{name}"},
    "tooltip": {"trigger": "axis", "formatter": "{b}: {c} kg"},
    "xAxis": {
        "type": "category",
        "data": {"$bind": {"source": "dimension", "alias": "state"}},
        "axisLabel": {"formatter": "{value} kg", "rotate": 30},
        "axisLine": {"onZero": False},
    },
    "yAxis": {"type": "time", "axisLabel": {"formatter": {"year": "{yyyy}"}}},
    "toolbox": {"feature": {"saveAsImage": {"title": "Save"}, "restore": {}}},
    "series": [
        {
            "type": "bar",
            "data": {"$bind": {"source": "metric", "alias": "count"}},
            "label": {
                "show": True,
                "formatter": "{a|{b}}",
                "rich": {"a": {"color": "#333", "fontWeight": "bold"}},
            },
            "itemStyle": {"color": {"$bind": {"source": "theme", "token": "colorX"}}},
        }
    ],
    "color": ["#e74c3c", "#3498db"],
    "animation": True,
}

UNSAFE_OPTIONS: dict[str, dict[str, Any]] = {
    "tooltip_html_formatter": {
        "tooltip": {"formatter": "<img src=x onerror=alert(1)>{b}"}
    },
    "tooltip_formatter_function_source": {
        "tooltip": {"formatter": "function (params) { return params.name; }"}
    },
    "tooltip_formatter_arrow_function": {
        "tooltip": {"formatter": "(p) => document.cookie"}
    },
    "formatter_bound_to_data": {
        "tooltip": {"formatter": {"$bind": {"source": "metric", "alias": "count"}}}
    },
    "value_formatter_function_source": {
        "tooltip": {"valueFormatter": "function (v) { return v; }"}
    },
    "nested_series_tooltip_html": {
        "series": [{"type": "bar", "tooltip": {"formatter": "<b>{b}</b>"}}]
    },
    "tooltip_extra_css": {"tooltip": {"extraCssText": "position:fixed"}},
    "tooltip_class_name": {"tooltip": {"className": "x"}},
    "tooltip_append_to_body": {"tooltip": {"appendToBody": True}},
    "toolbox_data_view": {
        "toolbox": {
            "feature": {
                "dataView": {"show": True, "lang": ["<img src=x onerror=1>", "x", "y"]}
            }
        }
    },
    "toolbox_custom_feature": {
        "toolbox": {"feature": {"myTool": {"show": True, "title": "x", "icon": "y"}}}
    },
    "toolbox_feature_list": {"toolbox": {"feature": [{"dataView": {}}]}},
    "data_view_outside_toolbox": {"series": [{"dataView": {"show": True}}]},
    "rich_text_with_html": {
        "title": {
            "text": "<b onmouseover=alert(1)>Sales</b>",
            "textStyle": {"rich": {}},
        }
    },
    "html_in_series_name": {"series": [{"type": "bar", "name": "</script><script>"}]},
    "html_comment": {"title": {"subtext": "<!-- x -->"}},
    "graphic_with_onclick": {
        "graphic": [{"type": "text", "style": {"text": "x"}, "onclick": "alert(1)"}]
    },
    "graphic_plain": {"graphic": {"type": "image", "style": {"image": "http://x/y"}}},
    "onclick_anywhere": {"series": [{"type": "bar", "onclick": "alert(1)"}]},
    "event_handler_mixed_case": {"title": {"onMouseOver": "alert(1)"}},
    "custom_render_item": {"series": [{"type": "custom", "renderItem": "f"}]},
    "javascript_link": {"title": {"text": "x", "link": "javascript:alert(1)"}},
    "obfuscated_javascript_link": {"title": {"sublink": " java\tscript:alert(1)"}},
    "javascript_url_value": {"series": [{"symbol": "JaVaScRiPt:alert(1)"}]},
    "data_html_url_value": {"title": {"text": "data:text/html,<script>1</script>"}},
    "link_is_not_text": {"title": {"link": {"$bind": {"source": "metric"}}}},
    "unknown_top_level_component": {"timeline": {"data": [1, 2]}},
    "options_nesting": {"options": [{"toolbox": {"feature": {"dataView": {}}}}]},
    "base_option_nesting": {"baseOption": {"graphic": []}},
}


def test_declarative_echarts_option_is_accepted() -> None:
    assert echarts_option_problem(SAFE_OPTION) is None
    assert echarts_option_problem({}) is None
    assert (
        Echarts.validate_control_values(
            {"dataBinding": BINDING, "echartsOptions": SAFE_OPTION}
        )
        == []
    )


@pytest.mark.parametrize("name", sorted(UNSAFE_OPTIONS))
def test_executable_or_html_echarts_settings_are_rejected(name: str) -> None:
    option = UNSAFE_OPTIONS[name]

    assert echarts_option_problem(option) is not None

    errors = Echarts.validate_control_values(
        {"dataBinding": BINDING, "echartsOptions": option}
    )
    assert [error["loc"] for error in errors] == [["echartsOptions"]]
    assert "echartsOptions" in errors[0]["message"]


@pytest.mark.parametrize("option", [[], "x", 1, None])
def test_echarts_option_must_be_an_object(option: Any) -> None:
    assert echarts_option_problem(option) is not None


def test_echarts_option_walk_is_bounded() -> None:
    deep: dict[str, Any] = {}
    cursor = deep
    for _ in range(MAX_OPTION_DEPTH + 5):
        cursor["a"] = {}
        cursor = cursor["a"]
    assert "nested deeper" in str(echarts_option_problem({"series": deep}))

    # Far past the recursion limit: reported, never a RecursionError.
    very_deep: list[Any] = []
    cursor_list = very_deep
    for _ in range(50000):
        cursor_list.append([])
        cursor_list = cursor_list[0]
    assert "nested deeper" in str(echarts_option_problem({"series": very_deep}))

    wide = {"series": [{"data": list(range(MAX_OPTION_NODES + 1))}]}
    assert "more than" in str(echarts_option_problem(wide))


def test_echarts_option_reports_the_offending_path() -> None:
    problem = echarts_option_problem(
        {"series": [{"type": "bar"}, {"tooltip": {"formatter": "<i>{b}</i>"}}]}
    )
    assert problem == "echartsOptions.series[1].tooltip.formatter contains HTML markup"


SAFE_COLUMNS: list[dict[str, Any]] = [
    {
        "field": "state",
        "headerName": "State",
        "headerTooltip": "Where a < b",
        "width": 120,
        "minWidth": 50.5,
        "flex": 1,
        "pinned": "left",
        "sort": "asc",
        "sortIndex": 0,
        "sortable": True,
        "resizable": False,
        "filter": True,
        "hide": False,
        "wrapText": True,
        "type": "numericColumn",
        "cellDataType": "number",
    },
    {"field": "num"},
]

UNSAFE_COLUMNS: dict[str, Any] = {
    "cell_renderer_string": [{"field": "a", "cellRenderer": "<img src=x onerror=1>"}],
    "cell_renderer_expression": [{"field": "a", "cellRenderer": "params.value"}],
    "value_formatter_expression": [{"field": "a", "valueFormatter": "x.constructor"}],
    "value_getter_expression": [{"field": "a", "valueGetter": "data.a + 1"}],
    "tooltip_value_getter": [{"field": "a", "tooltipValueGetter": "data.a"}],
    "tooltip_component": [{"field": "a", "tooltipComponent": "x"}],
    "cell_class_rules": [{"field": "a", "cellClassRules": {"x": "x > 1"}}],
    "cell_style": [{"field": "a", "cellStyle": {"background": "url(//evil)"}}],
    "header_component": [{"field": "a", "headerComponent": "x"}],
    "filter_component_name": [{"field": "a", "filter": "agTextColumnFilter"}],
    "column_group_children": [{"headerName": "g", "children": [{"field": "a"}]}],
    "html_header_name": [{"field": "a", "headerName": "<b>Bold</b>"}],
    "html_header_tooltip": [{"field": "a", "headerTooltip": "<img src=x>"}],
    "number_as_text": [{"field": "a", "width": "120"}],
    "boolean_as_number": [{"field": "a", "width": True}],
    "text_as_boolean": [{"field": "a", "hide": "true"}],
    "unknown_sort": [{"field": "a", "sort": "sideways"}],
    "unknown_pinned": [{"field": "a", "pinned": "top"}],
    "not_an_object": ["field"],
    "not_a_list": {"field": "a"},
    "too_many": [{"field": "a"}] * (MAX_COLUMN_DEFS + 1),
}


def test_declarative_column_defs_are_accepted() -> None:
    assert column_defs_problem(SAFE_COLUMNS) is None
    assert column_defs_problem([]) is None
    assert (
        AgGridTable.validate_control_values(
            {"dataBinding": BINDING, "columnDefs": SAFE_COLUMNS}
        )
        == []
    )


@pytest.mark.parametrize("name", sorted(UNSAFE_COLUMNS))
def test_executable_or_html_column_settings_are_rejected(name: str) -> None:
    column_defs = UNSAFE_COLUMNS[name]

    assert column_defs_problem(column_defs) is not None

    errors = AgGridTable.validate_control_values(
        {"dataBinding": BINDING, "columnDefs": column_defs}
    )
    assert errors
    assert errors[0]["loc"][0] == "columnDefs"


def test_column_defs_report_the_offending_setting() -> None:
    assert (
        column_defs_problem([{"field": "a"}, {"field": "b", "cellRenderer": "x"}])
        == "columnDefs[1].cellRenderer is not an allowed column setting"
    )


def test_control_schema_shape_is_unchanged_by_the_rules() -> None:
    """The rules validate values; the served control schema stays free-form."""
    echarts = Echarts.get_control_schema()["properties"]["echartsOptions"]
    table = AgGridTable.get_control_schema()["properties"]["columnDefs"]

    assert echarts["type"] == "object"
    assert echarts["x-control"] == "code"
    assert table["type"] == "array"
    assert table["items"]["type"] == "object"


@pytest.mark.parametrize(
    "widget_type, props",
    [
        (
            "echarts",
            {
                "dataBinding": BINDING,
                "echartsOptions": UNSAFE_OPTIONS["toolbox_data_view"],
            },
        ),
        (
            "ag-grid-table",
            {
                "dataBinding": BINDING,
                "columnDefs": UNSAFE_COLUMNS["value_formatter_expression"],
            },
        ),
    ],
)
def test_unsafe_definitions_are_never_stored(
    mocker: MockerFixture, widget_type: str, props: dict[str, Any]
) -> None:
    """Every write path runs the control model first, so nothing is written."""
    security = MagicMock()
    security.is_guest_user.return_value = False
    mocker.patch("superset.commands.widget.saved.security_manager", new=security)
    create = mocker.patch("superset.commands.widget.saved.SavedWidgetDAO.create")

    with pytest.raises(WidgetInvalidError) as excinfo:
        validate_widget_props(widget_type, props)
    assert excinfo.value.status == 400
    assert excinfo.value.errors

    with pytest.raises(WidgetInvalidError):
        CreateSavedWidgetCommand(
            {"widget_type": widget_type, "props": props}
        ).validate()
    create.assert_not_called()

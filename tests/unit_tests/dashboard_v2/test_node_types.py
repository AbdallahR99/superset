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
"""Which node types a save accepts — everything the builder palette can
produce — and how the props of each family are validated."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.orm.session import Session

from superset.commands.dashboard_v2.exceptions import DashboardV2InvalidError
from superset.commands.dashboard_v2.save import normalize_and_validate
from superset.dashboard_v2 import node_types
from superset.extensions import feature_flag_manager

BASE = "/api/v1/dashboard_v2/"
EXTENSION_TYPE = "extensions.acme.gauges.gauge"


def _document(**nodes: dict[str, Any]) -> dict[str, Any]:
    """A root grid holding the given nodes that no other node lists."""
    nested = {child for node in nodes.values() for child in node.get("children", ())}
    root = {"type": "grid", "children": [name for name in nodes if name not in nested]}
    return {"version": 1, "nodes": {"root": root, **nodes}}


def _palette_document() -> dict[str, Any]:
    """One of everything the built-in palette places, freshly configured the
    way the builder leaves it."""
    return _document(
        tabs={"type": "tabs", "children": ["tab_1", "tab_2"]},
        tab_1={"type": "tab", "props": {"label": "Tab 1"}, "children": ["chart"]},
        tab_2={"type": "tab", "props": {"label": "Tab 2"}, "children": []},
        chart={"type": "echarts"},
        collapsible={
            "type": "collapsible",
            "props": {"collapsed": True, "expandedRowSpan": 6},
            "children": ["text"],
        },
        text={"type": "markdown", "props": {"content": "# hi"}},
        carousel={"type": "carousel", "children": ["slide_1"]},
        slide_1={"type": "slide", "props": {"label": "Slide 1"}, "children": ["tile"]},
        tile={"type": "metric-tile", "props": {}},
        bar={"type": "filter.bar", "children": ["filter"]},
        filter={"type": "filter.select"},
        table={"type": "ag-grid-table", "props": {"dataBinding": {}}},
    )


def test_a_dashboard_using_every_palette_type_can_be_saved_and_updated(
    client: Any, dashboard_v2_enabled: None, editor: None, v2_session: Session
) -> None:
    document = _palette_document()

    created = client.post(BASE, json={"dashboard_title": "All", "document": document})
    assert created.status_code == 201, created.get_json()
    pk = created.get_json()["id"]
    updated = client.put(f"{BASE}{pk}", json={"document": document, "base_revision": 1})

    assert updated.status_code == 200, updated.get_json()
    assert updated.get_json()["result"]["document"]["nodes"] == document["nodes"]


@pytest.mark.parametrize(
    "node_type", ["tabs", "tab", "collapsible", "carousel", "slide"]
)
def test_a_structural_container_needs_a_children_array(
    app_context: None, node_type: str
) -> None:
    with pytest.raises(DashboardV2InvalidError) as excinfo:
        normalize_and_validate(_document(a={"type": node_type}))

    message = "A container must have a children array."
    assert excinfo.value.errors == {"a": [{"loc": ["children"], "message": message}]}


@pytest.mark.parametrize(
    ("node", "location"),
    [
        ({"type": "tab", "children": [], "props": {"label": 5}}, ["label"]),
        ({"type": "slide", "children": [], "props": {"label": "x" * 251}}, ["label"]),
        (
            {"type": "collapsible", "children": [], "props": {"collapsed": "yes"}},
            ["collapsed"],
        ),
        (
            {"type": "collapsible", "children": [], "props": {"expandedRowSpan": 0}},
            ["expandedRowSpan"],
        ),
    ],
)
def test_structural_container_props_are_validated(
    app_context: None, node: dict[str, Any], location: list[str]
) -> None:
    with pytest.raises(DashboardV2InvalidError) as excinfo:
        normalize_and_validate(_document(a=node))

    assert [error["loc"] for error in excinfo.value.errors["a"]] == [location]


def test_props_a_container_does_not_declare_are_kept(app_context: None) -> None:
    node = {"type": "tabs", "children": [], "props": {"title": "Mine", "x": [1]}}

    stored = normalize_and_validate(_document(a=node))

    assert stored["nodes"]["a"]["props"] == {"title": "Mine", "x": [1]}


@pytest.mark.parametrize(
    "node",
    [
        {"type": "echarts"},
        {"type": "echarts", "props": {}},
        {"type": "echarts", "props": {"dataBinding": {}}},
        {"type": "echarts", "props": {"dataBinding": {"dimensions": ["a"]}}},
        {"type": "metric-tile", "props": {"label": "Revenue"}},
        {"type": "ag-grid-table"},
        {"type": "markdown"},
        {"type": "markdown", "props": {}},
        {"type": "filter.select"},
        {"type": "filter.select", "props": {"scope": {}}},
        {"type": "filter.bar", "children": []},
        {"type": "echarts", "props": {"collapsed": True, "expandedRowSpan": 4}},
    ],
)
def test_a_widget_that_is_not_configured_yet_can_be_saved(
    app_context: None, node: dict[str, Any]
) -> None:
    stored = normalize_and_validate(_document(a=node))

    assert stored["nodes"]["a"] == node


@pytest.mark.parametrize(
    ("node", "location"),
    [
        (
            {"type": "echarts", "props": {"dataBinding": {"datasetId": "seven"}}},
            ["dataBinding", "datasetId"],
        ),
        ({"type": "echarts", "props": {"chartType": "pie-in-the-sky"}}, ["chartType"]),
        ({"type": "markdown", "props": {"content": 5}}, ["content"]),
        ({"type": "metric-tile", "props": {"dataBinding": "x"}}, ["dataBinding"]),
    ],
)
def test_props_that_are_present_are_still_validated_strictly(
    app_context: None, node: dict[str, Any], location: list[str]
) -> None:
    with pytest.raises(DashboardV2InvalidError) as excinfo:
        normalize_and_validate(_document(a=node))

    assert location in [error["loc"] for error in excinfo.value.errors["a"]]


# --------------------------------------------------------------------------
# Extension widgets
# --------------------------------------------------------------------------


def test_widget_of_an_installed_extension_is_accepted_with_generic_props(
    app_context: None, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        node_types, "installed_extension_ids", return_value={"acme.gauges"}
    )
    node = {"type": EXTENSION_TYPE, "props": {"anything": {"goes": [1, "two", None]}}}

    stored = normalize_and_validate(_document(a=node))

    assert stored["nodes"]["a"] == node


def test_extension_widget_props_stay_bounded_plain_json(
    app_context: None, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        node_types, "installed_extension_ids", return_value={"acme.gauges"}
    )
    deep: Any = "leaf"
    for _ in range(40):
        deep = {"nested": deep}

    with pytest.raises(DashboardV2InvalidError, match="nested deeper than 32"):
        normalize_and_validate(_document(a={"type": EXTENSION_TYPE, "props": deep}))
    with pytest.raises(DashboardV2InvalidError, match="non-finite"):
        normalize_and_validate(
            _document(a={"type": EXTENSION_TYPE, "props": {"x": float("inf")}})
        )


@pytest.mark.parametrize(
    "node_type",
    [
        EXTENSION_TYPE,  # extension not installed
        "extensions.acme.gauge",  # no widget name after the extension id
        "acme.gauges.gauge",  # not in the extensions namespace
    ],
)
def test_extension_like_types_that_are_not_installed_stay_unknown(
    app_context: None, mocker: MockerFixture, node_type: str
) -> None:
    mocker.patch.object(
        node_types, "installed_extension_ids", return_value={"other.extension"}
    )

    with pytest.raises(DashboardV2InvalidError, match="unknown type"):
        normalize_and_validate(_document(a={"type": node_type}))


def test_installed_extensions_come_from_the_extension_loader(
    app_context: None, mocker: MockerFixture
) -> None:
    mocker.patch.dict(feature_flag_manager._feature_flags, {"ENABLE_EXTENSIONS": True})
    mocker.patch(
        "superset.extensions.utils.get_extensions",
        return_value={"acme.gauges": object()},
    )

    assert node_types.accepted_extension_types(
        [EXTENSION_TYPE, "extensions.other.thing.x", "markdown"]
    ) == {EXTENSION_TYPE}


def test_no_extension_type_is_accepted_while_extensions_are_disabled(
    app_context: None, mocker: MockerFixture
) -> None:
    mocker.patch.dict(feature_flag_manager._feature_flags, {"ENABLE_EXTENSIONS": False})
    loader = mocker.patch("superset.extensions.utils.get_extensions")

    assert node_types.accepted_extension_types([EXTENSION_TYPE]) == set()
    loader.assert_not_called()


def test_extensions_are_not_listed_for_documents_without_extension_types(
    app_context: None, mocker: MockerFixture
) -> None:
    lookup = mocker.patch.object(node_types, "installed_extension_ids")

    normalize_and_validate(_palette_document())

    lookup.assert_not_called()


def test_a_broken_extension_bundle_does_not_fail_the_save(
    app_context: None, mocker: MockerFixture
) -> None:
    mocker.patch.dict(feature_flag_manager._feature_flags, {"ENABLE_EXTENSIONS": True})
    mocker.patch(
        "superset.extensions.utils.get_extensions", side_effect=RuntimeError("boom")
    )

    with pytest.raises(DashboardV2InvalidError, match="unknown type"):
        normalize_and_validate(_document(a={"type": EXTENSION_TYPE}))

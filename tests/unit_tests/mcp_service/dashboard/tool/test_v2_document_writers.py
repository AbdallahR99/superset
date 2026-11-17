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
"""The MCP dashboard tools that write ``json_metadata`` of a Dashboard v2
dashboard: they store through the document's compare-and-swap, and a write
that keeps losing against concurrent writers is reported, not forced."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import Mock, patch

import pytest
from fastmcp import Client

from superset.utils import json

SWAP = "superset.daos.dashboard.write_metadata_keeping_document"


def _document(revision: int, child: str) -> dict[str, Any]:
    return {
        "version": 1,
        "revision": revision,
        "nodes": {
            "root": {"type": "grid", "children": [child]},
            child: {"type": "markdown", "props": {"content": child}},
        },
    }


def _mock_dashboard(json_metadata: str, slices: list[Mock] | None = None) -> Mock:
    """A dashboard with every field the response serializers read."""
    dashboard = Mock()
    dashboard.id = 42
    dashboard.dashboard_title = "Sales"
    dashboard.slug = "sales"
    dashboard.description = None
    dashboard.published = True
    dashboard.css = None
    dashboard.json_metadata = json_metadata
    dashboard.position_json = "{}"
    dashboard.certified_by = None
    dashboard.certification_details = None
    dashboard.deleted_at = None
    dashboard.is_managed_externally = False
    dashboard.external_url = None
    dashboard.created_on = datetime(2024, 1, 1)
    dashboard.changed_on = datetime(2024, 1, 1)
    dashboard.created_by = Mock(username="admin")
    dashboard.changed_by = Mock(username="admin")
    dashboard.created_by_name = "admin"
    dashboard.changed_by_name = "admin"
    dashboard.created_on_humanized = "a day ago"
    dashboard.changed_on_humanized = "a day ago"
    dashboard.uuid = "dashboard-uuid-42"
    dashboard.slices = slices or []
    dashboard.editors = []
    dashboard.tags = []
    dashboard.embedded = []
    return dashboard


def _mock_chart(chart_id: int) -> Mock:
    chart = Mock()
    chart.id = chart_id
    chart.slice_name = f"Chart {chart_id}"
    chart.uuid = f"chart-uuid-{chart_id}"
    chart.tags = []
    chart.editors = []
    chart.viz_type = "table"
    chart.datasource_name = None
    chart.description = None
    return chart


async def _update(mcp_server: object, overrides: dict[str, Any]) -> dict[str, Any]:
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "update_dashboard",
            {"request": {"identifier": 42, "json_metadata_overrides": overrides}},
        )
    return json.loads(result.content[0].text)


@patch("superset.daos.dashboard.DashboardDAO.get_by_id_or_slug")
@patch("superset.extensions.db.session")
@pytest.mark.asyncio
async def test_update_dashboard_reports_a_write_that_keeps_losing(
    mock_session: Mock, mock_get: Mock, mcp_server: object
) -> None:
    """``DashboardUpdateFailedError`` from the compare-and-swap becomes a
    conflict answer; nothing is committed and the session is rolled back."""
    loaded = json.dumps({"color_scheme": "old", "v2_document": _document(3, "a")})
    dashboard = _mock_dashboard(loaded)
    mock_get.return_value = dashboard

    with patch(SWAP, return_value=None) as swap:
        payload = await _update(mcp_server, {"color_scheme": "new"})

    swap.assert_called_once()
    assert payload["error_type"] == "Conflict"
    assert "changed by someone else" in payload["error"]
    assert dashboard.json_metadata == loaded
    mock_session.commit.assert_not_called()
    mock_session.rollback.assert_called_once()


@patch("superset.daos.dashboard.DashboardDAO.get_by_id_or_slug")
@patch("superset.extensions.db.session")
@pytest.mark.asyncio
async def test_update_dashboard_stores_what_the_compare_and_swap_stored(
    mock_session: Mock, mock_get: Mock, mcp_server: object
) -> None:
    """The document comes from the row at the time of the write (revision 4),
    not from the copy the tool loaded (revision 3)."""
    dashboard = _mock_dashboard(
        json.dumps({"color_scheme": "old", "v2_document": _document(3, "a")})
    )
    mock_get.return_value = dashboard
    stored = json.dumps({"color_scheme": "new", "v2_document": _document(4, "b")})

    with patch(SWAP, return_value=stored) as swap:
        payload = await _update(mcp_server, {"color_scheme": "new"})

    pk, metadata = swap.call_args.args
    assert pk == 42
    assert metadata["color_scheme"] == "new"
    assert payload.get("error") is None
    assert dashboard.json_metadata == stored
    assert mock_session.commit.call_count >= 1


async def _remove_chart(mcp_server: object) -> dict[str, Any]:
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "remove_chart_from_dashboard",
            {"request": {"dashboard_id": 42, "chart_id": 10}},
        )
    return result.structured_content


def _layout() -> dict[str, Any]:
    return {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"]},
        "GRID_ID": {
            "id": "GRID_ID",
            "type": "GRID",
            "parents": ["ROOT_ID"],
            "children": ["ROW-1"],
        },
        "ROW-1": {
            "id": "ROW-1",
            "type": "ROW",
            "parents": ["ROOT_ID", "GRID_ID"],
            "children": ["CHART-10", "CHART-20"],
            "meta": {},
        },
        "CHART-10": {
            "id": "CHART-10",
            "type": "CHART",
            "parents": ["ROOT_ID", "GRID_ID", "ROW-1"],
            "children": [],
            "meta": {"chartId": 10, "width": 4, "height": 50},
        },
        "CHART-20": {
            "id": "CHART-20",
            "type": "CHART",
            "parents": ["ROOT_ID", "GRID_ID", "ROW-1"],
            "children": [],
            "meta": {"chartId": 20, "width": 4, "height": 50},
        },
    }


def _removal_dashboards() -> tuple[Mock, Mock]:
    """The dashboard as loaded, and as re-fetched after the chart removal:
    a v2 dashboard whose metadata still references the removed chart."""
    before = _mock_dashboard("{}", slices=[_mock_chart(10), _mock_chart(20)])
    before.position_json = json.dumps(_layout())
    after = _mock_dashboard(
        json.dumps(
            {
                "expanded_slices": {"10": True, "20": True},
                "v2_document": _document(3, "a"),
            }
        ),
        slices=[_mock_chart(20)],
    )
    return before, after


@patch("superset.commands.dashboard.update.UpdateDashboardCommand")
@patch("superset.security_manager.raise_for_editorship")
@patch("superset.daos.dashboard.DashboardDAO.find_by_id")
@pytest.mark.asyncio
async def test_remove_chart_cleans_metadata_through_the_compare_and_swap(
    mock_find_by_id: Mock,
    mock_raise_for_editorship: Mock,
    mock_update_cmd_cls: Mock,
    mcp_server: object,
) -> None:
    """The cleaned metadata is stored through the helper, which takes the
    document from the row: a v2 save that landed after the tool re-fetched
    the dashboard (revision 4) is kept, not rolled back to revision 3."""
    before, after = _removal_dashboards()
    mock_find_by_id.side_effect = [before, after]
    mock_update_cmd_cls.return_value.run.return_value = after
    stored = json.dumps(
        {"expanded_slices": {"20": True}, "v2_document": _document(4, "b")}
    )

    with patch(SWAP, return_value=stored) as swap, patch("superset.db.session"):
        content = await _remove_chart(mcp_server)

    assert content["error"] is None
    pk, metadata = swap.call_args.args
    assert pk == 42
    assert metadata["expanded_slices"] == {"20": True}
    assert after.json_metadata == stored
    assert json.loads(after.json_metadata)["v2_document"]["revision"] == 4


@patch("superset.commands.dashboard.update.UpdateDashboardCommand")
@patch("superset.security_manager.raise_for_editorship")
@patch("superset.daos.dashboard.DashboardDAO.find_by_id")
@pytest.mark.asyncio
async def test_remove_chart_leaves_metadata_alone_when_the_swap_keeps_losing(
    mock_find_by_id: Mock,
    mock_raise_for_editorship: Mock,
    mock_update_cmd_cls: Mock,
    mcp_server: object,
) -> None:
    """The chart is already removed; a metadata cleanup that cannot be
    stored without overwriting someone else's write is skipped."""
    before, after = _removal_dashboards()
    loaded = after.json_metadata
    mock_find_by_id.side_effect = [before, after]
    mock_update_cmd_cls.return_value.run.return_value = after

    with patch(SWAP, return_value=None), patch("superset.db.session") as session:
        content = await _remove_chart(mcp_server)

    assert content["error"] is None
    assert after.json_metadata == loaded
    session.rollback.assert_called_once()

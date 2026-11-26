# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Exercise the property-market provider on an isolated native Superset host."""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - standalone browser runner
import math
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import (
    Error,
    expect,
    Locator,
    Page,
    Response,
    sync_playwright,
)

PROVIDER = "extensions.nxtbi.property-market-lab.market"
VIEW_NAME = "property_transactions"
LAYER_API = "/api/v1/semantic_layer/"
VIEW_API = "/api/v1/semantic_view/"
DATASOURCE_API = "/api/v1/datasource/"
CHART_API = "/api/v1/chart/"
DASHBOARD_API = "/api/v1/dashboard/"
TIMEOUT = 30_000
METRICS = (
    "transaction_count",
    "average_transaction_price",
    "weighted_price_per_sqm",
    "distinct_property_count",
)
EXPECTED = {
    "Apartment": (3, 380_000, 6_000, 2),
    "Villa": (2, 570_000, 1_140_000 / 420, 1),
    "Unknown": (1, 120_000, None, 1),
}


def login(page: Page, base: str, username: str, password: str) -> None:
    """Establish and verify the real Superset password session."""
    page.goto(f"{base}/login/")
    try:
        page.locator(
            '[data-test="username-input"] input, input[data-test="username-input"]'
        ).fill(username)
        page.locator(
            '[data-test="password-input"] input, input[data-test="password-input"]'
        ).fill(password)
        page.locator('[data-test="login-button"]').click()
        page.wait_for_url(lambda url: urlsplit(url).path.rstrip("/") != "/login")
    except Error:
        raise AssertionError("The lab password login did not complete.") from None
    response = page.request.get(f"{base}/api/v1/me/")
    assert response.ok, f"Read lab identity HTTP {response.status}."
    assert response.json()["result"]["username"] == username


class LabApi:
    """Use one signed-in browser context for the synthetic fixture mutations."""

    def __init__(self, page: Page, base: str) -> None:
        """Acquire a CSRF token tied to the browser's auth cookies."""
        self.page = page
        self.base = base
        token = self.call("GET", "/api/v1/security/csrf_token/")["result"]
        assert isinstance(token, str)
        assert token
        self.headers = {"X-CSRFToken": token, "Referer": f"{base}/"}

    def call(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run a normal REST request and validate its response envelope."""
        response = self.page.request.fetch(
            f"{self.base}{path}",
            method=method,
            data=payload,
            headers=self.headers if method != "GET" else None,
        )
        assert response.ok, (
            f"{method} {path} returned HTTP {response.status}: {response.text()[:400]}"
        )
        if method == "DELETE":
            return {}
        data = response.json()
        assert isinstance(data, dict), f"{method} {path} returned a non-object."
        return data


def datasource_rows(page: Page, base: str) -> list[dict[str, Any]]:
    """Read the normal datasource list as the signed-in principal."""
    response = page.request.get(
        f"{base}{DATASOURCE_API}",
        params={
            "q": f"(filters:!((col:table_name,opr:ct,value:{VIEW_NAME})),page_size:100)"
        },
    )
    assert response.ok, f"Read datasource list HTTP {response.status}."
    rows = response.json()["result"]
    assert isinstance(rows, list)
    return rows


def register_view(api: LabApi, cleanup: ExitStack) -> tuple[str, int]:
    """Register the provider and resolve the persisted view ID used by charts."""
    types = api.call("GET", f"{LAYER_API}types")["result"]
    assert any(item["id"] == PROVIDER for item in types), (
        "The host has not loaded the property-market lab extension."
    )
    layer_uuid = api.call(
        "POST",
        LAYER_API,
        payload={
            "name": f"Property market lab {uuid4().hex[:8]}",
            "type": PROVIDER,
            "configuration": {},
        },
    )["result"]["uuid"]
    cleanup.callback(api.call, "DELETE", f"{LAYER_API}{layer_uuid}")
    view_uuid = api.call(
        "POST",
        VIEW_API,
        payload={"views": [{"name": VIEW_NAME, "semantic_layer_uuid": layer_uuid}]},
    )["result"]["created"][0]["uuid"]
    matches = [
        row["id"]
        for row in datasource_rows(api.page, api.base)
        if row["kind"] == "semantic_view" and row["uuid"] == view_uuid
    ]
    assert len(matches) == 1
    assert isinstance(matches[0], int)
    return view_uuid, matches[0]


def save_chart(api: LabApi, cleanup: ExitStack, view_id: int, title: str) -> int:
    """Save the native table chart using approved metric and dimension names."""
    params = {
        "datasource": f"{view_id}__semantic_view",
        "viz_type": "table",
        "query_mode": "aggregate",
        "groupby": ["property_type"],
        "metrics": list(METRICS),
        "adhoc_filters": [],
        "row_limit": 100,
    }
    chart_id = api.call(
        "POST",
        CHART_API,
        payload={
            "slice_name": title,
            "viz_type": "table",
            "datasource_id": view_id,
            "datasource_type": "semantic_view",
            "params": json.dumps(params),
        },
    )["id"]
    assert isinstance(chart_id, int)
    cleanup.callback(api.call, "DELETE", f"{CHART_API}{chart_id}")
    return chart_id


def save_dashboard(
    api: LabApi,
    cleanup: ExitStack,
    view_id: int,
    chart_id: int,
    chart_title: str,
    title: str,
) -> int:
    """Persist the chart layout and its native semantic filter."""
    root = "ROOT_ID"
    grid = "GRID_ID"
    row = "ROW-1"
    chart = f"CHART-{chart_id}"
    layout = {
        "DASHBOARD_VERSION_KEY": "v2",
        root: {"type": "ROOT", "id": root, "children": [grid]},
        grid: {"type": "GRID", "id": grid, "children": [row], "parents": [root]},
        row: {
            "type": "ROW",
            "id": row,
            "children": [chart],
            "parents": [root, grid],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        },
        chart: {
            "type": "CHART",
            "id": chart,
            "children": [],
            "parents": [root, grid, row],
            "meta": {
                "chartId": chart_id,
                "width": 12,
                "height": 50,
                "sliceName": chart_title,
            },
        },
    }
    scope = {"rootPath": [root], "excluded": []}
    native_filter = {
        "id": "NATIVE_FILTER-property-market-type",
        "name": "Property type",
        "filterType": "filter_select",
        "type": "NATIVE_FILTER",
        "targets": [
            {
                "datasetId": view_id,
                "datasourceType": "semantic_view",
                "column": {"name": "property_type"},
            }
        ],
        "controlValues": {
            "multiSelect": False,
            "enableEmptyFilter": False,
            "defaultToFirstItem": False,
            "inverseSelection": False,
            "searchAllOptions": False,
        },
        "defaultDataMask": {"filterState": {}, "extraFormData": {}},
        "cascadeParentIds": [],
        "scope": scope,
        "chartsInScope": [chart_id],
    }
    metadata = {
        "native_filter_configuration": [native_filter],
        "chart_configuration": {},
        "cross_filters_enabled": False,
        "global_chart_configuration": {"scope": scope, "chartsInScope": [chart_id]},
    }
    dashboard_id = api.call(
        "POST",
        DASHBOARD_API,
        payload={
            "dashboard_title": title,
            "published": True,
            "position_json": json.dumps(layout),
            "json_metadata": json.dumps(metadata),
        },
    )["id"]
    assert isinstance(dashboard_id, int)
    cleanup.callback(api.call, "DELETE", f"{DASHBOARD_API}{dashboard_id}")
    api.call("PUT", f"{CHART_API}{chart_id}", payload={"dashboards": [dashboard_id]})
    return dashboard_id


def is_chart_data(response: Response) -> bool:
    """Match the main table query while ignoring native filter option requests."""
    if (
        response.request.method != "POST"
        or urlsplit(response.url).path.rstrip("/") != f"{CHART_API}data"
    ):
        return False
    body = response.request.post_data_json
    return isinstance(body, dict) and any(
        list(METRICS) == query.get("metrics") for query in body.get("queries", [])
    )


def assert_chart_rows(response: Response, categories: set[str]) -> None:
    """Compare typed results against independent fixture totals."""
    assert response.ok, f"Table data HTTP {response.status}: {response.text()[:400]}"
    queries = response.json()["result"]
    assert len(queries) == 1
    rows = queries[0]["data"]
    assert len(rows) == len(categories)
    assert {row["property_type"] for row in rows} == categories
    for row in rows:
        category = row["property_type"]
        count, mean, weighted, distinct = EXPECTED[category]
        assert row[METRICS[0]] == count, row
        assert row[METRICS[3]] == distinct, row
        assert math.isclose(row[METRICS[1]], mean), row
        if weighted is None:
            assert row[METRICS[2]] is None, row
        else:
            assert math.isclose(row[METRICS[2]], weighted), row


def assert_visible_categories(chart: Locator, categories: set[str]) -> None:
    """Distinguish chart render success from a successful data request alone."""
    for category in EXPECTED:
        category_cell = chart.get_by_role("cell").get_by_text(category, exact=True)
        expect(category_cell).to_have_count(int(category in categories))


def verify_explore(page: Page, base: str, chart_id: int) -> None:
    """Open the actual native Explore route and inspect its rendered result."""
    with page.expect_response(is_chart_data) as captured:
        page.goto(f"{base}/explore/?slice_id={chart_id}")
    assert_chart_rows(captured.value, set(EXPECTED))
    expect(page.locator('[data-test="datasource-control"]')).to_contain_text(VIEW_NAME)
    assert_visible_categories(
        page.locator('[data-test="chart-container"]'), set(EXPECTED)
    )


def verify_dashboard(
    page: Page, base: str, dashboard_id: int, chart_id: int, title: str
) -> None:
    """Reopen the persisted Classic dashboard and apply its native filter."""
    with page.expect_response(is_chart_data) as captured:
        page.goto(f"{base}/dashboard/{dashboard_id}/")
    assert_chart_rows(captured.value, set(EXPECTED))
    expect(page.get_by_text(title, exact=True).first).to_be_visible()
    chart = page.locator(
        f'[data-test="chart-grid-component"][data-test-chart-id="{chart_id}"]'
    )
    assert_visible_categories(chart, set(EXPECTED))

    filter_bar = page.locator('[data-test="filter-bar"]')
    control = filter_bar.locator('[data-test="form-item-value"]').get_by_role(
        "combobox"
    )
    control.click()
    options = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")
    options.get_by_text("Villa", exact=True).click()
    with page.expect_response(is_chart_data) as filtered:
        filter_bar.locator('[data-test="filter-bar__apply-button"]').click()
    assert_chart_rows(filtered.value, {"Villa"})
    assert_visible_categories(chart, {"Villa"})


def main() -> None:
    """Run the portable lab browser proof and clean its own test records."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    url = urlsplit(base)
    if (
        url.scheme != "http"
        or url.hostname not in {"localhost", "127.0.0.1"}
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
        or not url.port
    ):
        parser.error("Use the isolated Superset lab HTTP origin on a loopback port.")
    username = os.environ.get("NXTBI_SEMANTIC_LAB_USER")
    password = os.environ.get("NXTBI_SEMANTIC_LAB_PASSWORD")
    viewer = os.environ.get("NXTBI_SEMANTIC_LAB_VIEWER")
    viewer_password = os.environ.get("NXTBI_SEMANTIC_LAB_VIEWER_PASSWORD")
    if not username or not password:
        parser.error("The lab harness must supply the browser credentials.")
    if bool(viewer) != bool(viewer_password):
        parser.error("Supply both viewer environment variables or neither.")
    if args.artifact_dir:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)

    expect.set_options(timeout=TIMEOUT)
    with sync_playwright() as playwright, ExitStack() as sessions:
        browser = playwright.chromium.launch()
        sessions.callback(browser.close)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000}, locale="en-US"
        )
        page.set_default_timeout(TIMEOUT)
        login(page, base, username, password)
        with ExitStack() as cleanup:
            api = LabApi(page, base)
            view_uuid, view_id = register_view(api, cleanup)
            print("PASS native provider registration and semantic-view listing")
            suffix = uuid4().hex[:8]
            chart_title = f"Property prices by type {suffix}"
            chart_id = save_chart(api, cleanup, view_id, chart_title)
            verify_explore(page, base, chart_id)
            print("PASS Explore rendered 3 categories, mean price and weighted price")
            title = f"Property market {suffix}"
            dashboard_id = save_dashboard(
                api, cleanup, view_id, chart_id, chart_title, title
            )
            verify_dashboard(page, base, dashboard_id, chart_id, title)
            print("PASS saved Classic dashboard and live Villa filter")
            if args.artifact_dir:
                page.screenshot(path=str(args.artifact_dir / "property-market.png"))
            if viewer and viewer_password:
                viewer_page = browser.new_page(locale="en-US")
                viewer_page.set_default_timeout(TIMEOUT)
                login(viewer_page, base, viewer, viewer_password)
                assert all(
                    row["uuid"] != view_uuid
                    for row in datasource_rows(viewer_page, base)
                ), "The ungranted viewer can list the synthetic semantic view."
                print("PASS ungranted viewer datasource listing")
            if os.environ.get("NXTBI_SEMANTIC_LAB_KEEP_ASSETS") == "1":
                cleanup.pop_all()  # The disposable host owns teardown after MCP.


if __name__ == "__main__":
    main()

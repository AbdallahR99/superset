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
"""Verify the Copilot dashboard lifecycle on disposable local deployments.

Use a Superset deployment with local browser auth, Copilot and an upload target
configured, and the SDK Vite example on another port of the same hostname.
The script creates a dataset and saves a dashboard and widget. The deployment
and the imported fixture data should be discarded after the run.
Set NXTBI_E2E_MODEL_PROBE=1 for a separate natural-language check against
the configured model provider, scoped to the synthetic CSV.
"""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - Standalone browser test uses the standard library.
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from playwright.sync_api import (
    Error,
    expect,
    Locator,
    Page,
    Response,
    Route,
    sync_playwright,
)

COPILOT_API = "/api/v1/nxtbi_copilot"
WIDGET_DATA = "/api/v1/widget/data"
TIMEOUT = 45_000
CSV = (
    b"order_date,region,revenue\n"
    b"2026-01-01,North,100\n2026-01-02,South,125\n"
    b"2026-01-03,North,150\n2026-01-04,South,175\n"
)
METRIC = "sum_revenue"
TOTAL = 550
NORTH_TOTAL = 250
PROPOSED_WIDGET_TITLE = "Revenue total for review"


@dataclass(frozen=True)
class SavedWidget:
    """Identify the edited widget and its real data for both embedding modes."""

    uuid: str
    dataset_id: int
    table: str
    label: str


def matches(response: Response, method: str, path: str) -> bool:
    """Match the method and path of one Superset browser response."""
    return response.request.method == method and urlsplit(response.url).path == path


def login(page: Page, base: str, username: str, password: str) -> None:
    """Authenticate through Superset's real password login on the test stack."""
    page.goto(f"{base}/login/")
    page.locator(
        '[data-test="username-input"] input, input[data-test="username-input"]'
    ).fill(username)
    page.locator(
        '[data-test="password-input"] input, input[data-test="password-input"]'
    ).fill(password)
    page.locator('[data-test="login-button"]').click()
    page.wait_for_url(lambda url: urlsplit(url).path != "/login/")
    me = page.request.get(f"{base}/api/v1/me/")
    assert me.ok, f"Read current Superset user HTTP {me.status}"
    assert me.json()["result"]["username"] == username, (
        "Superset did not establish the expected browser session."
    )
    page.goto(f"{base}/lang/en")
    page.goto(f"{base}/dashboard/list/")


def open_chat(page: Page, *, arabic: bool = False) -> Locator:
    """Open the compiled host extension unless its panel was restored."""
    panel = page.locator("#nxtbi-copilot-panel")
    composer = panel.get_by_role(
        "textbox", name="اسأل المساعد" if arabic else "Ask Copilot"
    )
    trigger = page.get_by_role(
        "button", name="مساعد NxtBI" if arabic else "NxtBI Copilot", exact=True
    )
    expect(trigger).to_be_visible()
    if trigger.get_attribute("aria-expanded") != "true":
        trigger.click()
    expect(composer).to_be_visible()
    return panel


def read_agui_run(
    page: Page, trigger: Locator, *, timeout: int = TIMEOUT
) -> list[dict[str, Any]]:
    """Capture AG-UI without buffering or replacing the response the UI sees."""
    endpoint = f"{COPILOT_API}/run"
    page.evaluate(
        """(runPath) => {
          window.lifecycleStream = undefined;
          if (window.lifecycleObserver) return;
          window.lifecycleObserver = true;
          const fetch = window.fetch.bind(window);
          window.fetch = async (...args) => {
            const response = await fetch(...args);
            if (response.url && new URL(response.url).pathname === runPath) {
              window.lifecycleStream = response.clone().text();
            }
            return response;
          };
        }""",
        endpoint,
    )
    with page.expect_response(
        lambda response: matches(response, "POST", endpoint), timeout=timeout
    ) as run:
        trigger.click()
    response = run.value
    assert response.ok, f"Copilot run HTTP {response.status}"
    assert "text/event-stream" in response.headers.get("content-type", "")
    stream = page.evaluate(
        """(timeout) => Promise.race([
          window.lifecycleStream,
          new Promise(resolve => setTimeout(() => resolve(''), timeout)),
        ])""",
        timeout,
    )
    assert stream, "The browser did not capture the completed Copilot stream."
    events = [
        json.loads(line.removeprefix("data:").strip())
        for line in stream.splitlines()
        if line.startswith("data:") and line.removeprefix("data:").strip() != "[DONE]"
    ]
    assert events, "Copilot returned an empty AG-UI stream."
    assert events[0].get("type") == "RUN_STARTED"
    terminal_code = events[-1].get("code")
    if not isinstance(terminal_code, str) or not re.fullmatch(
        r"[a-z0-9_]{1,40}", terminal_code
    ):
        terminal_code = "unavailable"
    assert events[-1].get("type") == "RUN_FINISHED", (
        f"The AG-UI stream did not finish successfully (code: {terminal_code})."
    )
    return events


def verify_evidence(
    panel: Locator, events: list[dict[str, Any]], dataset_id: int, source_name: str
) -> Locator:
    """Check measured fixture values in native A2UI operations and rendered cells."""
    evidence = next(
        (
            event
            for event in events
            if event.get("type") == "ACTIVITY_SNAPSHOT"
            and event.get("activityType") == "a2ui-surface"
        ),
        None,
    )
    assert evidence is not None, (
        "The uploaded draft did not stream native A2UI evidence."
    )
    create, update = evidence["content"]["a2ui_operations"]
    assert create["version"] == update["version"] == "1.0"
    surface_id = create["createSurface"]["surfaceId"]
    assert update["updateComponents"]["surfaceId"] == surface_id
    components = update["updateComponents"]["components"]
    headline = next(item for item in components if item["component"] == "Metric")
    assert float(headline["value"]) == TOTAL
    assert headline["@catalogId"] == "urn:nxtbi:a2ui:1.0"
    assert headline["detail"] == "All accessible rows (4)"
    comparison = next(item for item in components if item["component"] == "Table")
    groups = {"North": 250, "South": 300}
    assert {row["group"]: float(row["value"]) for row in comparison["rows"]} == groups

    surface = panel.locator(f'[data-a2ui-surface="{surface_id}"]')
    expect(surface.get_by_text("Evidence used", exact=True)).to_be_visible()
    expect(
        surface.get_by_text(f"{source_name} · #{dataset_id}", exact=True)
    ).to_be_visible()
    expect(surface.get_by_text(re.compile(rf"^{TOTAL}(?:\.0+)?$"))).to_be_visible()
    comparison_table = surface.get_by_role("table", name="region", exact=True)
    for group, value in groups.items():
        row = comparison_table.get_by_role("row").filter(has_text=group)
        expect(row.get_by_role("cell", name=group, exact=True)).to_be_visible()
        expect(
            row.get_by_role("cell", name=re.compile(rf"^{value}(?:\.0+)?$"))
        ).to_be_visible()
    return surface


def is_kpi_preview(response: Response, dataset_id: int) -> bool:
    """Name the real widget data request for the proposal's revenue KPI."""
    if not matches(response, "POST", WIDGET_DATA):
        return False
    widget = response.request.post_data_json.get("widget", {})
    binding = widget.get("props", {}).get("dataBinding", {})
    return (
        widget.get("type") == "metric-tile"
        and binding.get("datasetId") == dataset_id
        and METRIC in binding.get("metrics", [])
    )


def create_draft(
    page: Page, base: str, title: str, artifact_dir: Path | None
) -> tuple[int, int, str]:
    """Import a fixture, stream an editable proposal, and approve the draft."""
    panel = open_chat(page)
    panel.locator('input[type="file"][accept*=".csv"]').set_input_files(
        {"name": f"{title}.csv", "mimeType": "text/csv", "buffer": CSV}
    )
    with page.expect_response(
        lambda response: matches(response, "POST", f"{COPILOT_API}/upload/")
    ) as upload:
        panel.get_by_role("button", name="Import CSV files", exact=True).click()
    response = upload.value
    assert response.status == 201, f"Copilot upload HTTP {response.status}"
    dataset_id = response.json()["id"]
    dataset = page.request.get(f"{base}/api/v1/dataset/{dataset_id}")
    assert dataset.ok, f"Read imported dataset HTTP {dataset.status}"
    table = dataset.json()["result"]["table_name"]

    with page.expect_response(
        lambda response: is_kpi_preview(response, dataset_id)
    ) as preview:
        events = read_agui_run(
            page,
            panel.get_by_role(
                "button", name="Draft dashboard from dataset", exact=True
            ),
        )
    evidence = verify_evidence(panel, events, dataset_id, f"{title}.csv")
    draft = next(
        event["value"]
        for event in events
        if event.get("type") == "CUSTOM"
        and event.get("name") == "nxtbi.dashboard-proposal"
    )
    assert {("bar", "region"), ("line", "order_date")} <= {
        (item.get("chartStyle"), item.get("dimension"))
        for item in draft["widgets"]
        if item["type"] == "echarts"
    }, "The draft omitted the categorical or temporal view."
    data = preview.value
    assert data.ok, f"Copilot KPI preview HTTP {data.status}"
    assert float(data.json()["result"]["rows"][0][METRIC]) == TOTAL
    proposal = page.get_by_role("region", name="Dashboard proposal", exact=True)
    expect(proposal.locator("canvas").first).to_be_visible()
    title_field = proposal.get_by_role("textbox", name="Dashboard title", exact=True)
    title_field.fill(title)
    widget_editor = proposal.get_by_role("article").first
    widget_editor.locator("summary").filter(has_text="Edit widget").click()
    widget_editor.get_by_role("textbox", name="Widget title", exact=True).fill(
        PROPOSED_WIDGET_TITLE
    )
    widget_editor.locator("summary").filter(has_text="Edit widget").click()
    proposal.get_by_role("button", name="Refresh previews", exact=True).click()
    expect(
        widget_editor.locator('[data-superset-widget="metric-tile"]').get_by_text(
            PROPOSED_WIDGET_TITLE, exact=True
        )
    ).to_be_visible()
    if artifact_dir is not None:
        evidence.scroll_into_view_if_needed()
        page.screenshot(path=artifact_dir / "copilot-evidence.png")
        title_field.scroll_into_view_if_needed()
        page.screenshot(path=artifact_dir / "copilot-proposal.png")
    proposal.get_by_role("button", name="Review and save", exact=True).click()
    with page.expect_response(
        lambda response: matches(response, "POST", f"{COPILOT_API}/approve")
    ) as approval:
        proposal.get_by_role("button", name="Save dashboard", exact=True).click()
    response = approval.value
    assert response.status == 201, f"Copilot approval HTTP {response.status}"
    result = response.json()
    dashboard_id = result["id"]
    assert result["url"] == f"/dashboard/v2/{dashboard_id}/"
    page.get_by_role("button", name="Open dashboard", exact=True).click()
    page.wait_for_url(f"{base}{result['url']}")
    expect(page.locator('[data-test="header-title"]')).to_have_value(title)
    print(
        f"PASS CSV dataset {dataset_id}, AG-UI draft, dashboard {dashboard_id}",
        flush=True,
    )
    return dashboard_id, dataset_id, table


def stored_dashboard(page: Page, url: str) -> dict[str, Any]:
    """Read the authoritative Dashboard V2 document through the owner session."""
    response = page.request.get(url)
    assert response.ok, f"Read Dashboard V2 HTTP {response.status}"
    return response.json()["result"]


def save_dashboard(page: Page, api_path: str) -> None:
    """Click the actual builder Save action and require its successful response."""
    expect(page.locator('[data-test="header-unsaved"]')).to_be_visible()
    with page.expect_response(
        lambda response: matches(response, "PUT", api_path)
    ) as saved:
        page.locator('[data-test="header-save"]').click()
    assert saved.value.ok, f"Save Dashboard V2 HTTP {saved.value.status}"
    expect(page.locator('[data-test="header-unsaved"]')).to_have_count(0)


def verify_saved_history(page: Page, dashboard_uuid: str, label: str) -> None:
    """Check the committed widget edit in server history and in the builder."""
    activity = f"/api/v1/dashboard/{dashboard_uuid}/activity/"
    with page.expect_response(
        lambda response: (
            matches(response, "GET", activity)
            and parse_qs(urlsplit(response.url).query).get("page_size") == ["25"]
        )
    ) as loaded:
        page.locator('[data-test="header-history"]').click()
    response = loaded.value
    assert response.ok, f"Read Dashboard V2 history HTTP {response.status}"
    records = response.json()["result"]
    assert any(
        record.get("source") == "self"
        and record.get("from_value") == PROPOSED_WIDGET_TITLE
        and record.get("to_value") == label
        and record.get("path", [])[-1:] == ["label"]
        for record in records
    ), "Saved widget edit missing from history: " + repr(
        [
            (record.get("path"), record.get("from_value"), record.get("to_value"))
            for record in records
        ]
    )
    history = page.get_by_role("dialog", name="Version history", exact=True)
    summary = history.locator("details > summary").first
    expect(summary).to_be_visible()
    summary.click()
    expect(history.locator("details[open] li").first).to_be_visible()
    history.get_by_role("button", name="Close", exact=True).last.click()


def edit_publish_and_save_widget(
    page: Page,
    base: str,
    dashboard_id: int,
    dataset_id: int,
    table: str,
) -> SavedWidget:
    """Edit the Copilot's KPI, publish the dashboard, and persist its embed id."""
    dashboard_api = f"/api/v1/dashboard_v2/{dashboard_id}"
    initial = stored_dashboard(page, f"{base}{dashboard_api}")
    assert initial["revision"] == 1
    assert initial["published"] is False
    node_id = next(
        (
            node_id
            for node_id, node in initial["document"]["nodes"].items()
            if node["type"] == "metric-tile"
            and node["props"].get("dataBinding", {}).get("datasetId") == dataset_id
            and METRIC in node["props"]["dataBinding"]["metrics"]
        ),
        None,
    )
    assert node_id, "The saved dashboard was missing the KPI for the imported revenue."
    tile = page.locator(f'[data-test="widget-content-{node_id}"]')
    expect(tile.get_by_text(str(TOTAL), exact=True)).to_be_visible()
    tile.click()
    page.locator(
        '[data-test="editor-panel"] [data-node-key="properties"] [role="tab"]'
    ).click()
    label = "Reviewed revenue total"
    label_field = page.locator('[data-test="schema-control-panel"] input#label')
    original_label = label_field.input_value()
    label_field.fill(label)
    expect(tile.get_by_text(label, exact=True)).to_be_visible()
    page.locator('[data-test="header-undo"]').click()
    expect(tile.get_by_text(original_label, exact=True)).to_be_visible()
    page.locator('[data-test="header-redo"]').click()
    expect(tile.get_by_text(label, exact=True)).to_be_visible()
    save_dashboard(page, dashboard_api)
    edited = stored_dashboard(page, f"{base}{dashboard_api}")
    assert edited["revision"] == initial["revision"] + 1
    assert edited["document"]["nodes"][node_id]["props"]["label"] == label

    page.reload()
    expect(tile.get_by_text(label, exact=True)).to_be_visible()
    expect(tile.get_by_text(str(TOTAL), exact=True)).to_be_visible()
    verify_saved_history(page, edited["uuid"], label)
    publish_button = page.locator('[data-test="header-publish"]')
    expect(publish_button).to_have_text("Publish")
    with page.expect_response(
        lambda response: matches(response, "PUT", f"/api/v1/dashboard/{dashboard_id}")
    ) as publication:
        publish_button.click()
    response = publication.value
    assert response.ok, f"Publish Dashboard V2 HTTP {response.status}"
    assert response.json()["result"]["published"] is True
    expect(page.locator('[data-test="header-published"]')).to_have_text("Published")

    page.locator('[data-test="header-embed"]').click()
    page.locator(f'[data-test="embed-dashboard-save-{node_id}"]').click()
    embed_widget = page.get_by_role("dialog", name="Embed widget", exact=True)
    inline_snippet = embed_widget.locator('[data-test="embed-widget-inline-snippet"]')
    expect(inline_snippet).to_contain_text('"type": "dataset"')
    expect(inline_snippet).to_contain_text(f'"id": "{dataset_id}"')
    with page.expect_response(
        lambda response: matches(response, "POST", "/api/v1/widget/")
    ) as created:
        embed_widget.get_by_role("button", name="Save widget", exact=True).click()
    response = created.value
    assert response.ok, f"Save embed widget HTTP {response.status}"
    widget_id = response.json()["result"]["uuid"]
    expect(
        embed_widget.locator('[data-test="embed-widget-saved-snippet"]')
    ).to_contain_text(widget_id)
    embed_widget.get_by_role("button", name="Close", exact=True).last.click()
    dashboard_embed = page.get_by_role(
        "dialog", name="Embed this dashboard", exact=True
    )
    dashboard_embed.get_by_role("button", name="Close", exact=True).last.click()
    save_dashboard(page, dashboard_api)

    page.reload()
    expect(page.locator('[data-test="header-published"]')).to_have_text("Published")
    expect(tile.get_by_text(label, exact=True)).to_be_visible()
    reopened = stored_dashboard(page, f"{base}{dashboard_api}")
    assert reopened["published"] is True
    assert reopened["document"]["nodes"][node_id]["props"]["embedWidgetId"] == widget_id
    page.locator('[data-test="header-embed"]').click()
    expect(page.locator('[data-test="embed-dashboard-snippet"]')).to_contain_text(
        widget_id
    )
    print(
        f"PASS Dashboard V2 edit, history, publish, reopen, saved widget {widget_id}",
        flush=True,
    )
    return SavedWidget(widget_id, dataset_id, table, label)


def guest_token(
    page: Page,
    base: str,
    resource: Literal["dataset", "widget"],
    resource_id: str,
    dataset_id: int,
) -> str:
    """Mint a guest token bound to one resource and the fixture's North rows."""
    csrf = page.request.get(f"{base}/api/v1/security/csrf_token/")
    assert csrf.ok, f"Read Superset CSRF token HTTP {csrf.status}"
    token = page.request.post(
        f"{base}/api/v1/security/guest_token/",
        headers={"X-CSRFToken": csrf.json()["result"], "Referer": f"{base}/"},
        data={
            "user": {
                "username": "copilot-lifecycle-guest",
                "first_name": "Copilot",
                "last_name": "Lifecycle",
            },
            "resources": [{"type": resource, "id": resource_id}],
            "rls": [{"dataset": dataset_id, "clause": "region = 'North'"}],
        },
    )
    assert token.ok, f"Issue {resource} guest token HTTP {token.status}"
    return token.json()["token"]


def verify_embed(
    page: Page,
    base: str,
    widget_host: str,
    widget: SavedWidget,
    token: str = "",
    *,
    inline: bool = False,
) -> None:
    """Render the widget from the real SDK example using one auth mode."""
    mode = "guest inline" if inline else "guest saved" if token else "session saved"
    config = {
        "supersetUrl": base,
        "authMode": "guest" if token else "session",
        "savedWidgetIds": [] if inline else [widget.uuid],
        "table": widget.table,
        "datasetId": widget.dataset_id,
        "metric": METRIC,
        "metricColumn": "revenue",
        "category": "region",
        "filterColumn": "region",
        "categoryValues": ["North", "South"],
        "filterValues": ["North", "South"],
        "label": "order_date",
        "second": {
            "table": widget.table,
            "datasetId": widget.dataset_id,
            "metric": METRIC,
            "dimension": "region",
            "values": ["North", "South"],
        },
    }

    def configure_example(route: Route) -> None:
        """Inject only the fixture IDs discovered during this test run."""
        response = route.fetch()
        assert response.ok, f"Load SDK example config HTTP {response.status}"
        route.fulfill(
            response=response,
            body=f"{response.text()}\nObject.assign(config, {json.dumps(config)});\n",
        )

    def is_widget_query(response: Response) -> bool:
        """Identify data requested by the exact saved or inline widget."""
        if inline:
            return is_kpi_preview(response, widget.dataset_id)
        return (
            matches(response, "POST", WIDGET_DATA)
            and response.request.post_data_json.get("id") == widget.uuid
        )

    page.route(f"{widget_host}/src/config.ts*", configure_example)
    if token:
        # Serve the real, scoped token at the example host's existing broker
        # contract. Requests for widget definitions and data still hit Superset.
        page.route(
            f"{widget_host}/api/guest-token?*",
            lambda route: route.fulfill(
                status=200, content_type="text/plain", body=token
            ),
        )
    with page.expect_response(is_widget_query) as data:
        if inline:
            page.goto(widget_host)
        else:
            with page.expect_response(
                lambda response: matches(
                    response, "GET", f"/api/v1/widget/{widget.uuid}"
                )
            ) as saved:
                page.goto(widget_host)
            assert saved.value.ok, f"Read saved {mode} embed HTTP {saved.value.status}"
    assert data.value.ok, f"Query {mode} embed HTTP {data.value.status}"
    request_headers = data.value.request.all_headers()
    if token:
        assert request_headers.get("x-guesttoken") == token, (
            "No matching guest auth on widget query."
        )
        assert "cookie" not in request_headers, (
            "The guest widget query sent a session cookie."
        )
    else:
        assert "x-guesttoken" not in request_headers, (
            "The session widget used guest auth."
        )
        assert "cookie" in request_headers, (
            "The session widget did not send its login cookie."
        )
    result = data.value.json()["result"]
    expected_total = NORTH_TOTAL if token else TOTAL
    assert float(result["rows"][0][METRIC]) == expected_total
    section = page.get_by_role(
        "heading", name="Inline widgets" if inline else "Saved widgets", exact=True
    ).locator("xpath=ancestor::section[1]")
    expected_label = f"Total {METRIC}" if inline else widget.label
    tile = section.locator('[data-superset-widget="metric-tile"]').filter(
        has=page.get_by_text(expected_label, exact=True)
    )
    expect(tile.get_by_text(expected_label, exact=True)).to_be_visible()
    expect(tile.get_by_text(str(expected_total), exact=True)).to_be_visible()
    scope = f"dataset {widget.dataset_id}" if inline else widget.uuid
    print(
        f"PASS {mode} browser embed {scope} rendered revenue {expected_total}",
        flush=True,
    )


def verify_model_probe(page: Page, base: str, dataset_id: int) -> None:
    """Test one optional natural-language analysis of the synthetic fixture."""
    page.goto(f"{base}/explore/?datasource_type=table&datasource_id={dataset_id}")
    panel = open_chat(page)
    panel.get_by_role("textbox", name="Ask Copilot").fill(
        f"Analyze only the synthetic CSV dataset {dataset_id} on this page. "
        "Use get_dataset to verify it and aggregate_dataset with the saved "
        "sum_revenue metric grouped by region. Show the measured North and "
        "South totals in an A2UI table titled Revenue by region. "
        "Use whole numbers without currency symbols. Do not read any other dataset."
    )
    events = read_agui_run(
        page, panel.get_by_role("button", name="Send", exact=True), timeout=150_000
    )
    tool_names = {
        event.get("toolCallName")
        for event in events
        if event.get("type") == "TOOL_CALL_START"
    }
    assert {"get_dataset", "aggregate_dataset"} <= tool_names, (
        "The model did not verify the fixture through the dataset gateway."
    )
    table = panel.locator("[data-a2ui-surface]").filter(has_text="Revenue by region")
    expect(table.get_by_text("North", exact=True)).to_be_visible()
    expect(table.get_by_text(re.compile(r"^250(?:\.0+)?$"))).to_be_visible()
    expect(table.get_by_text("South", exact=True)).to_be_visible()
    expect(table.get_by_text(re.compile(r"^300(?:\.0+)?$"))).to_be_visible()
    print(
        "PASS optional model analysis, authorized aggregate and A2UI table", flush=True
    )


def verify_arabic_shell(page: Page, base: str) -> None:
    """Open the real Copilot extension in the Arabic fixture locale."""
    page.goto(f"{base}/lang/ar")
    page.goto(f"{base}/dashboard/list/")
    panel = open_chat(page, arabic=True)
    expect(panel).to_have_attribute("dir", "rtl")
    print("PASS Arabic Copilot shell, RTL direction and composer", flush=True)


def main() -> None:
    """Run the complete browser lifecycle against explicitly named local fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Disposable Superset origin")
    parser.add_argument(
        "--widget-host-url", required=True, help="Widget SDK example origin"
    )
    parser.add_argument("--username", default=os.getenv("NXTBI_E2E_ADMIN_USERNAME"))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--channel", help="Optional installed Chromium channel")
    parser.add_argument(
        "--artifact-dir", type=Path, help="Optional screenshot directory"
    )
    args = parser.parse_args()
    password = os.getenv("NXTBI_E2E_ADMIN_PASSWORD")
    if not args.username or not password:
        parser.error("Set NXTBI_E2E_ADMIN_USERNAME and NXTBI_E2E_ADMIN_PASSWORD.")
    base = args.base_url.rstrip("/")
    widget_host = args.widget_host_url.rstrip("/")
    origins = (urlsplit(base), urlsplit(widget_host))
    if (
        any(
            origin.scheme != "http"
            or origin.hostname not in {"127.0.0.1", "localhost"}
            or origin.username
            or origin.password
            or origin.path
            or origin.query
            or origin.fragment
            for origin in origins
        )
        or origins[0].hostname != origins[1].hostname
        or base == widget_host
    ):
        parser.error("Use separate local HTTP origins on the same loopback hostname.")

    if args.artifact_dir is not None:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)

    expect.set_options(timeout=TIMEOUT)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not args.headed, channel=args.channel
        )
        session = browser.new_context(viewport={"width": 1440, "height": 1000})
        session.set_default_timeout(TIMEOUT)
        owner = session.new_page()
        active_page: Page | None = None
        try:
            login(owner, base, args.username, password)
            active_page = owner
            title = f"Copilot lifecycle {uuid4().hex[:8]}"
            dashboard_id, dataset_id, table = create_draft(
                owner, base, title, args.artifact_dir
            )
            widget = edit_publish_and_save_widget(
                owner,
                base,
                dashboard_id,
                dataset_id,
                table,
            )
            active_page = session.new_page()
            verify_embed(active_page, base, widget_host, widget)
            token = guest_token(owner, base, "widget", widget.uuid, dataset_id)
            guest = browser.new_context(viewport={"width": 1440, "height": 1000})
            guest.set_default_timeout(TIMEOUT)
            assert not guest.cookies([base]), (
                "The guest browser inherited login cookies."
            )
            active_page = guest.new_page()
            verify_embed(active_page, base, widget_host, widget, token)
            inline_token = guest_token(
                owner, base, "dataset", str(dataset_id), dataset_id
            )
            active_page = guest.new_page()
            verify_embed(
                active_page, base, widget_host, widget, inline_token, inline=True
            )
            if os.getenv("NXTBI_E2E_MODEL_PROBE") == "1":
                active_page = session.new_page()
                verify_model_probe(active_page, base, dataset_id)
            arabic = browser.new_context(storage_state=session.storage_state())
            arabic.set_default_timeout(TIMEOUT)
            active_page = arabic.new_page()
            verify_arabic_shell(active_page, base)
        except Exception:
            if (
                args.artifact_dir is not None
                and active_page is not None
                and urlsplit(active_page.url).path.rstrip("/") != "/login"
            ):
                with suppress(Error):
                    active_page.screenshot(path=args.artifact_dir / "failure.png")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()

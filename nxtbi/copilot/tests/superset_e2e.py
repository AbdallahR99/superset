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
"""Verify NxtBI Copilot against the isolated Keycloak and GovAI deployment."""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - Standalone browser test uses the standard library.
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import (
    Browser,
    Error,
    expect,
    Page,
    Response,
    sync_playwright,
)

BASE = "http://localhost:18088"
KEYCLOAK = "http://localhost:18180"
ROOT = Path(__file__).resolve().parents[3]
APPROVE = "/api/v1/nxtbi_copilot/approve"
RUN = "/api/v1/nxtbi_copilot/run"
WIDGET_DATA = "/api/v1/widget/data"
WIDGET_CATALOG = "urn:nxtbi:superset-widgets:1.0"
TIMEOUT = 150_000


def response_matches(response: Response, path: str) -> bool:
    """Identify the documented Superset API call by method and path."""
    return response.request.method == "POST" and urlsplit(response.url).path == path


def keycloak_session(browser: Browser, username: str, password: str) -> Page:
    """Sign in through Keycloak and verify the resulting Superset principal."""
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    try:
        page.goto(f"{BASE}/login/")
        page.get_by_text("Keycloak", exact=False).first.click()
        page.wait_for_url(f"{KEYCLOAK}/realms/**", timeout=45_000)
        page.locator("#username").fill(username)
        page.locator("#password").fill(password)
        page.locator("#kc-login").click()
        page.wait_for_url(f"{BASE}/**", timeout=45_000)
    except Error:
        raise AssertionError(
            f"Keycloak browser sign-in failed for {username}."
        ) from None
    identity = page.request.get(f"{BASE}/api/v1/me/roles/")
    assert identity.ok, f"Superset session status {identity.status}"
    assert identity.json()["result"]["username"] == username
    return page


def dataset_id(page: Page, table: str) -> int | None:
    """Return the isolated demo dataset when visible to the browser session."""
    result = page.request.get(
        f"{BASE}/api/v1/dataset/",
        params={"q": f"(filters:!((col:table_name,opr:eq,value:{table})))"},
    )
    assert result.ok, f"Dataset list status {result.status}"
    return next(
        (
            item["id"]
            for item in result.json()["result"]
            if item["table_name"] == table and item.get("schema") == "nxtbi"
        ),
        None,
    )


def dashboard_matches(page: Page, title: str) -> list[int]:
    """Count only dashboards matching the unique acceptance-test fixture title."""
    result = page.request.get(
        f"{BASE}/api/v1/dashboard/",
        params={"q": f"(filters:!((col:dashboard_title,opr:eq,value:'{title}')))"},
    )
    assert result.ok, f"Dashboard list status {result.status}"
    return [
        item["id"]
        for item in result.json()["result"]
        if item["dashboard_title"] == title
    ]


def csrf_headers(page: Page) -> dict[str, str]:
    """Obtain the normal anti-CSRF header using the signed-in browser session."""
    response = page.request.get(f"{BASE}/api/v1/security/csrf_token/")
    assert response.ok, f"CSRF endpoint status {response.status}"
    return {"X-CSRFToken": response.json()["result"], "Referer": f"{BASE}/"}


def open_chat(page: Page, *, arabic: bool = False) -> None:
    """Open Superset's native chat trigger for the current language."""
    trigger = page.get_by_role(
        "button", name="مساعد NxtBI" if arabic else "NxtBI Copilot", exact=True
    )
    composer = page.get_by_role(
        "textbox", name="اسأل المساعد" if arabic else "Ask Copilot"
    )
    expect(composer.or_(trigger).first).to_be_visible(timeout=45_000)
    if not composer.is_visible():
        trigger.click()
    expect(composer).to_be_visible()


def send_prompt(
    page: Page, prompt: str, *, arabic: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Drive the real composer and parse the completed AG-UI response."""
    textbox = page.get_by_role(
        "textbox", name="اسأل المساعد" if arabic else "Ask Copilot"
    )
    textbox.fill(prompt)
    # Keep a copy of the wire events without replacing or buffering the live stream.
    # The SDK may release the original reader before Chromium emits requestfinished.
    page.evaluate(
        """path => {
            window.nxtbiE2eRun = undefined;
            if (window.nxtbiE2eObserver) return;
            window.nxtbiE2eObserver = true;
            const fetch = window.fetch.bind(window);
            window.fetch = async (input, init) => {
                const response = await fetch(input, init);
                const url = new URL(response.url, window.location.href);
                if (url.origin === location.origin && url.pathname === path) {
                    window.nxtbiE2eRun = response.clone().text();
                }
                return response;
            };
        }""",
        RUN,
    )
    send = page.get_by_role("button", name="إرسال" if arabic else "Send", exact=True)
    with page.expect_response(
        lambda response: response_matches(response, RUN), timeout=TIMEOUT
    ) as streamed:
        send.click()
    response = streamed.value
    assert response.status == 200, f"Copilot run HTTP {response.status}"
    assert "text/event-stream" in response.headers.get("content-type", "")
    expect(send).to_be_visible(timeout=TIMEOUT)
    data = page.evaluate(
        """() => Promise.race([
            window.nxtbiE2eRun,
            new Promise(resolve => setTimeout(() => resolve(''), 10000)),
        ])"""
    )
    assert data, "The browser did not capture the completed Copilot stream."
    events = [
        json.loads(line.removeprefix("data:").strip())
        for line in data.splitlines()
        if line.startswith("data:") and line.removeprefix("data:").strip() != "[DONE]"
    ]
    kinds = {event.get("type") for event in events}
    assert "RUN_ERROR" not in kinds, "Copilot returned a run error."
    assert {"RUN_STARTED", "RUN_FINISHED"} <= kinds, (
        f"Missing AG-UI run boundaries. Events: {sorted(str(kind) for kind in kinds)}"
    )
    body = response.request.post_data_json
    assert isinstance(body, dict)
    return body, events


def verify_proposal(page: Page, dataset: int, title: str) -> int:
    """Confirm live model output, Widget previews, explicit approval and retry."""
    page.goto(f"{BASE}/explore/?datasource_type=table&datasource_id={dataset}")
    open_chat(page)
    expect(page.locator("#nxtbi-copilot-panel")).to_have_attribute("dir", "ltr")
    dock = page.get_by_role("button", name="Dock", exact=True)
    dock.click()
    expect(page.get_by_role("button", name="Float", exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name="Ask Copilot")).to_be_visible()
    print(
        "PASS Keycloak Planning session, native English chat open and docked",
        flush=True,
    )

    assert dashboard_matches(page, title) == []
    previews: list[Response] = []
    page.on(
        "response",
        lambda response: (
            previews.append(response)
            if response_matches(response, WIDGET_DATA)
            else None
        ),
    )
    request, events = send_prompt(
        page,
        "Use get_dataset to verify my active budget_execution dataset. "
        "Then use propose_dashboard to draft Planning budget preview. "
        "Add a bar chart of execution_rate by sector_en and a metric tile "
        "of overall execution_rate, both from the checked dataset. "
        "Return the draft for review without saving it.",
    )
    assert {"description": "active_dataset_id", "value": str(dataset)} in request[
        "context"
    ]
    tool_names = {
        event.get("toolCallName")
        for event in events
        if event.get("type") == "TOOL_CALL_START"
    }
    assert {"get_dataset", "propose_dashboard"} <= tool_names, (
        f"Observed tools: {sorted(str(name) for name in tool_names)}"
    )
    draft = next(
        (
            event["value"]
            for event in events
            if event.get("type") == "CUSTOM"
            and event.get("name") == "nxtbi.dashboard-proposal"
        ),
        None,
    )
    assert draft, "The real agent stream did not include a verified dashboard proposal."
    metric_index = next(
        (
            index
            for index, item in enumerate(draft["widgets"])
            if item["type"] == "metric-tile"
        ),
        None,
    )
    assert metric_index is not None, (
        "The real proposal did not include the metric tile."
    )
    proposal = page.get_by_role("region", name="Dashboard proposal", exact=True)
    expect(proposal.get_by_role("combobox", name="Widget type").first).to_be_visible()
    expect(proposal.locator("canvas").first).to_be_visible(timeout=30_000)
    assert previews, "The Widget SDK did not request preview data."
    preview = previews[0]
    assert preview.status == 200, f"Widget preview HTTP {preview.status}"
    result = preview.json()["result"]
    assert result["rows"], "Widget preview returned no data."
    assert (
        preview.request.post_data_json["widget"]["props"]["dataBinding"]["datasetId"]
        == dataset
    )

    proposal.get_by_role("textbox", name="Dashboard title", exact=True).fill(title)
    widget_title = "Reviewed Budget Widget"
    proposal.locator("fieldset").nth(metric_index).get_by_role(
        "textbox", name="Widget title"
    ).fill(widget_title)
    expect(proposal.get_by_role("button", name="Refresh previews")).to_be_enabled()
    proposal.get_by_role("button", name="Refresh previews").click()
    print(
        "PASS GovAI tools, page context, live Widget REST 200, and editable proposal",
        flush=True,
    )

    approval_posts: list[int] = []
    page.on(
        "response",
        lambda response: (
            approval_posts.append(response.status)
            if response_matches(response, APPROVE)
            else None
        ),
    )
    proposal.get_by_role("button", name="Review and save", exact=True).click()
    expect(
        proposal.get_by_role("button", name="Save dashboard", exact=True)
    ).to_be_visible()
    assert approval_posts == []
    assert dashboard_matches(page, title) == []
    with page.expect_response(
        lambda response: response_matches(response, APPROVE)
    ) as approved:
        proposal.get_by_role("button", name="Save dashboard", exact=True).click()
    response = approved.value
    assert response.status == 201, f"Confirmed approval HTTP {response.status}"
    approved_body = response.request.post_data_json
    page.wait_for_url(re.compile(rf"{re.escape(BASE)}/dashboard/v2/[1-9]\d*/$"))
    dashboard_id = int(urlsplit(page.url).path.rstrip("/").rsplit("/", maxsplit=1)[1])
    expect(page.locator("[data-test='header-title']")).to_have_value(
        title, timeout=45_000
    )

    original = page.request.post(
        f"{BASE}{APPROVE}",
        data=approved_body,
        headers=csrf_headers(page),
    )
    assert original.status == 200, f"Idempotent approval HTTP {original.status}"
    assert original.json()["id"] == dashboard_id
    assert approval_posts == [201]
    assert dashboard_matches(page, title) == [dashboard_id]
    saved = page.request.get(f"{BASE}/api/v1/dashboard_v2/{dashboard_id}")
    assert saved.ok, f"Read saved Dashboard V2 HTTP {saved.status}"
    stored = saved.json()["result"]
    assert stored["dashboard_title"] == title
    assert stored["revision"] == 1
    assert any(
        node.get("props", {}).get("label") == widget_title
        for node in stored["document"]["nodes"].values()
    ), "Approved widget title edit was missing from the stored document."
    page.reload()
    expect(page.locator("[data-test='header-title']")).to_have_value(
        title, timeout=45_000
    )
    print(
        f"PASS approval 201, retry 200, one saved and reopened ({dashboard_id})",
        flush=True,
    )
    return dashboard_id


def verify_dashboard_action(page: Page, dashboard_id: int) -> None:
    """Follow the model's validated A2UI button with the signed-in user."""
    page.goto(f"{BASE}/dashboard/list/")
    open_chat(page)
    _, events = send_prompt(
        page,
        f"Use get_dashboard to verify that I can open dashboard ID {dashboard_id}. "
        "Use render_a2ui to show a button labelled Open reviewed dashboard "
        "with the nxtbi.open-dashboard event for that numeric dashboard ID.",
    )
    assert any(
        event.get("type") == "ACTIVITY_SNAPSHOT"
        and event.get("activityType") == "a2ui-surface"
        for event in events
    ), "The agent did not return the dashboard action surface."
    page.get_by_role("button", name="Open reviewed dashboard", exact=True).click()
    page.wait_for_url(f"{BASE}/dashboard/v2/{dashboard_id}/", timeout=45_000)
    print("PASS model-generated A2UI button opened the verified dashboard", flush=True)


def verify_saved_widget_surface(page: Page, dataset: int) -> None:
    """Render a model-authored layout containing an authorized saved widget."""
    label = f"Saved metric result {uuid4().hex[:10]}"
    created = page.request.post(
        f"{BASE}/api/v1/widget/",
        headers=csrf_headers(page),
        data={
            "widget_type": "metric-tile",
            "title": label,
            "props": {
                "dataBinding": {
                    "datasetId": dataset,
                    "metrics": ["execution_rate"],
                    "dimensions": [],
                    "rowLimit": 1,
                },
                "label": label,
            },
        },
    )
    assert created.status == 201, f"Saved widget fixture HTTP {created.status}"
    widget_id = created.json()["result"]["uuid"]
    widget_path = f"/api/v1/widget/{widget_id}"
    try:
        open_chat(page)
        widget_reads: list[int] = []
        preview_reads: list[int] = []

        def track(response: Response) -> None:
            if urlsplit(response.url).path == widget_path:
                widget_reads.append(response.status)
            elif response_matches(response, WIDGET_DATA):
                payload = response.request.post_data_json
                if isinstance(payload, dict) and payload.get("id") == widget_id:
                    preview_reads.append(response.status)

        page.on("response", track)
        _, events = send_prompt(
            page,
            "Use render_a2ui to build a Card with a Row of two children. "
            "Add plain Text Budget widget and a SupersetWidgetPreview whose "
            f"widgetId is {widget_id}. Use the saved UUID as provided.",
        )
        components = [
            component
            for event in events
            if event.get("type") == "ACTIVITY_SNAPSHOT"
            for operation in event.get("content", {}).get("a2ui_operations", [])
            for component in operation.get("updateComponents", {}).get("components", [])
        ]
        assert any(
            component.get("component") == "SupersetWidgetPreview"
            and component.get("@catalogId") == WIDGET_CATALOG
            and component.get("widgetId") == widget_id
            for component in components
        ), "The agent did not return the authorized saved-widget catalog leaf."
        expect(page.get_by_text(label, exact=True)).to_be_visible(timeout=30_000)
        assert 200 in widget_reads
        assert 200 in preview_reads
        print(
            "PASS A2UI catalog rendered saved Widget and data REST HTTP 200", flush=True
        )
    finally:
        removed = page.request.delete(
            f"{BASE}{widget_path}", headers=csrf_headers(page)
        )
        assert removed.ok, f"Saved widget fixture cleanup HTTP {removed.status}"


def verify_arabic(page: Page, dashboard_id: int) -> None:
    """Verify the Arabic shell, direction, and active dashboard on a live run."""
    page.goto(f"{BASE}/lang/ar")
    page.goto(f"{BASE}/dashboard/v2/{dashboard_id}/")
    open_chat(page, arabic=True)
    expect(page.locator("#nxtbi-copilot-panel")).to_have_attribute("dir", "rtl")
    request, events = send_prompt(
        page,
        "أجب برسالة ترحيب قصيرة باللغة العربية فقط، من دون استدعاء أي أدوات.",
        arabic=True,
    )
    assert {"description": "locale", "value": "ar"} in request["context"]
    assert {
        "description": "active_dashboard_id",
        "value": str(dashboard_id),
    } in request["context"]
    answer = "".join(str(event.get("delta", "")) for event in events)
    assert re.search(r"[\u0600-\u06ff]", answer), (
        "The live Arabic turn returned no Arabic text."
    )
    print(
        "PASS Arabic RTL native chat and contextual Arabic GovAI response", flush=True
    )


def verify_restricted(page: Page, dashboard_id: int) -> None:
    """Check ordinary tenant permission boundaries under a second Keycloak session."""
    assert dataset_id(page, "trade_flows") is not None
    assert dataset_id(page, "budget_execution") is None
    response = page.request.get(f"{BASE}/api/v1/dashboard_v2/{dashboard_id}")
    assert response.status in {403, 404}, f"Restricted dashboard HTTP {response.status}"
    page.goto(f"{BASE}/lang/en")
    page.goto(f"{BASE}/dashboard/list/")
    open_chat(page)
    _, events = send_prompt(
        page,
        "Use list_datasets to search for the exact table budget_execution. "
        "Use the tool result to tell me whether it is visible in my current session.",
    )
    reads = {
        event["toolCallId"]
        for event in events
        if event.get("type") == "TOOL_CALL_START"
        and event.get("toolCallName") == "list_datasets"
    }
    assert reads, (
        "The restricted user's agent did not use the requested dataset metadata tool."
    )
    results = [
        json.loads(event["content"])
        for event in events
        if event.get("type") == "TOOL_CALL_RESULT" and event.get("toolCallId") in reads
    ]
    assert results, "The restricted user's metadata tool returned no results."
    assert all(result == {"items": []} for result in results), (
        "The restricted user's scoped metadata response was not empty."
    )
    print(
        "PASS Statistics session cannot read the Planning dataset or dashboard",
        flush=True,
    )


def main() -> None:
    """Exercise the isolated session, preserving previously saved demo objects."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, default=ROOT / "nxtbi/out/stabilization/demo.env"
    )
    arguments = parser.parse_args()
    password = next(
        line.split("=", 1)[1].strip()
        for line in arguments.env_file.read_text(encoding="utf-8-sig").splitlines()
        if line.startswith("NXTBI_DEMO_USER_PASSWORD=")
    )
    assert password, "Missing isolated demo password."
    title = f"Copilot acceptance {uuid4().hex[:12]}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = keycloak_session(browser, "planning.admin@nxtbi.local", password)
        try:
            page.goto(f"{BASE}/lang/en")
            dataset = dataset_id(page, "budget_execution")
            assert dataset is not None, "The Planning demo dataset is required."
            dashboard = verify_proposal(page, dataset, title)
            verify_saved_widget_surface(page, dataset)
            verify_dashboard_action(page, dashboard)
            verify_arabic(page, dashboard)
            restricted = keycloak_session(browser, "stats.editor@nxtbi.local", password)
            verify_restricted(restricted, dashboard)
        finally:
            for fixture in dashboard_matches(page, title):
                removed = page.request.delete(
                    f"{BASE}/api/v1/dashboard/{fixture}", headers=csrf_headers(page)
                )
                assert removed.ok, f"Acceptance fixture cleanup HTTP {removed.status}"
            browser.close()


if __name__ == "__main__":
    main()

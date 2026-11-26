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

"""Publish bilingual Copilot V2 dashboards and render their widgets in the SDK."""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - standalone browser runner
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from browser_smoke import datasource_rows, LabApi, login, TIMEOUT, VIEW_NAME
from copilot_browser_smoke import (
    assert_amount,
    response_object,
    save_from_copilot,
    Scenario,
    SCENARIOS,
)
from playwright.sync_api import (
    Browser,
    Error,
    expect,
    Locator,
    Page,
    Response,
    Route,
    sync_playwright,
)

WIDGET_API = "/api/v1/widget"
V2_API = "/api/v1/dashboard_v2"
ROLE_API = "/api/v1/security/roles"
GUEST_TOKEN_CODE = re.compile(r"fetchGuestToken|resources\s*:|rls\s*:")
KPI = "metric-tile"
TABLE = "ag-grid-table"
WIDGETS = (KPI, TABLE)
LABELS = {
    "en": {
        "draft": "Draft",
        "published": "Published",
        "embed_dashboard": "Embed this dashboard",
        "embed_widget": "Embed widget",
        "save_widget": "Save widget",
        "close": "Close",
        "dimension": "Property type",
    },
    "ar": {
        "draft": "مسودة",
        "published": "منشورة",
        "embed_dashboard": "تضمين لوحة المعلومات هذه",
        "embed_widget": "تضمين عنصر الواجهة",
        "save_widget": "حفظ عنصر الواجهة",
        "close": "إغلاق",
        "dimension": "نوع العقار",
    },
}


def matches(response: Response, method: str, path: str) -> bool:
    """Identify one observed browser request by HTTP method and route."""
    return (
        response.request.method == method
        and urlsplit(response.url).path.rstrip("/") == path
    )


def stored_dashboard(page: Page, base: str, dashboard_id: int) -> dict[str, Any]:
    """Read the dashboard persisted by the Copilot or the builder UI."""
    response = page.request.get(f"{base}{V2_API}/{dashboard_id}")
    return response_object(response)["result"]


def kpi_text(page: Page, case: Scenario, props: dict[str, Any]) -> str:
    """Format the independent fixture total with the widget's display settings."""
    number = page.evaluate(
        """({value, decimals, percentage}) =>
            new Intl.NumberFormat(undefined, {
                style: percentage ? 'percent' : 'decimal',
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals,
            }).format(value)
        """,
        {
            "value": case.value,
            "decimals": props.get("decimals", 0),
            "percentage": props.get("percentage", False),
        },
    )
    return f"{props.get('prefix', '')}{number}{props.get('suffix', '')}"


def verify_widgets(
    page: Page,
    case: Scenario,
    tile: Locator,
    table: Locator,
    kpi_props: dict[str, Any],
) -> None:
    """Require the native Widget components to draw fixture data and captions."""
    titles = case.chart_titles(case.locale)
    expect(tile.get_by_text(titles["big_number_total"], exact=True)).to_be_visible()
    expect(
        tile.get_by_text(kpi_text(page, case, kpi_props), exact=True)
    ).to_be_visible()
    expect(
        table.get_by_role(
            "columnheader", name=LABELS[case.locale]["dimension"], exact=True
        )
    ).to_be_visible()
    expect(
        table.get_by_role("columnheader", name=titles["big_number_total"], exact=True)
    ).to_be_visible()
    for name, amount in case.rows.items():
        label = page.get_by_role("gridcell", name=name, exact=True)
        expect(table.get_by_role("gridcell", name=name, exact=True)).to_be_visible()
        if amount is not None:
            row = table.get_by_role("row").filter(has=label)
            value = row.locator(f'[role="gridcell"][col-id="{case.metric}"]')
            expect(value).to_be_visible()
            number = (
                value.inner_text().replace(",", "").replace("٬", "").replace("٫", ".")
            )
            assert_amount(float(number), amount)


def verify_binding(
    props: dict[str, Any], case: Scenario, widget_type: str, view_uuid: str
) -> None:
    """Check the dashboard and portable copies retain only the approved view."""
    binding = props["dataBinding"]
    assert binding["semanticViewId"] == view_uuid
    assert binding.get("datasetId") is None
    assert binding["metrics"] == [case.metric]
    dimensions = [] if widget_type == KPI else ["property_type"]
    assert binding.get("dimensions", []) == dimensions


def create_saved_widgets(
    page: Page,
    case: Scenario,
    nodes: dict[str, str],
    dashboard_id: int,
    view_uuid: str,
) -> dict[str, str]:
    """Use the dashboard and widget dialogs and persist the returned SDK IDs."""
    labels = LABELS[case.locale]
    page.locator('[data-test="header-embed"]').click()
    dashboard_dialog = page.get_by_role(
        "dialog", name=labels["embed_dashboard"], exact=True
    )
    saved_ids = {}
    for kind, node_id in nodes.items():
        dashboard_dialog.locator(
            f'[data-test="embed-dashboard-save-{node_id}"]'
        ).click()
        widget_dialog = page.get_by_role(
            "dialog", name=labels["embed_widget"], exact=True
        )
        if case.locale == "en":
            expect(
                widget_dialog.get_by_text(
                    "Viewers sign in to Superset to see this semantic widget.",
                    exact=True,
                )
            ).to_be_visible()
        with page.expect_response(
            lambda response: matches(response, "POST", WIDGET_API)
        ) as created:
            widget_dialog.get_by_role(
                "button", name=labels["save_widget"], exact=True
            ).click()
        widget = response_object(created.value)["result"]
        assert widget["widget_type"] == kind
        verify_binding(widget["props"], case, kind, view_uuid)
        saved_ids[kind] = widget["uuid"]
        saved_snippet = widget_dialog.locator(
            '[data-test="embed-widget-saved-snippet"]'
        )
        expect(saved_snippet).to_contain_text(f'<Widget id="{saved_ids[kind]}" />')
        expect(saved_snippet).not_to_contain_text(GUEST_TOKEN_CODE)
        inline_snippet = widget_dialog.locator(
            '[data-test="embed-widget-inline-snippet"]'
        )
        expect(inline_snippet).to_contain_text(f'"semanticViewId": "{view_uuid}"')
        expect(inline_snippet).not_to_contain_text(GUEST_TOKEN_CODE)
        widget_dialog.get_by_role(
            "button", name=labels["close"], exact=True
        ).last.click()
    expect(
        dashboard_dialog.locator('[data-test="embed-dashboard-session"]')
    ).to_be_visible()
    snippet = dashboard_dialog.locator('[data-test="embed-dashboard-snippet"]')
    expect(snippet).to_contain_text("<SupersetProvider")
    expect(snippet).to_contain_text(
        f'supersetDomain="{page.evaluate("location.origin")}"'
    )
    expect(snippet).not_to_contain_text(GUEST_TOKEN_CODE)
    for widget_uuid in saved_ids.values():
        expect(snippet).to_contain_text(f'<Widget id="{widget_uuid}" />')
    dashboard_dialog.get_by_role(
        "button", name=labels["close"], exact=True
    ).last.click()
    unsaved = page.locator('[data-test="header-unsaved"]')
    expect(unsaved).to_be_visible()
    with page.expect_response(
        lambda response: matches(response, "PUT", f"{V2_API}/{dashboard_id}")
    ) as saved:
        page.locator('[data-test="header-save"]').click()
    assert saved.value.ok, f"Save Dashboard V2 HTTP {saved.value.status}"
    expect(unsaved).to_have_count(0)
    return saved_ids


def publish_dashboard(
    page: Page,
    base: str,
    case: Scenario,
    dashboard_id: int,
    view_uuid: str,
    artifacts: Path,
) -> dict[str, str]:
    """Verify live draft content, publish explicitly, and reopen the saved widgets."""
    labels = LABELS[case.locale]
    status = page.locator('[data-test="header-published"]')
    current = stored_dashboard(page, base, dashboard_id)
    assert current["revision"] == 1
    assert current["published"] is False
    expect(page.locator("html")).to_have_attribute("dir", case.direction)
    expect(page.locator('[data-test="header-title"]')).to_have_text(
        case.dashboard_title(case.locale)
    )
    expect(status).to_have_text(labels["draft"])
    nodes = {
        node["type"]: node_id
        for node_id, node in current["document"]["nodes"].items()
        if node["type"] in WIDGETS
    }
    assert nodes.keys() == set(WIDGETS)
    for kind, node_id in nodes.items():
        verify_binding(
            current["document"]["nodes"][node_id]["props"], case, kind, view_uuid
        )
    tile = page.locator(f'[data-test="widget-content-{nodes[KPI]}"]')
    table = page.locator(f'[data-test="widget-content-{nodes[TABLE]}"]')
    kpi_props = current["document"]["nodes"][nodes[KPI]]["props"]
    verify_widgets(page, case, tile, table, kpi_props)

    with page.expect_response(
        lambda response: matches(response, "PUT", f"/api/v1/dashboard/{dashboard_id}")
    ) as publication:
        page.locator('[data-test="header-publish"]').click()
    assert response_object(publication.value)["result"]["published"] is True
    expect(status).to_have_text(labels["published"])
    saved_ids = create_saved_widgets(page, case, nodes, dashboard_id, view_uuid)
    page.reload()
    reopened = stored_dashboard(page, base, dashboard_id)
    assert reopened["published"] is True
    assert reopened["revision"] > current["revision"]
    for kind, node_id in nodes.items():
        props = reopened["document"]["nodes"][node_id]["props"]
        assert props["embedWidgetId"] == saved_ids[kind]
        verify_binding(props, case, kind, view_uuid)
    expect(status).to_have_text(labels["published"])
    verify_widgets(page, case, tile, table, kpi_props)
    page.screenshot(
        path=str(artifacts / f"copilot-semantic-v2-dashboard-{case.locale}.png")
    )
    print(
        f"PASS {case.locale} live Dashboard V2 draft, explicit publish, reload, "
        f"and two saved SDK widgets (dashboard {dashboard_id})",
        flush=True,
    )
    return saved_ids


@contextmanager
def sdk_fixture(
    page: Page, base: str, widget_host: str, saved_ids: dict[str, str]
) -> Iterator[None]:
    """Give the separately running SDK host the real endpoint and saved IDs."""
    config_path = f"{widget_host}/src/config.ts*"
    config = {
        "supersetUrl": base,
        "authMode": "session",
        "savedWidgetIds": list(saved_ids.values()),
    }

    def configure(route: Route) -> None:
        """Set only host configuration, leaving the real widget and data APIs intact."""
        response = route.fetch()
        assert response.ok, f"Load SDK example config HTTP {response.status}"
        route.fulfill(
            response=response,
            body=f"{response.text()}\nObject.assign(config, {json.dumps(config)});\n",
        )

    page.route(config_path, configure)
    try:
        yield
    finally:
        page.unroute(config_path, configure)


def render_sdk_host(
    page: Page,
    base: str,
    widget_host: str,
    case: Scenario,
    saved_ids: dict[str, str],
    view_uuid: str,
    artifacts: Path,
    *,
    viewer: bool = False,
) -> None:
    """Render both immutable definitions on the actual standalone SDK example."""

    def widget_query(response: Response, kind: str) -> bool:
        """Identify the data response for the widget just saved in the browser."""
        return (
            matches(response, "POST", f"{WIDGET_API}/data")
            and response.request.post_data_json.get("id") == saved_ids[kind]
        )

    with (
        sdk_fixture(page, base, widget_host, saved_ids),
        page.expect_response(lambda response: widget_query(response, KPI)) as kpi,
        page.expect_response(lambda response: widget_query(response, TABLE)) as table,
        page.expect_response(
            lambda response: matches(response, "GET", f"{WIDGET_API}/{saved_ids[KPI]}")
        ) as kpi_definition,
        page.expect_response(
            lambda response: matches(
                response, "GET", f"{WIDGET_API}/{saved_ids[TABLE]}"
            )
        ) as table_definition,
    ):
        page.goto(widget_host)

    kpi_data = response_object(kpi.value)["result"]
    table_data = response_object(table.value)["result"]
    kpi_props = response_object(kpi_definition.value)["result"]["props"]
    table_props = response_object(table_definition.value)["result"]["props"]

    for response in (kpi.value, table.value):
        headers = response.request.all_headers()
        assert "cookie" in headers, "The SDK did not send the signed-in session."
        assert "x-guesttoken" not in headers, "The SDK did not use session auth."
    assert kpi_data["columns"] == [case.metric]
    assert len(kpi_data["rows"]) == 1
    assert_amount(kpi_data["rows"][0][case.metric], case.value)
    assert set(table_data["columns"]) == {"property_type", case.metric}
    rows = {row["property_type"]: row[case.metric] for row in table_data["rows"]}
    assert len(rows) == len(table_data["rows"])
    assert rows.keys() == case.rows.keys()
    for name, value in case.rows.items():
        assert_amount(rows[name], value)

    verify_binding(kpi_props, case, KPI, view_uuid)
    verify_binding(table_props, case, TABLE, view_uuid)
    if case.locale == "ar":
        page.get_by_role("checkbox", name="العربية (RTL)", exact=True).check()
    expect(
        page.locator(f'[dir="{case.direction}"][lang="{case.locale}"]')
    ).to_be_visible()
    section = page.get_by_role("heading", name="Saved widgets", exact=True).locator(
        "xpath=ancestor::section[1]"
    )
    for kind in WIDGETS:
        expect(section.locator(f'[data-superset-widget="{kind}"]')).to_have_attribute(
            "dir", case.direction
        )
    verify_widgets(
        page,
        case,
        section.locator(f'[data-superset-widget="{KPI}"]'),
        section.locator(f'[data-superset-widget="{TABLE}"]'),
        kpi_props,
    )
    expect(section.locator("iframe")).to_have_count(0)
    audience = "-viewer" if viewer else ""
    section.screenshot(
        path=str(artifacts / f"copilot-semantic-v2-embed-{case.locale}{audience}.png")
    )
    print(
        f"PASS {case.locale}{audience} two live, session-authenticated SDK widgets on "
        "a separate origin with exact metric and breakdown data",
        flush=True,
    )


def verify_viewer_denied(
    page: Page,
    base: str,
    widget_host: str,
    dashboard_id: int,
    saved_ids: dict[str, str],
) -> None:
    """Follow the published links before granting the viewer access."""
    with page.expect_response(
        lambda response: matches(response, "GET", f"{V2_API}/{dashboard_id}")
    ) as document:
        page.goto(f"{base}/dashboard/v2/{dashboard_id}/")
    assert document.value.status in {403, 404}
    expect(page.locator('[data-test="dashboard-load-error"]')).to_be_visible()
    expect(page.locator('[data-test^="widget-content-"]')).to_have_count(0)
    with (
        sdk_fixture(page, base, widget_host, saved_ids),
        page.expect_response(
            lambda response: matches(response, "GET", f"{WIDGET_API}/{saved_ids[KPI]}")
        ) as kpi,
        page.expect_response(
            lambda response: matches(
                response, "GET", f"{WIDGET_API}/{saved_ids[TABLE]}"
            )
        ) as table,
    ):
        page.goto(widget_host)
    for definition in (kpi.value, table.value):
        assert definition.status in {403, 404}
        assert "cookie" in definition.request.all_headers()
    section = page.get_by_role("heading", name="Saved widgets", exact=True).locator(
        "xpath=ancestor::section[1]"
    )
    expect(section).to_be_visible()
    expect(section.locator("[data-superset-widget]")).to_have_count(0)
    print(
        f"PASS ungranted Gamma denied Dashboard V2 {dashboard_id} and both SDK widgets",
        flush=True,
    )


@contextmanager
def view_grant(
    admin_page: Page, base: str, view_id: int, user_id: int
) -> Iterator[None]:
    """Attach just this native semantic-view permission to the test viewer."""
    api = LabApi(admin_page, base)
    permissions = response_object(
        admin_page.request.get(
            f"{base}/api/v1/security/permissions-resources/",
            params={"q": f"(filters:!((col:view_menu.name,opr:ct,value:{VIEW_NAME})))"},
        )
    )["result"]
    suffix = f".[{VIEW_NAME}](id:{view_id})"
    matches_view = [
        permission["id"]
        for permission in permissions
        if permission["permission"]["name"] == "datasource_access"
        and permission["view_menu"]["name"].endswith(suffix)
    ]
    assert len(matches_view) == 1, "Expected one exact semantic-view permission."
    role = api.call("POST", f"{ROLE_API}/", payload={"name": "Lab Copilot View Reader"})
    role_path = f"{ROLE_API}/{role['id']}"
    try:
        api.call(
            "POST",
            f"{role_path}/permissions",
            payload={"permission_view_menu_ids": matches_view},
        )
        api.call("PUT", f"{role_path}/users", payload={"user_ids": [user_id]})
        yield
    finally:
        api.call("DELETE", role_path)


def verify_granted_dashboard(
    page: Page, base: str, case: Scenario, dashboard_id: int
) -> None:
    """Open the same published dashboard through the ordinary read-only UI."""
    page.goto(f"{base}/lang/{case.locale}")
    page.goto(f"{base}/dashboard/v2/{dashboard_id}/")
    saved = stored_dashboard(page, base, dashboard_id)
    assert saved["published"] is True
    assert saved["can_edit"] is False
    assert saved["can_publish"] is False
    expect(page.locator('[data-test="header-publish"]')).to_have_count(0)
    expect(page.locator("html")).to_have_attribute("dir", case.direction)
    expect(page.locator('[data-test="header-title"]')).to_have_text(
        case.dashboard_title(case.locale)
    )
    nodes = {
        node["type"]: node_id
        for node_id, node in saved["document"]["nodes"].items()
        if node["type"] in WIDGETS
    }
    tile = page.locator(f'[data-test="widget-content-{nodes[KPI]}"]')
    table = page.locator(f'[data-test="widget-content-{nodes[TABLE]}"]')
    kpi_props = saved["document"]["nodes"][nodes[KPI]]["props"]
    verify_widgets(page, case, tile, table, kpi_props)
    print(
        f"PASS {case.locale} granted Gamma read-only Dashboard V2 {dashboard_id}",
        flush=True,
    )


def verify_viewer_access(
    browser: Browser,
    admin_page: Page,
    base: str,
    widget_host: str,
    credentials: tuple[str, str],
    view: dict[str, Any],
    cases: list[tuple[Scenario, int, dict[str, str]]],
    artifacts: Path,
) -> None:
    """Compare isolated browser sessions before and after the exact view grant."""
    with browser.new_context(viewport={"width": 1440, "height": 1050}) as ungranted:
        ungranted.set_default_timeout(TIMEOUT)
        page = ungranted.new_page()
        login(page, base, *credentials)
        user_id = response_object(page.request.get(f"{base}/api/v1/me/"))["result"][
            "id"
        ]
        assert not any(
            row["uuid"] == view["uuid"] for row in datasource_rows(page, base)
        )
        for _, dashboard_id, saved_ids in cases:
            verify_viewer_denied(page, base, widget_host, dashboard_id, saved_ids)

    with (
        view_grant(admin_page, base, view["id"], user_id),
        browser.new_context(viewport={"width": 1440, "height": 1050}) as granted,
    ):
        granted.set_default_timeout(TIMEOUT)
        page = granted.new_page()
        login(page, base, *credentials)
        assert [row["uuid"] for row in datasource_rows(page, base)] == [view["uuid"]]
        for case, dashboard_id, saved_ids in cases:
            verify_granted_dashboard(page, base, case, dashboard_id)
            render_sdk_host(
                page,
                base,
                widget_host,
                case,
                saved_ids,
                view["uuid"],
                artifacts,
                viewer=True,
            )


def fixture_origin(url: str) -> bool:
    """Restrict the browser runner to the two disposable loopback hosts."""
    origin = urlsplit(url)
    return (
        origin.scheme == "http"
        and origin.hostname in {"localhost", "127.0.0.1"}
        and origin.port is not None
        and not any(
            (
                origin.username,
                origin.password,
                origin.path,
                origin.query,
                origin.fragment,
            )
        )
    )


def main() -> None:
    """Drive English and Arabic through the same build and SDK example."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--widget-host-url", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    widget_host = args.widget_host_url.rstrip("/")
    if (
        not fixture_origin(base)
        or not fixture_origin(widget_host)
        or urlsplit(base).hostname != urlsplit(widget_host).hostname
        or urlsplit(base).port == urlsplit(widget_host).port
    ):
        parser.error(
            "Expected two loopback HTTP origins on the same hostname "
            "and different ports."
        )
    username = os.environ.get("NXTBI_SEMANTIC_LAB_USER")
    password = os.environ.get("NXTBI_SEMANTIC_LAB_PASSWORD")
    viewer_username = os.environ.get("NXTBI_SEMANTIC_LAB_VIEWER")
    viewer_password = os.environ.get("NXTBI_SEMANTIC_LAB_VIEWER_PASSWORD")
    if not username or not password or not viewer_username or not viewer_password:
        parser.error("Set both the administrator and Gamma viewer lab credentials.")
    artifacts = args.artifact_dir
    artifacts.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
        page = context.new_page()
        page.set_default_timeout(TIMEOUT)
        expect.set_options(timeout=TIMEOUT)
        try:
            login(page, base, username, password)
            views = datasource_rows(page, base)
            assert len(views) == 1
            view_uuid = views[0]["uuid"]
            saved_cases: list[tuple[Scenario, int, dict[str, str]]] = []
            for case in SCENARIOS:
                dashboard_id = save_from_copilot(
                    page, base, case, artifacts, dashboard_type="v2"
                )
                saved = publish_dashboard(
                    page, base, case, dashboard_id, view_uuid, artifacts
                )
                render_sdk_host(
                    page, base, widget_host, case, saved, view_uuid, artifacts
                )
                saved_cases.append((case, dashboard_id, saved))
            verify_viewer_access(
                browser,
                page,
                base,
                widget_host,
                (viewer_username, viewer_password),
                views[0],
                saved_cases,
                artifacts,
            )
        except Exception:
            if not urlsplit(page.url).path.startswith("/login"):
                with suppress(Error):
                    page.screenshot(
                        path=str(artifacts / "copilot-semantic-v2-failure.png"),
                        timeout=5_000,
                    )
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()

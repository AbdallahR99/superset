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

"""Generate and save bilingual semantic dashboards through the real Copilot."""

from __future__ import annotations

import argparse
import json  # noqa: TID251 - standalone browser runner
import math
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from browser_smoke import CHART_API, DASHBOARD_API, datasource_rows, login, TIMEOUT
from playwright.sync_api import (
    APIResponse,
    Error,
    expect,
    Locator,
    Page,
    Request,
    Response,
    sync_playwright,
)

COPILOT_API = "/api/v1/nxtbi_copilot/semantic_catalog"
SELECTABLE_METRICS = ("average_transaction_price", "weighted_price_per_sqm")
CASE_NAMES = {
    "en": ("Average transaction price", "Price per square meter"),
    "ar": ("متوسط سعر المعاملة", "السعر لكل متر مربع"),
}


@dataclass(frozen=True)
class Scenario:
    """A language, an approved choice, and its independently computed totals."""

    locale: str
    direction: str
    trigger: str
    catalog: str
    input_label: str
    phrase: str
    generate: str
    save: str
    saved: str
    reopen: str
    metric_index: int
    value: float
    rows: dict[str, float | None]

    @property
    def metric(self) -> str:
        """Return the stable approved ID the native charts should retain."""
        return SELECTABLE_METRICS[self.metric_index]

    def dashboard_title(self, locale: str) -> str:
        """Return the expected localized dashboard title from the fixture."""
        subject = "Property Market" if locale == "en" else "سوق العقارات"
        return f"{subject} · {CASE_NAMES[locale][self.metric_index]}"

    def chart_titles(self, locale: str) -> dict[str, str]:
        """Return the localized titles of the native KPI and breakdown."""
        label = CASE_NAMES[locale][self.metric_index]
        suffix = "by property type" if locale == "en" else "حسب نوع العقار"
        return {"big_number_total": label, "table": f"{label} {suffix}"}


SCENARIOS = (
    Scenario(
        "en",
        "ltr",
        "NxtBI Copilot",
        "Semantic catalog",
        "Metric or dashboard request",
        "Create a dashboard for average property price",
        "Generate draft",
        "Save dashboard",
        "Dashboard saved.",
        "Open dashboard",
        0,
        400_000,
        {"Apartment": 380_000, "Villa": 570_000, "Unknown": 120_000},
    ),
    Scenario(
        "ar",
        "rtl",
        "مساعد NxtBI",
        "الكتالوج الدلالي",
        "المقياس أو طلب لوحة المعلومات",
        "أنشئ لوحة معلومات عن متوسط سعر العقار",
        "إنشاء مسودة",
        "حفظ لوحة المعلومات",
        "تم حفظ لوحة المعلومات.",
        "فتح لوحة المعلومات",
        1,
        2_280_000 / 610,
        {"Apartment": 6_000, "Villa": 1_140_000 / 420, "Unknown": None},
    ),
)


def response_object(response: APIResponse | Response) -> dict[str, Any]:
    """Require a successful JSON envelope without printing approval credentials."""
    assert response.ok, f"HTTP {response.status} for {urlsplit(response.url).path}"
    body = response.json()
    assert isinstance(body, dict), "Expected an object in the JSON response."
    return body


def posts_to(response: Response, path: str) -> bool:
    """Identify a response to the UI's ordinary authoring request."""
    return (
        response.request.method == "POST"
        and urlsplit(response.url).path.rstrip("/") == path
    )


def assert_amount(actual: object, expected: float | None) -> None:
    """Check values before display rounding and keep missing values distinct."""
    if expected is None:
        assert actual is None
    else:
        assert isinstance(actual, (int, float))
        assert not isinstance(actual, bool)
        assert math.isclose(actual, expected, rel_tol=1e-9)


def display_amount(page: Page, locale: str, value: float | None) -> str:
    """Resolve the expected preview display in the active browser locale."""
    if value is None:
        return "غير متاح" if locale == "ar" else "Unavailable"
    return page.evaluate(
        "({locale, value}) => "
        "new Intl.NumberFormat(locale, {maximumFractionDigits: 2}).format(value)",
        {"locale": locale, "value": value},
    )


def open_catalog(page: Page, base: str, case: Scenario) -> Locator:
    """Switch Superset's locale and open the installed Copilot authoring tool."""
    page.goto(f"{base}/lang/{case.locale}")
    page.goto(f"{base}/dashboard/list/")
    expect(page.locator("html")).to_have_attribute("dir", case.direction)
    trigger = page.get_by_role("button", name=case.trigger, exact=True)
    expect(trigger).to_be_visible()
    if trigger.get_attribute("aria-expanded") != "true":
        trigger.click()
    panel = page.locator("#nxtbi-copilot-panel")
    tool = panel.locator('[data-test="semantic-catalog-draft"]')
    expect(tool).to_have_attribute("lang", case.locale)
    expect(tool).to_have_attribute("dir", case.direction)
    tool.get_by_text(case.catalog, exact=True).click()
    expect(tool.get_by_role("textbox", name=case.input_label)).to_be_visible()
    return tool


def save_from_copilot(
    page: Page, base: str, case: Scenario, artifacts: Path | None
) -> int:
    """Clarify a real bilingual request, preview results, and approve it in the UI."""
    tool = open_catalog(page, base, case)
    tool.get_by_role("textbox", name=case.input_label).fill(case.phrase)
    generate = tool.get_by_role("button", name=case.generate, exact=True)
    save = tool.get_by_role("button", name=case.save, exact=True)

    with page.expect_response(
        lambda response: posts_to(response, f"{COPILOT_API}/draft")
    ) as ambiguous:
        generate.click()
    lookup = response_object(ambiguous.value)
    assert lookup["status"] == "ambiguous"
    candidates = {metric["metricId"]: metric for metric in lookup["candidates"]}
    assert set(candidates) == set(SELECTABLE_METRICS)
    assert {metric["unit"] for metric in candidates.values()} == {"AED", "AED/m²"}
    for name, metric_id in zip(
        CASE_NAMES[case.locale], SELECTABLE_METRICS, strict=True
    ):
        expect(tool.get_by_role("radio", name=name, exact=True)).to_be_visible()
        expect(tool.get_by_text(candidates[metric_id]["definition"])).to_be_visible()
    expect(save).to_have_count(0)

    tool.get_by_role(
        "radio", name=CASE_NAMES[case.locale][case.metric_index], exact=True
    ).check()
    with page.expect_response(
        lambda response: posts_to(response, f"{COPILOT_API}/draft")
    ) as staged:
        generate.click()
    draft = response_object(staged.value)
    assert draft["status"] == "draft"
    assert draft["metric"] == candidates[case.metric]
    assert draft["title"] == case.dashboard_title(case.locale)
    assert_amount(draft["value"], case.value)
    preview_rows = {row["label"]: row["value"] for row in draft["rows"]}
    assert preview_rows.keys() == case.rows.keys()
    preview = tool.get_by_role("region", name=draft["title"], exact=True)
    expect(
        preview.get_by_text(display_amount(page, case.locale, case.value), exact=True)
    ).to_be_visible()
    for label, value in case.rows.items():
        assert_amount(preview_rows[label], value)
        row = preview.get_by_role("row").filter(
            has=page.get_by_role("rowheader", name=label, exact=True)
        )
        expect(
            row.get_by_text(display_amount(page, case.locale, value), exact=True)
        ).to_be_visible()
    if artifacts:
        page.screenshot(
            path=str(artifacts / f"copilot-semantic-draft-{case.locale}.png")
        )

    with page.expect_response(
        lambda response: posts_to(response, f"{COPILOT_API}/approve")
    ) as approval:
        save.click()
    assert approval.value.status == 201
    saved = response_object(approval.value)
    dashboard_id = saved["id"]
    assert isinstance(dashboard_id, int)
    assert dashboard_id > 0
    path = f"/dashboard/{dashboard_id}/"
    assert saved["url"] == path
    expect(tool.get_by_text(case.saved, exact=True)).to_be_visible()
    link = tool.get_by_role("link", name=case.reopen, exact=True)
    expect(link).to_have_attribute("href", f"{base}{path}")
    link.click()
    expect(page).to_have_url(f"{base}{path}")
    print(
        f"PASS {case.locale} Copilot clarification, exact preview, and approval",
        flush=True,
    )
    return dashboard_id


def is_chart_response(response: Response, chart_id: int) -> bool:
    """Identify one of the saved charts, independent of request order."""
    if not posts_to(response, f"{CHART_API}data"):
        return False
    form_data = parse_qs(urlsplit(response.url).query).get("form_data", ["{}"])[0]
    return json.loads(form_data).get("slice_id") == chart_id


def verify_stored_dashboard(
    page: Page, base: str, case: Scenario, dashboard_id: int, view_id: int
) -> dict[str, int]:
    """Verify the saved dashboard, translations and native semantic bindings."""
    path = f"{base}{DASHBOARD_API}{dashboard_id}"
    stored = response_object(page.request.get(path))["result"]
    source_title = case.dashboard_title(case.locale)
    assert stored["dashboard_title"] == source_title
    assert stored["localized_title"] == source_title
    assert stored["published"] is False
    localization = json.loads(stored["json_metadata"])["nxtbi_localization"]
    assert localization["sourceLocale"] == case.locale
    assert localization["title"] == {
        "source": source_title,
        "translations": {locale: case.dashboard_title(locale) for locale in CASE_NAMES},
    }

    charts = response_object(page.request.get(f"{path}/charts"))["result"]
    assert len(charts) == 2
    chart_ids = {}
    for entry in charts:
        chart_id = entry["id"]
        chart = response_object(page.request.get(f"{base}{CHART_API}{chart_id}"))[
            "result"
        ]
        viz = chart["viz_type"]
        assert chart["datasource_type"] == "semantic_view"
        assert chart["datasource_id"] == view_id
        expected_title = case.chart_titles(case.locale)[viz]
        assert chart["slice_name"] == expected_title
        assert localization["widgets"][str(chart_id)] == {
            "source": expected_title,
            "translations": {
                locale: case.chart_titles(locale)[viz] for locale in CASE_NAMES
            },
        }
        form = entry["form_data"]
        assert form["datasource"] == f"{view_id}__semantic_view"
        if viz == "table":
            assert form["metrics"] == [case.metric]
            assert form["groupby"] == ["property_type"]
            assert form["column_config"] == {
                "property_type": {
                    "customColumnName": "Property type"
                    if case.locale == "en"
                    else "نوع العقار",
                },
                case.metric: {
                    "customColumnName": CASE_NAMES[case.locale][case.metric_index],
                },
            }
        else:
            assert form["metric"] == case.metric
        chart_ids[viz] = chart_id
    assert set(chart_ids) == {"big_number_total", "table"}
    return chart_ids


def verify_reopened_dashboard(
    page: Page,
    case: Scenario,
    chart_ids: dict[str, int],
    artifacts: Path | None,
    *,
    locale: str | None = None,
    url: str | None = None,
) -> None:
    """Open the saved dashboard and verify its rendered native queries."""
    viewer_locale = locale or case.locale
    direction = "rtl" if viewer_locale == "ar" else "ltr"
    kpi_id = chart_ids["big_number_total"]
    table_id = chart_ids["table"]
    with (
        page.expect_response(
            lambda response: is_chart_response(response, kpi_id)
        ) as kpi,
        page.expect_response(
            lambda response: is_chart_response(response, table_id)
        ) as table,
    ):
        if url:
            page.goto(url)
        else:
            page.reload()

    expect(page.locator("html")).to_have_attribute("dir", direction)
    expect(
        page.locator('[data-test="dashboard-header-container"]').get_by_text(
            case.dashboard_title(viewer_locale), exact=True
        )
    ).to_be_visible()
    for viz, chart_id in chart_ids.items():
        chart = page.locator(f'[data-test-chart-id="{chart_id}"]')
        expect(
            chart.locator('[data-test="slice-header"]').get_by_text(
                case.chart_titles(viewer_locale)[viz], exact=True
            )
        ).to_be_visible()

    kpi_rows = response_object(kpi.value)["result"][0]["data"]
    assert len(kpi_rows) == 1
    assert_amount(kpi_rows[0][case.metric], case.value)
    table_rows = response_object(table.value)["result"][0]["data"]
    by_type = {row["property_type"]: row[case.metric] for row in table_rows}
    table_view = page.locator(f'[data-test-chart-id="{table_id}"]')
    dimension_label = "Property type" if case.locale == "en" else "نوع العقار"
    header_row = table_view.get_by_role("row").filter(has_text=dimension_label)
    expect(header_row.get_by_text(dimension_label, exact=True)).to_be_visible()
    expect(
        header_row.get_by_text(CASE_NAMES[case.locale][case.metric_index], exact=True)
    ).to_be_visible()
    assert by_type.keys() == case.rows.keys()
    for label, value in case.rows.items():
        assert_amount(by_type[label], value)
        expect(table_view.get_by_text(label, exact=True)).to_be_visible()
    if artifacts:
        suffix = case.locale if locale is None else f"{case.locale}-in-{locale}"
        page.screenshot(
            path=str(artifacts / f"copilot-semantic-dashboard-{suffix}.png")
        )
    print(
        f"PASS {case.locale} dashboard in {viewer_locale} with live data and captions",
        flush=True,
    )


def _extension_resource(url: str) -> str | None:
    """Keep only the extension route and known Copilot assets."""
    path = urlsplit(url).path
    if path.rstrip("/") == "/api/v1/extensions":
        return "extensions list"
    if "/api/v1/extensions/nxtbi/ai-copilot/" in path:
        return path.rsplit("/", 1)[-1]
    if path.rstrip("/") == COPILOT_API:
        return "semantic catalog availability"
    return None


def watch_extension_startup(page: Page) -> list[str]:
    """Collect known extension resource and loader status without response bodies."""
    events: list[str] = []
    diagnostics = {
        "failed to initialize extension": "extension initialization failed",
        "error setting up extensions": "extension list initialization failed",
        "loading chunk": "extension chunk load failed",
        "script external load error": "extension remote script load failed",
        "module not found": "extension module unavailable",
        "cannot read properties": "undefined property in JavaScript",
        "is not a function": "unexpected JavaScript API",
    }

    def note(message: str) -> None:
        """Keep the report short and deduplicate each observation."""
        if message not in events and len(events) < 30:
            events.append(message)

    def observe_response(response: Response) -> None:
        """Record only route labels and HTTP status."""
        if name := _extension_resource(response.url):
            note(f"{name} HTTP {response.status}")

    def observe_failure(request: Request) -> None:
        """Record that an extension resource failed to load."""
        if name := _extension_resource(request.url):
            note(f"{name} request failed")

    def observe_error(message: str) -> None:
        """Classify selected load errors without retaining their text."""
        lowered = message.lower()
        for kind, label in diagnostics.items():
            if kind in lowered:
                note(label)

    page.on("response", observe_response)
    page.on("requestfailed", observe_failure)
    page.on(
        "console",
        lambda entry: observe_error(entry.text) if entry.type == "error" else None,
    )
    page.on("pageerror", lambda error: observe_error(error.message))
    return events


def report_extension_failure(
    page: Page, base: str, status: list[str], artifacts: Path | None
) -> None:
    """Save a redacted startup diagnostic report for fixture failures."""
    try:
        response = page.request.get(f"{base}/api/v1/extensions/", timeout=5_000)
        status.append(f"extension inventory HTTP {response.status}")
        if response.ok:
            extensions = {
                entry["id"]: bool(entry.get("remoteEntry"))
                for entry in response.json()["result"]
            }
            for name in ("nxtbi.ai-copilot", "nxtbi.property-market-lab"):
                state = (
                    "frontend registered"
                    if extensions.get(name)
                    else "backend only"
                    if name in extensions
                    else "absent"
                )
                status.append(f"{name} {state}")
    except (Error, KeyError, TypeError, ValueError):
        status.append("extension inventory unavailable")
    report = "\n".join(status) + "\n"
    print(report, end="", flush=True)
    if artifacts:
        (artifacts / "copilot-semantic-diagnostics.txt").write_text(
            report, encoding="utf-8"
        )
        if not urlsplit(page.url).path.startswith("/login"):
            with suppress(Error):
                page.screenshot(
                    path=str(artifacts / "copilot-semantic-failure.png"),
                    timeout=5_000,
                )


def main() -> None:
    """Drive the same disposable environment in both supported locales."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    origin = urlsplit(base)
    if (
        origin.scheme != "http"
        or origin.hostname not in {"localhost", "127.0.0.1"}
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
        or not origin.port
    ):
        parser.error("Use the isolated Superset lab HTTP origin on a loopback port.")
    username = os.environ.get("NXTBI_SEMANTIC_LAB_USER")
    password = os.environ.get("NXTBI_SEMANTIC_LAB_PASSWORD")
    if not username or not password:
        parser.error("The lab harness must supply the browser credentials.")
    if args.artifact_dir:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)

    expect.set_options(timeout=TIMEOUT)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        extension_status = watch_extension_startup(page)
        try:
            page.set_default_timeout(TIMEOUT)
            login(page, base, username, password)
            views = datasource_rows(page, base)
            assert len(views) == 1, "Provision one property-market semantic view first."
            view_id = views[0]["id"]
            dashboard_ids = set()
            for case in SCENARIOS:
                dashboard_id = save_from_copilot(page, base, case, args.artifact_dir)
                assert dashboard_id not in dashboard_ids
                dashboard_ids.add(dashboard_id)
                charts = verify_stored_dashboard(
                    page, base, case, dashboard_id, view_id
                )
                verify_reopened_dashboard(page, case, charts, args.artifact_dir)
                if case.locale == "ar":
                    page.goto(f"{base}/lang/en")
                    verify_reopened_dashboard(
                        page,
                        case,
                        charts,
                        args.artifact_dir,
                        locale="en",
                        url=f"{base}/dashboard/{dashboard_id}/",
                    )
        except (AssertionError, Error, KeyError):
            report_extension_failure(page, base, extension_status, args.artifact_dir)
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()

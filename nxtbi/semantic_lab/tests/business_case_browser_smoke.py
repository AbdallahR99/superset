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


"""Verify a complex authored property-market recipe in native V2 and the SDK."""

from __future__ import annotations

import argparse
import os
from contextlib import suppress
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from browser_smoke import datasource_rows, LabApi, login, METRICS, TIMEOUT
from copilot_browser_smoke import assert_amount, response_object
from copilot_v2_browser_smoke import (
    fixture_origin,
    KPI,
    LABELS,
    matches,
    sdk_fixture,
    stored_dashboard,
    TABLE,
    V2_API,
    WIDGET_API,
)
from playwright.sync_api import Error, expect, Locator, Page, sync_playwright

SALE = "sale_date"
REGISTRATION = "registration_date"
PROPERTY_TYPE = "property_type"
TOTALS = dict(zip(METRICS, (6, 400_000, 2_280_000 / 610, 4), strict=True))
TABLE_METRICS = METRICS[:3]

# Each dated row is distinct in this fixture. One orphan keeps its sale and
# transaction price but has no area, so its area-weighted metric is missing.
DEALS = (
    ("2026-01-05", "2026-01-10", "Apartment", 300_000, 6_000),
    ("2026-01-20", "2026-02-02", "Apartment", 360_000, 6_000),
    ("2026-02-04", "2026-02-10", "Villa", 900_000, 3_000),
    ("2026-02-27", "2026-03-02", "Apartment", 480_000, 6_000),
    ("2026-03-12", "2026-03-18", "Unknown", 120_000, None),
    ("2026-03-20", "2026-04-01", "Villa", 240_000, 2_000),
)
CAPTIONS = {
    "en": {
        "root": "Property market · sales and registration",
        SALE: "Sales dates and property mix",
        REGISTRATION: "Registration dates and property mix",
        f"{SALE}_column": "Sale date",
        f"{REGISTRATION}_column": "Registration date",
        PROPERTY_TYPE: "Property type",
        "transaction_count": "Transactions",
        "average_transaction_price": "Average transaction price",
        "weighted_price_per_sqm": "Area-weighted price per m²",
        "distinct_property_count": "Distinct properties",
    },
    "ar": {
        "root": "سوق العقارات · المبيعات والتسجيل",
        SALE: "تواريخ البيع ومزيج العقارات",
        REGISTRATION: "تواريخ التسجيل ومزيج العقارات",
        f"{SALE}_column": "تاريخ البيع",
        f"{REGISTRATION}_column": "تاريخ التسجيل",
        PROPERTY_TYPE: "نوع العقار",
        "transaction_count": "المعاملات",
        "average_transaction_price": "متوسط سعر المعاملة",
        "weighted_price_per_sqm": "السعر المرجح بالمساحة لكل متر مربع",
        "distinct_property_count": "العقارات الفريدة",
    },
}


def authored_document(view_uuid: str, locale: str) -> dict[str, Any]:
    """Bind the independent QA recipe to the lab's approved semantic members."""
    labels = CAPTIONS[locale]

    def caption(node_id: str) -> dict[str, Any]:
        """Translate presentation only; stable field IDs drive every query."""
        return {
            "source": labels[node_id],
            "translations": {
                language: strings[node_id] for language, strings in CAPTIONS.items()
            },
        }

    def binding(
        metrics: tuple[str, ...], dimensions: tuple[str, ...] = ()
    ) -> dict[str, Any]:
        """Use bounded native semantic data requests with stable dimensions."""
        return {
            "semanticViewId": view_uuid,
            "metrics": list(metrics),
            "dimensions": list(dimensions),
            "rowLimit": 40 if dimensions else 1,
        }

    children = [*METRICS, SALE, REGISTRATION]
    nodes: dict[str, Any] = {
        "root": {
            "type": "grid",
            "layout": {"columns": 24},
            "children": children,
            "props": {
                "nxtbiLocalization": {
                    "sourceLocale": locale,
                    "title": caption("root"),
                    "widgets": {node_id: caption(node_id) for node_id in children},
                }
            },
        }
    }
    for metric in METRICS:
        nodes[metric] = {
            "type": KPI,
            "layout": {"colSpan": 6, "rowSpan": 5},
            "props": {
                "label": labels[metric],
                "decimals": 2 if metric == "weighted_price_per_sqm" else 0,
                "dataBinding": binding((metric,)),
            },
        }
    for date_role in (SALE, REGISTRATION):
        dimensions = (date_role, PROPERTY_TYPE)
        nodes[date_role] = {
            "type": TABLE,
            "layout": {"colSpan": 24, "rowSpan": 11},
            "props": {
                "label": labels[date_role],
                "dataBinding": binding(TABLE_METRICS, dimensions),
                "columnDefs": [
                    {
                        "field": field,
                        "headerName": labels[
                            f"{field}_column" if field == date_role else field
                        ],
                        "minWidth": 116,
                        "flex": 1,
                    }
                    for field in (*dimensions, *TABLE_METRICS)
                ],
            },
        }
    return {"version": 1, "root": "root", "nodes": nodes}


def expect_direction(page: Page, locale: str) -> None:
    """Prove the Superset shell direction for this localized recipe."""
    expect(page.locator("html")).to_have_attribute(
        "dir", "rtl" if locale == "ar" else "ltr"
    )


def normalize_day(value: Any) -> str:
    """Normalize Superset's date-column JSON or DOM representation."""
    if isinstance(value, (int, float)) or str(value).isdigit():
        return (
            datetime.fromtimestamp(float(value) / 1_000, timezone.utc)
            .date()
            .isoformat()
        )
    return date.fromisoformat(str(value)[:10]).isoformat()


def expected_rows(date_role: str) -> dict[tuple[str, str], tuple[int, int, int | None]]:
    """Derive the independent per-date expected values from the six-row fixture."""
    return {
        (sale if date_role == SALE else registered, property_type): (1, price, weighted)
        for sale, registered, property_type, price, weighted in DEALS
    }


def verify_rows(
    rows: list[dict[str, Any]],
    date_role: str,
    *,
    april: bool = False,
) -> None:
    """Compare keyed rows without assuming the server's ordering."""
    expected = expected_rows(date_role)
    if april:
        expected = {
            key: values
            for key, values in expected.items()
            if key[0].startswith("2026-04-")
        }
    actual = {(normalize_day(row[date_role]), row[PROPERTY_TYPE]): row for row in rows}
    assert len(actual) == len(rows)
    assert actual.keys() == expected.keys()
    for key, values in expected.items():
        for metric, value in zip(TABLE_METRICS, values, strict=True):
            assert_amount(actual[key][metric], value)


def verify_table(table: Locator, locale: str, date_role: str) -> None:
    """Compare the real rendered grid with the approved bilingual business case."""
    captions = CAPTIONS[locale]
    expect(
        table.get_by_role(
            "columnheader", name=captions[f"{date_role}_column"], exact=True
        )
    ).to_be_visible()
    for field in (PROPERTY_TYPE, *TABLE_METRICS):
        expect(
            table.get_by_role("columnheader", name=captions[field], exact=True)
        ).to_be_visible()
    date_cells = table.locator(f'[role="gridcell"][col-id="{date_role}"]')
    expected = expected_rows(date_role)
    expect(date_cells).to_have_count(len(expected))
    visible: dict[tuple[str, str], tuple[float, ...]] = {}
    for date_cell in date_cells.all():
        row = date_cell.locator('xpath=ancestor::*[@role="row"][1]')
        key = (
            normalize_day(date_cell.inner_text()),
            row.locator(f'[role="gridcell"][col-id="{PROPERTY_TYPE}"]').inner_text(),
        )
        assert key not in visible
        visible[key] = tuple(
            float(
                row.locator(f'[role="gridcell"][col-id="{field}"]')
                .inner_text()
                .replace(",", "")
                .replace("٬", "")
                .replace("٫", ".")
            )
            for field, amount in zip(TABLE_METRICS, expected[key], strict=True)
            if amount is not None
        )
    assert visible.keys() == expected.keys()
    for key, values in expected.items():
        for value, amount in zip(
            visible[key], (value for value in values if value is not None), strict=True
        ):
            assert_amount(value, amount)


def verify_dashboard(page: Page, locale: str, *, published: bool) -> None:
    """Require all KPI and table widgets to render on the native dashboard."""
    expect_direction(page, locale)
    captions = CAPTIONS[locale]
    expect(page.locator('[data-test="header-title"]')).to_have_text(captions["root"])
    status = "published" if published else "draft"
    expect(page.locator('[data-test="header-published"]')).to_have_text(
        LABELS[locale][status]
    )
    for metric, value in TOTALS.items():
        tile = page.locator(f'[data-test="widget-content-{metric}"]')
        expect(tile.get_by_text(captions[metric], exact=True)).to_be_visible()
        amount = page.evaluate(
            """({ value, digits }) => new Intl.NumberFormat(undefined, {
                 minimumFractionDigits: digits, maximumFractionDigits: digits
             }).format(value)""",
            {"value": value, "digits": 2 if metric == "weighted_price_per_sqm" else 0},
        )
        expect(tile.get_by_text(amount, exact=True)).to_be_visible()
    for date_role in (SALE, REGISTRATION):
        table = page.locator(f'[data-test="widget-content-{date_role}"]')
        verify_table(table, locale, date_role)


def save_registration_embed(page: Page, dashboard_id: int, locale: str) -> str:
    """Create the real SDK object from V2 and save its dashboard reference."""
    labels = LABELS[locale]
    page.locator('[data-test="header-embed"]').click()
    dialog = page.get_by_role("dialog", name=labels["embed_dashboard"], exact=True)
    dialog.locator(f'[data-test="embed-dashboard-save-{REGISTRATION}"]').click()
    widget_dialog = page.get_by_role("dialog", name=labels["embed_widget"], exact=True)
    with page.expect_response(
        lambda response: matches(response, "POST", WIDGET_API)
    ) as created:
        widget_dialog.get_by_role(
            "button", name=labels["save_widget"], exact=True
        ).click()
    widget = response_object(created.value)["result"]
    assert widget["widget_type"] == TABLE
    assert widget["props"]["dataBinding"]["metrics"] == list(TABLE_METRICS)
    assert widget["props"]["dataBinding"]["dimensions"] == [REGISTRATION, PROPERTY_TYPE]
    embed_id = widget["uuid"]
    expect(
        widget_dialog.locator('[data-test="embed-widget-saved-snippet"]')
    ).to_contain_text(embed_id)
    widget_dialog.get_by_role("button", name=labels["close"], exact=True).last.click()
    dialog.get_by_role("button", name=labels["close"], exact=True).last.click()
    with page.expect_response(
        lambda response: matches(response, "PUT", f"{V2_API}/{dashboard_id}")
    ) as saved:
        page.locator('[data-test="header-save"]').click()
    assert saved.value.ok
    return embed_id


def verify_april(api: LabApi, document: dict[str, Any], embed_id: str) -> None:
    """April contains one registration and no sale, over the same six deals."""
    for date_role in (SALE, REGISTRATION):
        selector: dict[str, Any] = (
            {"id": embed_id}
            if date_role == REGISTRATION
            else {"widget": {"type": TABLE, "props": document["nodes"][SALE]["props"]}}
        )
        data = api.call(
            "POST",
            f"{WIDGET_API}/data",
            payload={
                **selector,
                "filters": [
                    {
                        "column": date_role,
                        "operator": "TIME_RANGE",
                        "value": {"start": "2026-04-01", "end": "2026-05-01"},
                    }
                ],
            },
        )["result"]
        verify_rows(data["rows"], date_role, april=True)


def verify_sdk_embed(
    page: Page, base: str, host: str, locale: str, embed_id: str, artifacts: Path
) -> None:
    """Render the persisted complex table through the real separate-origin SDK."""
    with (
        sdk_fixture(page, base, host, {TABLE: embed_id}),
        page.expect_response(
            lambda response: matches(response, "GET", f"{WIDGET_API}/{embed_id}")
        ) as definition,
        page.expect_response(
            lambda response: (
                matches(response, "POST", f"{WIDGET_API}/data")
                and response.request.post_data_json.get("id") == embed_id
            )
        ) as queried,
    ):
        page.goto(host)
    data = response_object(queried.value)["result"]
    props = response_object(definition.value)["result"]["props"]
    assert props["dataBinding"]["dimensions"] == [REGISTRATION, PROPERTY_TYPE]
    assert set(data["columns"]) == {REGISTRATION, PROPERTY_TYPE, *TABLE_METRICS}
    verify_rows(data["rows"], REGISTRATION)
    headers = queried.value.request.all_headers()
    assert "cookie" in headers
    assert "x-guesttoken" not in headers

    if locale == "ar":
        page.get_by_role("checkbox", name="العربية (RTL)", exact=True).check()
    section = page.get_by_role("heading", name="Saved widgets", exact=True).locator(
        "xpath=ancestor::section[1]"
    )
    widget = section.locator(f'[data-superset-widget="{TABLE}"]')
    expect(widget).to_have_attribute("dir", "rtl" if locale == "ar" else "ltr")
    expect(
        widget.get_by_text(CAPTIONS[locale][REGISTRATION], exact=True)
    ).to_be_visible()
    expect(section.locator("iframe")).to_have_count(0)
    verify_table(widget, locale, REGISTRATION)
    section.screenshot(path=str(artifacts / f"business-case-{locale}-embed.png"))


def publish_case(
    page: Page, base: str, locale: str, view_id: str, artifacts: Path
) -> tuple[int, str]:
    """Author through the documented API, then publish and reload in the real UI."""
    page.goto(f"{base}/lang/{locale}")
    api = LabApi(page, base)
    document = authored_document(view_id, locale)
    created = api.call(
        "POST",
        f"{V2_API}/",
        payload={"dashboard_title": CAPTIONS[locale]["root"], "document": document},
    )["result"]
    assert created["published"] is False
    assert created["revision"] == 1
    dashboard_id = created["id"]
    page.goto(f"{base}/dashboard/v2/{dashboard_id}/")
    verify_dashboard(page, locale, published=False)

    with page.expect_response(
        lambda response: matches(response, "PUT", f"/api/v1/dashboard/{dashboard_id}")
    ) as publication:
        page.locator('[data-test="header-publish"]').click()
    assert response_object(publication.value)["result"]["published"] is True
    expect(page.locator('[data-test="header-published"]')).to_have_text(
        LABELS[locale]["published"]
    )
    embed_id = save_registration_embed(page, dashboard_id, locale)
    page.reload()
    saved = stored_dashboard(page, base, dashboard_id)
    assert saved["published"] is True
    assert saved["revision"] > created["revision"]
    nodes = saved["document"]["nodes"]
    assert nodes[REGISTRATION]["props"]["embedWidgetId"] == embed_id
    assert nodes["root"]["props"]["nxtbiLocalization"]["sourceLocale"] == locale
    assert nodes["root"]["props"]["nxtbiLocalization"]["title"]["translations"] == {
        language: labels["root"] for language, labels in CAPTIONS.items()
    }
    verify_dashboard(page, locale, published=True)
    verify_april(api, document, embed_id)
    page.screenshot(path=str(artifacts / f"business-case-{locale}-dashboard.png"))
    return dashboard_id, embed_id


def main() -> None:
    """Exercise both languages against the disposable lab and its widget host."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--widget-host-url", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    host = args.widget_host_url.rstrip("/")
    if not fixture_origin(base) or not fixture_origin(host) or base == host:
        parser.error("Use separate loopback HTTP origins for Superset and the SDK.")
    username = os.getenv("NXTBI_SEMANTIC_LAB_USER")
    password = os.getenv("NXTBI_SEMANTIC_LAB_PASSWORD")
    if not username or not password:
        parser.error("The lab harness must supply the browser credentials.")
    artifacts = args.artifact_dir
    artifacts.mkdir(parents=True, exist_ok=True)

    expect.set_options(timeout=TIMEOUT)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1680, "height": 1100})
        page.set_default_timeout(TIMEOUT)
        try:
            login(page, base, username, password)
            views = datasource_rows(page, base)
            assert len(views) == 1
            view_id = views[0]["uuid"]
            for locale in CAPTIONS:
                dashboard_id, embed_id = publish_case(
                    page, base, locale, view_id, artifacts
                )
                verify_sdk_embed(page, base, host, locale, embed_id, artifacts)
                print(
                    f"PASS {locale} authored Dashboard V2 {dashboard_id}. "
                    "Four KPIs, both date roles, April reconciliation and live embed.",
                    flush=True,
                )
        except Exception:
            if not page.url.endswith("/login/"):
                with suppress(Error):
                    page.screenshot(
                        path=str(artifacts / "business-case-failure.png"), timeout=5_000
                    )
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()

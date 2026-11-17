"""Real-browser check of the NxtBI Superset demo (Chromium via Playwright, on the host).

    pip install playwright && playwright install chromium     # once
    python nxtbi/scripts/browser_check.py [--headed]

Signs in through the Keycloak UI, opens every NxtBI dashboard, applies a native filter,
opens Explore and SQL Lab, switches the UI to Arabic and signs out. Screenshots go to
nxtbi/docs/screenshots/, a machine-readable summary to nxtbi/out/browser-results.json.
Credentials are read from nxtbi/.env and never printed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
OUT = ROOT / "out"
ENV = {
    k.strip(): v.strip()
    for k, _, v in (line.partition("=") for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines())
    if k.strip() and not k.lstrip().startswith("#")
}
SUPERSET = ENV.get("SUPERSET_PUBLIC_URL", "http://localhost:8088").rstrip("/")
DASHBOARDS = {
    "nxtbi-budget-execution": "04-dashboard-budget-execution.png",
    "nxtbi-trade-population": "05-dashboard-trade.png",
    "nxtbi-service-operations": "07-dashboard-service-operations-admin.png",
}
RESULTS: list[dict[str, Any]] = []


def record(name: str, ok: bool, detail: Any) -> None:
    RESULTS.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {str(detail)[:260]}")


def shot(page: Page, name: str, full: bool = False) -> None:
    page.screenshot(path=str(SHOTS / name), full_page=full)


def login(page: Page, username: str, password: str) -> None:
    page.goto(f"{SUPERSET}/login/")
    page.wait_for_load_state("networkidle")
    page.get_by_text(re.compile("keycloak", re.I)).first.click()
    page.wait_for_url(re.compile(r"/realms/"))
    page.fill("#username", username)
    if page.locator("#password").count() == 0:  # identity-first flow: username page first
        page.locator("#kc-login").click()
        page.wait_for_selector("#password")
    page.fill("#password", password)
    page.locator("#kc-login").click()
    page.wait_for_url(re.compile(re.escape(SUPERSET)), timeout=30_000)
    page.wait_for_load_state("networkidle")


def logout(page: Page) -> str:
    page.goto(f"{SUPERSET}/logout/")
    page.wait_for_load_state("networkidle")
    return page.url


def open_dashboard(page: Page, slug: str) -> dict[str, Any]:
    """Open a dashboard and report on every chart-data call it makes."""
    calls: list[tuple[int, int]] = []

    def on_response(response: Any) -> None:
        if "/api/v1/chart/data" in response.url:
            rows = -1
            try:
                rows = sum(q.get("rowcount", 0) for q in response.json().get("result", []))
            except Exception:  # noqa: BLE001
                pass
            calls.append((response.status, rows))

    page.on("response", on_response)
    page.goto(f"{SUPERSET}/superset/dashboard/{slug}/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)  # chart animations
    page.remove_listener("response", on_response)
    charts = page.locator("[data-test='chart-container'], .chart-container").count()
    errors = page.locator(".dashboard-content [role='alert'], .dashboard-content .ant-alert-error").count()
    return {
        "title": page.title(),
        "charts_drawn": charts,
        "data_calls": len(calls),
        "failed_calls": sum(1 for status, _ in calls if status != 200),
        "empty_results": sum(1 for status, rows in calls if status == 200 and rows == 0),
        "error_alerts": errors,
    }


def main() -> int:
    headed = "--headed" in sys.argv
    SHOTS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)
    console_errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        context = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="en-US")
        page = context.new_page()
        page.on("console", lambda m: console_errors.append(m.text[:200]) if m.type == "error" else None)

        # --- login page and Keycloak UI ---------------------------------------------
        page.goto(f"{SUPERSET}/login/")
        page.wait_for_load_state("networkidle")
        shot(page, "01-login-nxtbi-sso.png")
        body = page.locator("body").inner_text()
        record("login page: NxtBI branding, Keycloak button, no password form",
               "keycloak" in body.lower() and page.locator("input[type=password]").count() == 0 and "NxtBI" in page.title(),
               f"title={page.title()!r}; password inputs={page.locator('input[type=password]').count()}")
        page.get_by_text(re.compile("keycloak", re.I)).first.click()
        page.wait_for_url(re.compile(r"/realms/"))
        shot(page, "02-keycloak-login.png")

        login(page, "superset.admin@nxtbi.local", ENV["SUPERSET_SSO_ADMIN_PASSWORD"])
        shot(page, "03-welcome-admin.png")
        record("SSO login through the Keycloak UI (platform admin)", page.url.startswith(SUPERSET), page.url)

        font = page.evaluate("getComputedStyle(document.body).fontFamily")
        logo = page.evaluate("(document.querySelector('.navbar-brand img, a.navbar-brand img, img[alt=\"NxtBI\"]')||{}).src || ''")
        record("theme applied (font, logo)", "IBM Plex Sans Arabic" in font and "nxtbi-logo" in logo, f"font={font[:60]!r}; logo={logo}")

        # --- dashboards ---------------------------------------------------------------
        for slug, file_name in DASHBOARDS.items():
            info = open_dashboard(page, slug)
            shot(page, file_name, full=True)
            ok = info["data_calls"] >= 6 and info["failed_calls"] == 0 and info["error_alerts"] == 0 and info["empty_results"] == 0
            record(f"dashboard renders: {slug}", ok, info)
            if slug == "nxtbi-trade-population":
                page.get_by_role("tab", name=re.compile("Population|السكان")).first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2500)
                shot(page, "06-dashboard-population-tab.png", full=True)
                record("dashboard tab switch (Population)", page.locator(".dashboard-content [role='alert']").count() == 0,
                       "second tab rendered without error alerts")

        # --- native filter ------------------------------------------------------------
        try:
            page.goto(f"{SUPERSET}/superset/dashboard/nxtbi-budget-execution/")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)
            kpi_before = page.locator("[data-test='chart-container']").first.inner_text()
            sector = page.locator("[data-test='filter-control-name']", has_text="Sector").first
            box = sector.locator("xpath=ancestor::*[.//input][1]").locator("input").first
            box.click()
            page.keyboard.type("Health")
            page.wait_for_timeout(1200)
            page.keyboard.press("Enter")
            page.keyboard.press("Escape")
            page.locator("[data-test='filter-bar__apply-button']").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            kpi_after = page.locator("[data-test='chart-container']").first.inner_text()
            shot(page, "08-native-filter-applied.png", full=True)
            record("native filter changes the dashboard (Sector = Health)", kpi_before != kpi_after,
                   f"first KPI before={kpi_before.strip()[:40]!r} after={kpi_after.strip()[:40]!r}")
        except Exception as exc:  # noqa: BLE001
            record("native filter changes the dashboard (Sector = Health)", False, f"{type(exc).__name__}: {str(exc)[:200]}")

        # --- Explore ------------------------------------------------------------------
        chart_id = page.evaluate(
            """async () => { const r = await fetch('/api/v1/chart/?q=' + encodeURIComponent("(filters:!((col:slice_name,opr:ct,value:'Spend')),page_size:5)"));
                             const j = await r.json(); return j.result.length ? j.result[0].id : null; }""")
        page.goto(f"{SUPERSET}/explore/?slice_id={chart_id}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        shot(page, "09-explore.png")
        record("Explore opens a saved chart", page.locator("[data-test='datasource-control'], .explore-container, #explore-container").count() > 0
               and page.locator(".ant-alert-error").count() == 0, f"chart id {chart_id}; url {page.url[:70]}")

        # --- SQL Lab ------------------------------------------------------------------
        page.goto(f"{SUPERSET}/sqllab/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        editor = ".ace_editor, .monaco-editor, [data-test='sql-editor']"
        if page.locator(editor).count() == 0:  # a first-time user starts without a query tab
            page.get_by_text("Add a new tab").first.click()
            page.wait_for_timeout(2500)
        shot(page, "10-sqllab.png")
        record("SQL Lab opens with an editor tab", "sqllab" in page.url and page.locator(editor).count() > 0, page.url)

        # --- Arabic UI ----------------------------------------------------------------
        page.goto(f"{SUPERSET}/lang/ar")
        page.goto(f"{SUPERSET}/dashboard/list/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        nav = page.locator("header, nav, .ant-menu").first.inner_text()
        shot(page, "11-arabic-dashboard-list.png")
        arabic = sum(1 for ch in nav if "؀" <= ch <= "ۿ")
        direction = page.evaluate("getComputedStyle(document.documentElement).direction")
        record("Arabic UI strings after switching language", arabic > 10, f"{arabic} Arabic characters in the navigation; layout direction = {direction}")
        page.goto(f"{SUPERSET}/superset/dashboard/nxtbi-budget-execution/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        shot(page, "12-arabic-dashboard.png", full=True)
        page.goto(f"{SUPERSET}/lang/en")

        # --- logout, then a tenant user -----------------------------------------------
        after_logout = logout(page)
        record("logout returns to the login page", "/login" in after_logout, after_logout)
        login(page, "planning.admin@nxtbi.local", ENV["NXTBI_DEMO_USER_PASSWORD"])
        record("second SSO login needs credentials again (Keycloak session ended)", page.url.startswith(SUPERSET), page.url)
        info = open_dashboard(page, "nxtbi-service-operations")
        # Chart contents only: the Markdown header names both organisations on purpose.
        text = "\n".join(page.locator("[data-test='chart-container']").all_inner_texts())
        shot(page, "13-dashboard-service-operations-planning-rls.png", full=True)
        record("RLS in the UI: planning user sees only its organisation",
               "Ministry of Planning" in text and "Statistics Bureau" not in text and info["failed_calls"] == 0,
               {**info, "mentions_planning": "Ministry of Planning" in text, "mentions_statistics": "Statistics Bureau" in text})
        page.goto(f"{SUPERSET}/superset/dashboard/nxtbi-trade-population/")
        page.wait_for_load_state("networkidle")
        record("other organisation's dashboard is not reachable", "nxtbi-trade-population" not in page.title()
               and page.locator("[data-test='chart-container']").count() == 0, f"url={page.url[:80]} title={page.title()!r}")
        logout(page)
        browser.close()

    severe = [e for e in console_errors if "favicon" not in e.lower()]
    (OUT / "browser-results.json").write_text(
        json.dumps({"results": RESULTS, "console_errors": severe[:30]}, indent=2, ensure_ascii=False), encoding="utf-8")
    failed = [r for r in RESULTS if r["status"] != "PASS"]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; {len(severe)} console errors; screenshots in {SHOTS}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

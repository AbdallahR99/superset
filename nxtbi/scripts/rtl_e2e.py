"""Functional end-to-end checks of Arabic / right-to-left support (real Chromium, running stack).

    python nxtbi/scripts/rtl_e2e.py                      # every check, Arabic and English
    python nxtbi/scripts/rtl_e2e.py --only 04,08         # checks whose name contains one of these
    python nxtbi/scripts/rtl_e2e.py --locales ar
    python nxtbi/scripts/rtl_e2e.py --keep               # keep the 'RTL E2E copy' dashboard + session
    python nxtbi/scripts/rtl_e2e.py --after-restart      # run after restarting the stack (needs --keep before)
    python nxtbi/scripts/rtl_e2e.py --cleanup            # delete what --keep left behind

Every check is independent, has a name and ends as PASS, FAIL or SKIP. Layout is asserted with
measured geometry (bounding boxes), never with screenshots; every check runs in Arabic and, as a
regression guard, in English with the assertions inverted. The three NxtBI dashboards are never
modified: the editing check works on a copy made with "Save as".

Results:  nxtbi/out/rtl-e2e-results.json      (exit code 1 when a check fails)
          nxtbi/out/rtl-e2e-restart-results.json   (--after-restart)
Failures: nxtbi/out/rtl-e2e/<check>.png       (screenshot at the moment of the failure)
State:    nxtbi/out/rtl-e2e-state.json, rtl-e2e-storage.json   (--keep; the second one holds the
          session cookie of the test admin, nxtbi/out/ is git-ignored)

Not tested here: server-side screenshots (reports, thumbnails). They are rendered by a headless
browser whose session has no locale, so they use BABEL_DEFAULT_LOCALE (English, LTR) whatever
the recipient's language is; see nxtbi/docs/rtl/03-surface-audit.md section 7.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rtl_audit import (  # noqa: E402
    DASHBOARDS, DROPDOWN, MODAL, POPOVER, PROBE, ROOT, SELECT_POPUP, SQL_OK, SUBMENU, SUPERSET, TOOLTIP,
    VIEWPORTS, api, delete_dashboard, expected_dir, find_dashboards, goto, hover_chart_point, login,
    open_right_menu, resolve_ids, set_locale, settle, sqllab_open, sqllab_run,
)

OUT = ROOT / "out"
SHOTS = OUT / "rtl-e2e"
RESULTS_FILE = OUT / "rtl-e2e-results.json"
RESTART_RESULTS_FILE = OUT / "rtl-e2e-restart-results.json"
STATE_FILE = OUT / "rtl-e2e-state.json"
STORAGE_FILE = OUT / "rtl-e2e-storage.json"
COPY_TITLE = "RTL E2E copy"
MARKER = "RTL-E2E-MARK علامة"
ARABIC = re.compile(r"[؀-ۿ]")
SESSION_HOURS = 8  # PERMANENT_SESSION_LIFETIME in nxtbi/config/superset_config.py
DEFAULT_LOCALE = "en"  # BABEL_DEFAULT_LOCALE in nxtbi/config/superset_config.py
TOL = 2.0  # px


class Skip(Exception):
    """The check cannot run here; the message says why."""


class Ctx:
    def __init__(self, browser: Browser, context: BrowserContext, ids: dict[str, Any], args: argparse.Namespace):
        self.browser, self.context, self.ids, self.args = browser, context, ids, args


Check = Callable[[Ctx, Page, str], dict[str, Any]]
CHECKS: list[tuple[str, Check, tuple[str, ...]]] = []


def check(name: str, locales: tuple[str, ...] = ("ar", "en")) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS.append((name, fn, locales))
        return fn
    return register


# ----------------------------------------------------------------------------- helpers

def expect(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def box(page: Page, selector: str, last: bool = False) -> dict[str, float]:
    locator = page.locator(selector)
    rect = (locator.last if last else locator.first).bounding_box()
    if not rect:
        raise AssertionError(f"not visible: {selector}")
    left, top = rect["x"], rect["y"]
    return {"left": round(left, 1), "right": round(left + rect["width"], 1), "top": round(top, 1),
            "bottom": round(top + rect["height"], 1), "cx": round(left + rect["width"] / 2, 1),
            "cy": round(top + rect["height"] / 2, 1)}


def span(rect: dict[str, float]) -> str:
    return f"[{rect['left']:.0f}..{rect['right']:.0f}]"


def before(a: dict[str, float], b: dict[str, float], rtl: bool, tol: float = TOL) -> bool:
    """a sits entirely on the inline-start side of b (right of it in RTL, left of it in LTR)."""
    return a["left"] >= b["right"] - tol if rtl else a["right"] <= b["left"] + tol


def start_half(inner: dict[str, float], outer: dict[str, float], rtl: bool) -> bool:
    """The centre of inner is in the inline-start half of outer."""
    middle = (outer["left"] + outer["right"]) / 2
    return inner["cx"] > middle if rtl else inner["cx"] < middle


def side(rtl: bool, start: bool = True) -> str:
    return "right" if rtl == start else "left"


def probe(page: Page) -> dict[str, Any]:
    return page.evaluate(PROBE)


def expect_direction(page: Page, locale: str, where: str) -> dict[str, Any]:
    state = probe(page)
    expect(state["dir"] == expected_dir(locale) and state["lang"] == locale,
           f"{where}: <html dir={state['dir']!r} lang={state['lang']!r}>, expected dir={expected_dir(locale)!r} lang={locale!r}")
    return state


def in_viewport(page: Page, rect: dict[str, float], tol: float = TOL) -> bool:
    size = page.viewport_size or VIEWPORTS["desktop"]
    return (rect["left"] >= -tol and rect["top"] >= -tol and rect["right"] <= size["width"] + tol
            and rect["bottom"] <= size["height"] + tol)


def gap(a: dict[str, float], b: dict[str, float]) -> float:
    dx = max(0.0, max(a["left"], b["left"]) - min(a["right"], b["right"]))
    dy = max(0.0, max(a["top"], b["top"]) - min(a["bottom"], b["bottom"]))
    return round(math.hypot(dx, dy), 1)


def switch_language_ui(page: Page, locale: str) -> None:
    """Use the language picker of the navbar, as a user does."""
    open_right_menu(page, "language-submenu")
    with page.expect_navigation(wait_until="load", timeout=30_000):
        page.locator(f"{SUBMENU} li[data-menu-id$='-{locale}'] a").first.click()
    settle(page, 1200)


def kpi(page: Page, chart_name: str) -> str | None:
    return page.evaluate(
        "name => { const e = document.querySelector(`[data-test-chart-name=\"${name}\"] .header-line`);"
        " return e ? e.innerText.trim() : null; }", chart_name)


def wait_until(page: Page, predicate: Callable[[], Any], timeout_ms: int = 20_000, step_ms: int = 400) -> Any:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        value = predicate()
        if value or time.monotonic() > deadline:
            return value
        page.wait_for_timeout(step_ms)


def close_popups(page: Page) -> None:
    page.keyboard.press("Escape")
    page.mouse.move(6, 400)
    page.wait_for_timeout(350)


def modal_boxes(page: Page) -> tuple[dict[str, float], dict[str, float]]:
    """(modal, close button) once the zoom-in animation of the modal is over."""
    page.locator(MODAL).first.wait_for(timeout=15_000)
    page.wait_for_timeout(900)
    return box(page, MODAL), box(page, f"{MODAL} .ant-modal-close")


def dashboard_path(ctx: Ctx, key: str) -> str:
    return f"/superset/dashboard/{ctx.ids[key]}/"


def chart_holder(ctx: Ctx, chart_name: str) -> str:
    return f"[data-test='chart-grid-component'][data-test-chart-id='{ctx.ids['charts'][chart_name]}']"


# ----------------------------------------------------------------------------- checks

@check("01-login-and-navigation")
def login_and_navigation(ctx: Ctx, _page: Page, locale: str) -> dict[str, Any]:
    """Fresh browser: Keycloak login, language picker, then the four main sections through the nav."""
    rtl = expected_dir(locale) == "rtl"
    context = ctx.browser.new_context(viewport=VIEWPORTS["desktop"], locale="en-US")
    context.set_default_timeout(15_000)
    page = context.new_page()
    try:
        login(page)
        goto(page, "/welcome/")
        expect("/login" not in page.url, f"login did not complete, still on {page.url}")
        switch_language_ui(page, locale)
        expect_direction(page, locale, "after the language picker")
        brand = box(page, "#main-menu a[data-test='internal-link'] img")
        nav = box(page, "[data-test='navbar-top']")
        right_menu = box(page, "#main-menu ul.ant-menu >> nth=1")
        first, second = box(page, "[data-test='navbar-top'] > li >> nth=0"), box(page, "[data-test='navbar-top'] > li >> nth=1")
        expect(before(brand, nav, rtl), f"brand {span(brand)} is not on the {side(rtl)} of the nav items {span(nav)}")
        expect(before(nav, right_menu, rtl), f"nav items {span(nav)} are not on the {side(rtl)} of the settings menus {span(right_menu)}")
        expect(before(first, second, rtl), f"first nav item {span(first)} is not on the {side(rtl)} of the second {span(second)}")
        visited = []
        for href in ("/dashboard/list/", "/chart/list/", "/tablemodelview/list/"):
            page.locator(f"[data-test='navbar-top'] a[href='{href}']").first.click()
            page.wait_for_url(re.compile(re.escape(href)), timeout=20_000)
            settle(page, 800)
            expect_direction(page, locale, href)
            expect(page.locator("[data-test='listview-table'], [data-test='styled-card']").count() > 0, f"{href}: no list rendered")
            visited.append(href)
        page.locator("[data-test='navbar-top'] [data-menu-id$='-SQL Lab']").first.hover()
        page.locator(f"{SUBMENU} a[href*='/sqllab/']").first.click()
        page.wait_for_url(re.compile(r"/sqllab/"), timeout=20_000)
        settle(page, 1500)
        expect_direction(page, locale, "/sqllab/")
        expect(page.locator("[data-test='SqlLabApp']").count() > 0, "SQL Lab did not render")
        visited.append("/sqllab/")
        return {"visited": visited, "brand": span(brand), "nav": span(nav), "settings_menus": span(right_menu)}
    finally:
        context.close()


@check("02-main-page-layout")
def main_page_layout(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    rtl = expected_dir(locale) == "rtl"
    problems: list[str] = []
    detail: dict[str, Any] = {}

    goto(page, dashboard_path(ctx, "budget"), 2500)
    filters, grid = box(page, "[data-test='dashboard-filters-panel']"), box(page, "[data-test='grid-container']")
    detail["dashboard"] = {"filter_bar": span(filters), "grid": span(grid)}
    if not before(filters, grid, rtl):
        problems.append(f"dashboard: filter bar {span(filters)} is not on the {side(rtl)} of the grid {span(grid)}")

    goto(page, f"/explore/?slice_id={ctx.ids['bar']}", 3500)
    source, controls = box(page, "[data-test='explore-datasource-gate']"), box(page, "[data-test='explore-controls-gate']")
    chart = box(page, "[data-test='chart-container']")
    detail["explore"] = {"datasource": span(source), "controls": span(controls), "chart": span(chart)}
    if not (before(source, controls, rtl) and before(controls, chart, rtl)):
        problems.append(f"explore: panels are not ordered datasource {span(source)}, controls {span(controls)}, "
                        f"chart {span(chart)} from the {side(rtl)}")

    goto(page, "/dashboard/list/", 1500)
    table, action = box(page, "[data-test='listview-table']"), box(page, "[data-test='dashboard-row-edit']")
    title = box(page, "[data-test='table-row'] a")
    detail["list"] = {"table": span(table), "title_link": span(title), "row_action": span(action)}
    if start_half(action, table, rtl) or not start_half(title, table, rtl):
        problems.append(f"list view: title {span(title)} should be in the {side(rtl)} half and the action column "
                        f"{span(action)} in the {side(rtl, False)} half of the table {span(table)}")

    goto(page, dashboard_path(ctx, "budget"), 2500)
    page.locator("[data-test='actions-trigger']").first.click()
    page.locator(f"{DROPDOWN} li[data-menu-id$='save_modal']").first.click()
    modal, close = modal_boxes(page)
    detail["modal"] = {"modal": span(modal), "close": span(close)}
    if start_half(close, modal, rtl):
        problems.append(f"modal: close button {span(close)} should be on the {side(rtl, False)} of the modal {span(modal)}")
    close_popups(page)
    expect(not problems, " | ".join(problems))
    return detail


@check("03-language-switching", locales=("ar",))
def language_switching(ctx: Ctx, page: Page, _locale: str) -> dict[str, Any]:
    """English <-> Arabic three times through the picker; no RTL residue, no growing style count."""
    set_locale(page, "en")
    goto(page, dashboard_path(ctx, "budget"), 2500)
    trips = []
    for trip in (1, 2, 3):
        switch_language_ui(page, "ar")
        if "/dashboard/" not in page.url:
            goto(page, dashboard_path(ctx, "budget"), 2500)
        arabic = expect_direction(page, "ar", f"trip {trip} Arabic")
        expect(arabic["rtlStyleClasses"] > 0, f"trip {trip}: no mirrored Emotion classes in Arabic")
        expect(not arabic["hscroll"], f"trip {trip}: horizontal scroll in Arabic ({arabic['scrollWidth']} > {arabic['clientWidth']})")
        expect(arabic["logoSide"] == "right", f"trip {trip}: brand is on the {arabic['logoSide']} in Arabic")
        switch_language_ui(page, "en")
        if "/dashboard/" not in page.url:
            goto(page, dashboard_path(ctx, "budget"), 2500)
        english = expect_direction(page, "en", f"trip {trip} English")
        expect(english["rtlStyleClasses"] == 0, f"trip {trip}: {english['rtlStyleClasses']} elements keep a superset-rtl- class in English")
        ant_rtl = page.locator("[class*='ant-'][class*='-rtl']").count()
        expect(ant_rtl == 0, f"trip {trip}: {ant_rtl} Ant Design elements keep an -rtl class in English")
        expect(not english["hscroll"], f"trip {trip}: horizontal scroll in English ({english['scrollWidth']} > {english['clientWidth']})")
        expect(english["logoSide"] == "left", f"trip {trip}: brand is on the {english['logoSide']} in English")
        trips.append({"ar_style_tags": arabic["emotionStyleTags"], "en_style_tags": english["emotionStyleTags"]})
    first, last = trips[0]["en_style_tags"], trips[-1]["en_style_tags"]
    expect(last <= first * 1.1 + 5, f"Emotion <style> tags keep growing across round trips: {[t['en_style_tags'] for t in trips]}")
    first, last = trips[0]["ar_style_tags"], trips[-1]["ar_style_tags"]
    expect(last <= first * 1.1 + 5, f"Emotion <style> tags keep growing in Arabic: {[t['ar_style_tags'] for t in trips]}")
    return {"round_trips": trips}


@check("04-popups-in-viewport")
def popups_in_viewport(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    """Dropdown, nav submenu, select popup, tooltip, popover and modal open on screen, next to the trigger."""
    rtl = expected_dir(locale) == "rtl"
    problems: list[str] = []
    detail: dict[str, Any] = {}

    def measure(name: str, trigger: str, popup: str, how: str = "click", max_gap: float = 16) -> None:
        try:
            target = page.locator(trigger).first
            target.scroll_into_view_if_needed()
            anchor = box(page, trigger)
            target.hover() if how == "hover" else target.click()
            page.locator(popup).last.wait_for(timeout=8000)
            page.wait_for_timeout(600)  # open animation
            shown = box(page, popup, last=True)
            distance = gap(anchor, shown)
            detail[name] = {"trigger": anchor, "popup": shown, "gap": distance}
            if not in_viewport(page, shown):
                problems.append(f"{name}: popup x{span(shown)} y[{shown['top']:.0f}..{shown['bottom']:.0f}] leaves the viewport {page.viewport_size}")
            if distance > max_gap:
                problems.append(f"{name}: popup x{span(shown)} opens {distance}px away from its trigger x{span(anchor)}")
        except AssertionError:
            raise
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: {type(exc).__name__}: {str(exc).splitlines()[0][:140]}")
        finally:
            close_popups(page)

    goto(page, dashboard_path(ctx, "budget"), 2500)
    measure("dashboard-header-dropdown", "[data-test='actions-trigger']", DROPDOWN)
    measure("chart-menu-dropdown", "[data-test='slice-header'] button[id$='-controls']", DROPDOWN)
    measure("filter-bar-settings-dropdown", "[data-test='filterbar-orientation-icon']", DROPDOWN)
    measure("native-filter-select", "[data-test='filter-bar'] .ant-select >> nth=1", SELECT_POPUP)
    measure("tooltip", "[data-test='refresh-button']", TOOLTIP, how="hover")
    measure("nav-settings-submenu", "#main-menu [data-menu-id$='-settings']", SUBMENU, how="hover")
    measure("nav-language-submenu", "#main-menu [data-menu-id$='-language-submenu']", SUBMENU, how="hover")
    measure("nav-sql-submenu", "[data-test='navbar-top'] [data-menu-id$='-SQL Lab']", SUBMENU, how="hover")

    goto(page, f"/explore/?slice_id={ctx.ids['bar']}", 3500)
    # ControlPopover places itself beside the control column on purpose, hence the larger gap
    measure("explore-filter-popover", "[data-test='adhoc_filters'] [data-test='option-label']", POPOVER, max_gap=60)
    measure("explore-metric-popover", "[data-test='metrics'] [data-test='option-label']", POPOVER, max_gap=60)
    measure("explore-actions-dropdown", "[data-test='actions-trigger']", DROPDOWN)
    page.locator("[data-test='query-save-button']").click()
    modal, close = modal_boxes(page)
    detail["save-chart-modal"] = {"modal": modal, "close": close}
    if not in_viewport(page, modal):
        problems.append(f"save-chart modal x{span(modal)} leaves the viewport")
    if start_half(close, modal, rtl):
        problems.append(f"save-chart modal: close button {span(close)} is not on the {side(rtl, False)} of {span(modal)}")
    close_popups(page)
    expect(not problems, " | ".join(problems))
    return {name: (f"trigger x{span(v['trigger'])} popup x{span(v['popup'])} gap {v['gap']}" if "gap" in v else
                   f"modal x{span(v['modal'])} close x{span(v['close'])}") for name, v in detail.items()}


def copy_title(locale: str) -> str:
    return COPY_TITLE if locale == "ar" else f"{COPY_TITLE} ({locale})"


def dashboard_snapshot(page: Page, ref: Any) -> dict[str, Any]:
    """What the API stores for a dashboard, parsed: raw JSON strings are not comparable (key order, spacing)."""
    result = api(page, f"/api/v1/dashboard/{ref}")["result"]
    metadata = json.loads(result.get("json_metadata") or "{}")
    return {
        "id": result.get("id"),
        "layout": json.loads(result.get("position_json") or "{}"),
        "metadata": metadata,
        "changed_on": result.get("changed_on"),
        # what an author typed or chose, as opposed to what the client derives and writes back
        "authored": {
            "title": result.get("dashboard_title"), "slug": result.get("slug"), "css": result.get("css") or "",
            "filters": [(f.get("id"), f.get("name")) for f in metadata.get("native_filter_configuration") or []],
            "color_scheme": metadata.get("color_scheme") or "",
            "cross_filters_enabled": metadata.get("cross_filters_enabled"),
        },
    }


def changed_keys(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return sorted(key for key in a.keys() | b.keys() if a.get(key) != b.get(key))


@check("05-dashboard-edit-and-save")
def dashboard_edit_and_save(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    """Save as -> edit a markdown block on the copy -> save -> reload -> persisted; originals untouched.

    "Untouched" is measured in two steps, because "Save as" itself writes to the source dashboard in
    every language: saveDashboardRequest.onCopySuccess (src/dashboard/actions/dashboardState.ts)
    dispatches saveChartConfiguration, a PUT of the json_metadata held by the client (recomputed
    cross-filter scoping, derived colour and scope fields) to the dashboard that is still open, the
    source. It moves the source's changed_on and may rewrite derived metadata, never the layout.
      1. source -> after "Save as": layout and authored settings identical; rewritten derived
         metadata keys are reported in the detail, not failed.
      2. after "Save as" -> after editing and saving the copy: nothing at all may differ.
    """
    rtl = expected_dir(locale) == "rtl"
    title = copy_title(locale)
    keep = ctx.args.keep and locale == "ar"
    source = dashboard_snapshot(page, ctx.ids["budget"])
    for stale in find_dashboards(page, title):
        delete_dashboard(page, stale)
    copy_id: int | None = None
    try:
        goto(page, dashboard_path(ctx, "budget"), 2500)
        expect(page.locator("[data-test='chart-grid-component']").count() > 0, "the dashboard shows no chart")
        page.locator("[data-test='actions-trigger']").first.click()
        page.locator(f"{DROPDOWN} li[data-menu-id$='save_modal']").first.click()
        page.locator(f"{MODAL} input[type='text']").first.fill(title)
        page.locator("[data-test='modal-save-dashboard-button']").click()
        found = wait_until(page, lambda: find_dashboards(page, title), 30_000, 1000)
        expect(found, f"'Save as' did not create a dashboard titled {title!r}")
        copy_id = int(found[0])
        expect(copy_id != source["id"], "'Save as' returned the original dashboard")

        goto(page, f"/superset/dashboard/{copy_id}/", 3000)
        expect_direction(page, locale, "copy, view mode")
        expect(f"/dashboard/{copy_id}/" in page.url, f"the page under edit is {page.url}, not the copy {copy_id}")
        baseline = dashboard_snapshot(page, ctx.ids["budget"])  # the PUT of "Save as" has settled by now
        expect(baseline["layout"] == source["layout"],
               f"'Save as' changed the layout of the ORIGINAL dashboard: {changed_keys(source['layout'], baseline['layout'])[:6]}")
        expect(baseline["authored"] == source["authored"],
               f"'Save as' changed authored settings of the ORIGINAL dashboard: {changed_keys(source['authored'], baseline['authored'])}")
        page.locator("[data-test='edit-dashboard-button']").click()
        page.locator("[data-test='dashboard-builder-sidepane']").wait_for(timeout=20_000)
        page.wait_for_timeout(1200)
        pane, grid = box(page, "[data-test='dashboard-builder-sidepane']"), box(page, "[data-test='grid-container']")
        expect(before(grid, pane, rtl), f"edit mode: builder pane {span(pane)} is not on the {side(rtl, False)} of the grid {span(grid)}")
        save_button, header = box(page, "[data-test='header-save-button']"), box(page, "[data-test='dashboard-header-container']")
        expect(not start_half(save_button, header, rtl), f"edit mode: Save {span(save_button)} is not at the {side(rtl, False)} end of the header {span(header)}")

        markdown = page.locator("[data-test='dashboard-markdown-editor']").first
        markdown.dblclick()
        markdown.locator(".ace_editor textarea").first.wait_for(state="attached", timeout=10_000)
        editor_dir = markdown.locator(".ace_editor").first.evaluate("e => getComputedStyle(e).direction")
        markdown.locator(".ace_editor textarea").first.focus()
        page.keyboard.press("Control+End")
        page.keyboard.insert_text(f"\n\n{MARKER}")
        page.wait_for_timeout(400)
        page.mouse.click(VIEWPORTS["desktop"]["width"] / 2, 5)  # empty part of the navbar: leaves the markdown editor
        page.wait_for_timeout(800)
        expect(MARKER in markdown.inner_text(), "the edited markdown does not show the new text before saving")
        page.locator("[data-test='header-save-button']").click()
        page.locator("[data-test='edit-dashboard-button']").wait_for(timeout=30_000)

        goto(page, f"/superset/dashboard/{copy_id}/", 3000)
        expect(MARKER in page.locator("[data-test='dashboard-markdown-editor']").first.inner_text(),
               "after reload the markdown text is not persisted on the copy")
        saved = api(page, f"/api/v1/dashboard/{copy_id}")["result"]
        expect(MARKER in json.dumps(json.loads(saved["position_json"]), ensure_ascii=False),
               "the API does not return the edited markdown for the copy")
        untouched = dashboard_snapshot(page, ctx.ids["budget"])
        expect(MARKER not in json.dumps(untouched["layout"], ensure_ascii=False),
               "the text typed into the copy was saved into the ORIGINAL dashboard")
        expect(untouched == baseline,
               "the ORIGINAL dashboard changed while editing the copy: "
               f"layout {changed_keys(baseline['layout'], untouched['layout'])[:6]}, "
               f"metadata {changed_keys(baseline['metadata'], untouched['metadata'])}, "
               f"changed_on {baseline['changed_on']} -> {untouched['changed_on']}")
        if keep:
            STATE_FILE.write_text(json.dumps({"copy_id": copy_id, "title": title, "marker": MARKER,
                                              "saved_at": time.time()}, ensure_ascii=False), encoding="utf-8")
        return {"copy_id": copy_id, "kept": keep, "markdown_editor_direction": editor_dir,
                "builder_pane": span(pane), "grid": span(grid),
                "source_metadata_rewritten_by_save_as": changed_keys(source["metadata"], baseline["metadata"]),
                "source_changed_on_moved_by_save_as": baseline["changed_on"] != source["changed_on"]}
    finally:
        if not keep:
            for leftover in find_dashboards(page, title):
                delete_dashboard(page, leftover)


@check("06-native-filters")
def native_filters(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    goto(page, dashboard_path(ctx, "service"), 3000)
    name = "Service Requests"
    original = wait_until(page, lambda: kpi(page, name), 30_000)
    expect(original, f"KPI {name!r} did not render")
    select = page.locator("[data-test='NATIVE_FILTER-service-channel']").first
    select.click()
    option = page.locator(f"{SELECT_POPUP} .ant-select-item-option").last
    option.wait_for(timeout=10_000)
    chosen = option.inner_text().strip()
    option.click()
    page.keyboard.press("Escape")
    page.locator("[data-test='filter-bar__apply-button']").click()
    filtered = wait_until(page, lambda: (kpi(page, name) or original) != original and kpi(page, name), 30_000)
    expect(filtered, f"KPI {name!r} stayed {original!r} after applying Channel = {chosen!r}")
    page.locator("[data-test='filter-bar__clear-button']").click()
    page.wait_for_timeout(500)
    apply = page.locator("[data-test='filter-bar__apply-button']")
    if apply.is_enabled():
        apply.click()
    restored = wait_until(page, lambda: kpi(page, name) == original, 30_000)
    expect(restored, f"KPI {name!r} is {kpi(page, name)!r} after 'Clear all', expected {original!r}")
    return {"kpi": name, "unfiltered": original, "channel": chosen, "filtered": filtered}


@check("06b-cross-filter")
def cross_filter(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    goto(page, dashboard_path(ctx, "service"), 3000)
    name = "Service Requests"
    original = wait_until(page, lambda: kpi(page, name), 30_000)
    expect(original, f"KPI {name!r} did not render")
    tried = []
    for chart in ("SLA Compliance by Service", "Requests by Status", "Channel Mix"):
        point = hover_chart_point(page, f"{chart_holder(ctx, chart)} canvas")
        if point is None:
            tried.append(f"{chart}: no hover target found")
            continue
        page.mouse.click(point["x"], point["y"])
        changed = wait_until(page, lambda: (kpi(page, name) or original) != original and kpi(page, name), 12_000)
        if not changed:
            tried.append(f"{chart}: click at ({point['x']:.0f},{point['y']:.0f}) emitted no cross-filter")
            continue
        page.mouse.click(point["x"], point["y"])  # same point again removes the cross-filter
        restored = wait_until(page, lambda: kpi(page, name) == original, 20_000)
        expect(restored, f"cross-filter from {chart!r} was not removed by clicking the same mark again ({kpi(page, name)!r} != {original!r})")
        return {"chart": chart, "unfiltered": original, "cross_filtered": changed, "skipped_before": tried}
    raise Skip("no chart reacted to a click with a cross-filter: " + "; ".join(tried))


def non_background_ratio(png: bytes) -> float:
    from PIL import Image  # noqa: PLC0415

    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.thumbnail((240, 240))
    colours = image.getcolors(maxcolors=image.width * image.height) or []
    background = max(colours)[1]
    painted = sum(n for n, colour in colours if sum(abs(a - b) for a, b in zip(colour, background)) > 40)
    return painted / (image.width * image.height)


@check("07-echarts")
def echarts(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    goto(page, dashboard_path(ctx, "budget"), 3000)
    bar = f"{chart_holder(ctx, 'Execution Rate by Sector')} canvas"
    pie_name = "الإنفاق حسب القطاع"
    pie = f"{chart_holder(ctx, pie_name)} canvas"
    page.locator(pie).first.scroll_into_view_if_needed()
    page.wait_for_timeout(2500)
    canvases = page.evaluate(
        "() => [...document.querySelectorAll('[data-test=chart-grid-component] canvas')].map(c => ({"
        " chart: c.closest('[data-test=chart-grid-component]').getAttribute('data-test-chart-name'),"
        " direction: getComputedStyle(c).direction, host: (c.closest('[dir]') || document.documentElement).getAttribute('dir') }))")
    expect(canvases, "no chart canvas on the dashboard")
    wrong = sorted({c["chart"] for c in canvases if c["direction"] != "ltr"})
    expect(not wrong, f"chart canvases with computed direction rtl: {wrong}")

    ratio = non_background_ratio(page.locator(pie).first.screenshot())
    expect(ratio > 0.03, f"the pie with Arabic labels ({pie_name}) renders an empty canvas ({ratio:.1%} painted)")
    try:
        data = api(page, f"/api/v1/chart/{ctx.ids['charts'][pie_name]}/data/")
        rows = (data.get("result") or [{}])[0].get("data") or []
    except Exception:  # noqa: BLE001 - the chart has no saved query context
        rows = []
    labels = [str(v) for row in rows for v in row.values() if isinstance(v, str)]
    if labels:
        expect(any(ARABIC.search(v) for v in labels), f"the pie data has no Arabic category: {labels[:4]}")

    point = hover_chart_point(page, bar)
    expect(point, "no ECharts tooltip appeared when hovering the bar chart")
    tip = page.evaluate(
        "() => { const e = [...document.querySelectorAll('.echarts-tooltip')].find(e => e.innerText.trim() && "
        "getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0); const r = e.getBoundingClientRect();"
        " return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, text: e.innerText.trim().replace(/\\s+/g, ' ').slice(0, 80),"
        " direction: getComputedStyle(e).direction}; }")
    expect(in_viewport(page, tip), f"ECharts tooltip x{span(tip)} y[{tip['top']:.0f}..{tip['bottom']:.0f}] leaves the viewport")
    expect(tip["direction"] == expected_dir(locale),
           f"ECharts tooltip (HTML, appended to <body>) has direction {tip['direction']!r}, the page is {expected_dir(locale)!r}")
    close_popups(page)
    return {"canvases": len(canvases), "pie_painted": f"{ratio:.1%}", "arabic_labels": [v for v in labels if ARABIC.search(v)][:3],
            "tooltip": tip["text"], "tooltip_box": span(tip), "tooltip_direction": tip["direction"]}


@check("08-sql-lab")
def sql_lab(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    rtl = expected_dir(locale) == "rtl"
    sqllab_open(page)
    expect_direction(page, locale, "SQL Lab")
    sqllab_run(page, SQL_OK, ".ag-root-wrapper")
    grid_js = (
        "() => { const g = document.querySelector('[data-test=south-pane] .ag-root-wrapper'); if (!g) return null;"
        " const x = e => Math.round(e.getBoundingClientRect().left);"
        " return { direction: getComputedStyle(g).direction,"
        " headers: [...g.querySelectorAll('[role=columnheader]')].map(h => ({name: h.innerText.trim(), x: x(h)})),"
        " cells: [...g.querySelectorAll('[role=gridcell]')].slice(0, 40).map(c => c.innerText.trim()) }; }")
    grid = wait_until(page, lambda: (lambda g: g if g and any(ARABIC.search(c) for c in g["cells"]) else None)(page.evaluate(grid_js)), 30_000)
    expect(grid, "the result grid shows no Arabic value for sector_ar")
    editor = page.evaluate(
        "() => { const e = document.querySelector('.ace_editor'); const content = e.querySelector('.ace_content').getBoundingClientRect();"
        " const line = e.querySelector('.ace_line').getBoundingClientRect(); const gutter = e.querySelector('.ace_gutter').getBoundingClientRect();"
        " return { direction: getComputedStyle(e).direction, textAlign: getComputedStyle(e).textAlign, value: e.querySelector('.ace_line').innerText,"
        " lineOffset: Math.round(line.left - content.left), gutterRight: Math.round(gutter.right), contentLeft: Math.round(content.left) }; }")
    expect(editor["direction"] == "ltr", f"the SQL editor has direction {editor['direction']!r}")
    expect(editor["gutterRight"] <= editor["contentLeft"] + TOL and abs(editor["lineOffset"]) < 30,
           f"the SQL text does not start at the left of the editor (gutter right {editor['gutterRight']}, text left {editor['contentLeft']}, line offset {editor['lineOffset']})")
    expect(editor["value"].strip().upper().startswith("SELECT"), f"the editor does not hold the typed query: {editor['value'][:40]!r}")
    expect(grid["direction"] == expected_dir(locale), f"the result grid has direction {grid['direction']!r}, expected {expected_dir(locale)!r}")
    position = {h["name"]: h["x"] for h in grid["headers"]}
    expect({"sector_en", "sector_ar", "spent"} <= set(position), f"result columns are {list(position)}")
    ordered = position["sector_en"] > position["sector_ar"] > position["spent"] if rtl else position["sector_en"] < position["sector_ar"] < position["spent"]
    expect(ordered, f"result columns are not laid out from the {side(rtl)}: {position}")
    notes = []
    index_x = next((h["x"] for h in grid["headers"] if h["name"] == ""), None)
    if index_x is not None and ((index_x < position["sector_en"]) if rtl else (index_x > position["sector_en"])):
        notes.append(f"row-number column at x={index_x} is on the inline-end side of the first data column (x={position['sector_en']})")
    return {"editor": editor, "grid_direction": grid["direction"], "columns_x": position,
            "arabic_cells": [c for c in grid["cells"] if ARABIC.search(c)][:3], "notes": notes}


def displayed_number(text: str) -> tuple[float, int] | None:
    cleaned = text.replace(",", "").replace("−", "-").replace("‎", "").replace("‏", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        return None
    return float(cleaned), len(cleaned.partition(".")[2])


@check("09-mixed-language-table")
def mixed_language_table(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    chart_id = ctx.ids["charts"]["Recent Requests"]
    payloads: list[dict[str, Any]] = []

    def on_response(response: Any) -> None:
        if "/api/v1/chart/data" not in response.url:
            return
        try:
            sent = json.loads(response.request.post_data or "{}")
            if sent.get("form_data", {}).get("slice_id") == chart_id:
                payloads.append(response.json()["result"][0])
        except Exception:  # noqa: BLE001
            pass

    page.on("response", on_response)
    try:
        goto(page, dashboard_path(ctx, "service"), 3000)
        holder = page.locator(chart_holder(ctx, "Recent Requests"))
        holder.scroll_into_view_if_needed()
        table_js = (
            "h => { const rows = [...h.querySelectorAll('tbody tr')]; if (!rows.length) return null; const t = h.querySelector('table');"
            " return { direction: getComputedStyle(t).direction, hostDir: (t.closest('[dir]') || document.documentElement).getAttribute('dir'),"
            " headers: [...h.querySelectorAll('thead th')].map(c => c.innerText.trim()),"
            " rows: rows.slice(0, 5).map(r => [...r.querySelectorAll('td')].map(c => ({text: c.innerText.trim(), align: getComputedStyle(c).textAlign}))) }; }")
        table = wait_until(page, lambda: holder.evaluate(table_js), 40_000, 800)
        expect(table, "the Recent Requests table rendered no rows")
        expect(payloads, "no /api/v1/chart/data response was seen for the Recent Requests table")
    finally:
        page.remove_listener("response", on_response)
    result = payloads[-1]
    columns = result["colnames"]
    expect("org_name_ar" in columns and "org_name_en" in columns, f"table columns are {columns}")
    headers = list(dict.fromkeys(table["headers"]))
    expect(len(headers) == len(columns), f"{len(headers)} header cells for {len(columns)} data columns: {headers}")
    first, row = result["data"][0], table["rows"][0]
    arabic_cell, english_cell = row[columns.index("org_name_ar")]["text"], row[columns.index("org_name_en")]["text"]
    expect(arabic_cell == str(first["org_name_ar"]) and ARABIC.search(arabic_cell), f"org_name_ar cell shows {arabic_cell!r}, data has {first['org_name_ar']!r}")
    expect(english_cell == str(first["org_name_en"]), f"org_name_en cell shows {english_cell!r}, data has {first['org_name_en']!r}")
    compared = {}
    for index, column in enumerate(columns):
        value = first[column]
        if result["coltypes"][index] != 0 or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue  # GenericDataType.NUMERIC only: dates arrive as epoch numbers
        shown = displayed_number(row[index]["text"])
        expect(shown is not None, f"numeric cell {column} is not readable as a number: {row[index]['text']!r} (data {value!r})")
        number, decimals = shown  # type: ignore[misc]
        expect(abs(number - float(value)) <= 0.5 * 10 ** -decimals + 1e-9, f"numeric cell {column} shows {row[index]['text']!r}, the chart data API returned {value!r}")
        compared[column] = row[index]["text"]
    expect(compared, "the first row has no numeric value to compare")
    signs = [entry for entry in probe(page)["bidi"] if entry.startswith("sign:")]
    expect(not signs, f"signed numbers painted with the sign on the wrong side: {signs}")
    expect(table["direction"] == expected_dir(locale),
           f"the table chart has direction {table['direction']!r} (host dir={table['hostDir']!r}) on a {expected_dir(locale)!r} page: "
           "HTML tables are meant to inherit the page direction (ChartMetadata direction: 'inherit')")
    return {"headers": headers, "org_name_ar": arabic_cell, "org_name_en": english_cell, "numeric_cells": compared,
            "table_direction": table["direction"]}


def responsive_problems(ctx: Ctx, page: Page, locale: str, seen: dict[Any, Any]) -> dict[str, str]:
    """No horizontal page scroll, no colliding header controls, a usable nav at 1024px and 390px."""
    found: dict[str, str] = {}
    for width, height in ((1024, 800), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        sizes = {}
        for path in ("/welcome/", "/dashboard/list/", dashboard_path(ctx, "budget")):
            goto(page, path, 2500)
            state = expect_direction(page, locale, f"{width}px {path}")
            sizes[path] = f"{state['scrollWidth']}/{state['clientWidth']}"
            if state["hscroll"]:
                found[f"{width} {path} hscroll"] = (f"{width}px {path}: horizontal page scroll ({state['scrollWidth']} > "
                                                    f"{state['clientWidth']}); offscreen {state['offscreen'][:2]}")
            if state["headerOverlaps"]:
                found[f"{width} {path} overlap"] = f"{width}px {path}: overlapping header controls {state['headerOverlaps'][:2]}"
            if state["headerClipped"]:
                found[f"{width} {path} clipped"] = f"{width}px {path}: header controls outside their bar {state['headerClipped'][:2]}"
        goto(page, "/welcome/", 1500)
        link = page.locator("#main-menu a[href='/chart/list/']").first
        if not link.is_visible():  # collapsed into a menu button
            page.locator("#main-menu .ant-menu-overflow-item-rest, #main-menu [aria-label='menu'], #main-menu .anticon-menu").first.click()
            page.wait_for_timeout(600)
            link = page.locator("a[href='/chart/list/']:visible").first
        place = box(page, "a[href='/chart/list/']:visible")
        if not in_viewport(page, {**place, "top": 0, "bottom": 0}):
            found[f"{width} nav"] = f"{width}px: nav link 'Charts' {span(place)} is outside the viewport"
        link.click()
        page.wait_for_url(re.compile(r"/chart/list/"), timeout=20_000)
        seen[width] = {"scroll_width/client_width": sizes, "nav_link": span(place)}
    page.set_viewport_size(VIEWPORTS["desktop"])
    return found


@check("10-theme-and-responsive")
def theme_and_responsive(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    rtl = expected_dir(locale) == "rtl"
    problems: list[str] = []
    detail: dict[str, Any] = {"viewports": {}}
    try:
        goto(page, "/welcome/")
        open_right_menu(page, "theme-sub-menu")
        page.locator(f"{SUBMENU} li[data-menu-id$='-dark']").first.click()
        page.wait_for_timeout(1500)
        goto(page, dashboard_path(ctx, "budget"), 2500)
        dark = expect_direction(page, locale, "dark theme")
        expect(dark["darkBackground"], "the dark theme was not applied by the theme menu")
        expect(dark["logoSide"] == side(rtl), f"dark theme: brand on the {dark['logoSide']}")
        filters, grid = box(page, "[data-test='dashboard-filters-panel']"), box(page, "[data-test='grid-container']")
        expect(before(filters, grid, rtl), f"dark theme: filter bar {span(filters)} is not on the {side(rtl)} of the grid {span(grid)}")
        expect(not dark["hscroll"], "dark theme: horizontal page scroll")
        detail["dark"] = {"filter_bar": span(filters), "grid": span(grid)}
        goto(page, "/welcome/")
        open_right_menu(page, "theme-sub-menu")
        page.locator(f"{SUBMENU} li[data-menu-id$='-default']").first.click()
        page.wait_for_timeout(1200)
        expect(not probe(page)["darkBackground"], "the light theme was not restored by the theme menu")

        found = responsive_problems(ctx, page, locale, detail["viewports"])
        if found and locale != "en":
            # tell an RTL regression from a layout that is equally broken left-to-right
            set_locale(page, "en")
            english = responsive_problems(ctx, page, "en", {})
            set_locale(page, locale)
            found = {key: text + (" (same problem in English: not caused by RTL)" if key in english else " (ARABIC ONLY)")
                     for key, text in found.items()}
        problems.extend(found.values())
    finally:
        page.set_viewport_size(VIEWPORTS["desktop"])
        page.evaluate("() => localStorage.setItem('superset-theme-mode', 'default')")
    expect(not problems, " | ".join(problems))
    return detail


@check("11-download-as-image")
def download_as_image(ctx: Ctx, page: Page, locale: str) -> dict[str, Any]:
    goto(page, dashboard_path(ctx, "service"), 3500)
    page.locator("[data-test='actions-trigger']").first.click()
    page.locator(DROPDOWN).last.wait_for(timeout=8000)
    item = page.locator("li[data-menu-id$='download-image']")
    for submenu in page.locator(f"{DROPDOWN} li.ant-dropdown-menu-submenu").all():
        submenu.hover()
        page.wait_for_timeout(700)
        if item.count() and item.first.is_visible():
            break
    if not (item.count() and item.first.is_visible()):
        close_popups(page)
        raise Skip("the dashboard menu offers no 'Download as image' entry")
    with page.expect_download(timeout=120_000) as started:
        item.first.click()
    download = started.value
    name = download.suggested_filename
    download.cancel()
    expect(re.search(r"\.(jpe?g|png)$", name, re.I), f"unexpected download file name {name!r}")
    return {"file": name}


# ----------------------------------------------------------------------------- after restart

def after_restart(browser: Browser, args: argparse.Namespace) -> list[tuple[str, Check]]:
    def kept_session(_ctx: Ctx, _page: Page, _locale: str) -> dict[str, Any]:
        if not STORAGE_FILE.exists() or not STATE_FILE.exists():
            raise Skip("no kept session: run rtl_e2e.py --keep before restarting the stack")
        age_hours = (time.time() - json.loads(STATE_FILE.read_text(encoding="utf-8"))["saved_at"]) / 3600
        if age_hours > SESSION_HOURS:
            raise Skip(f"the kept session is {age_hours:.1f} h old, sessions live {SESSION_HOURS} h")
        context = browser.new_context(viewport=VIEWPORTS["desktop"], storage_state=str(STORAGE_FILE), locale="en-US")
        page = context.new_page()
        try:
            page.goto(f"{SUPERSET}/welcome/")
            settle(page, 1500)
            expect("/login" not in page.url and "/realms/" not in page.url,
                   "the server-side session (Redis) did not survive the restart: the kept cookie leads to the login page")
            state = expect_direction(page, "ar", "kept Arabic session after restart")
            expect(state["logoSide"] == "right", f"brand on the {state['logoSide']} in the kept Arabic session")
            return {"session_age_hours": round(age_hours, 2), "dir": state["dir"], "lang": state["lang"]}
        finally:
            context.close()

    def new_login(_ctx: Ctx, _page: Page, _locale: str) -> dict[str, Any]:
        context = browser.new_context(viewport=VIEWPORTS["desktop"], locale="en-US")
        page = context.new_page()
        try:
            login(page)
            goto(page, "/welcome/")
            # the language lives in the session, not in the user profile: a new login starts in the default locale
            first = expect_direction(page, DEFAULT_LOCALE, "new login")
            switch_language_ui(page, "ar")
            second = expect_direction(page, "ar", "new login after choosing Arabic")
            return {"new_login": f"{first['lang']}/{first['dir']}", "after_picker": f"{second['lang']}/{second['dir']}"}
        finally:
            context.close()

    def kept_copy(ctx: Ctx, page: Page, _locale: str) -> dict[str, Any]:
        if not STATE_FILE.exists():
            raise Skip("no kept dashboard: run rtl_e2e.py --keep before restarting the stack")
        kept = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        set_locale(page, "ar")
        expect(kept["copy_id"] in find_dashboards(page, kept["title"]), f"dashboard {kept['title']!r} (id {kept['copy_id']}) no longer exists")
        goto(page, f"/superset/dashboard/{kept['copy_id']}/", 3500)
        expect_direction(page, "ar", "kept copy")
        expect(kept["marker"] in page.locator("[data-test='dashboard-markdown-editor']").first.inner_text(), "the edited markdown is gone after the restart")
        charts = page.locator("[data-test='chart-grid-component']").count()
        expect(charts > 0 and wait_until(page, lambda: kpi(page, "Allocated Budget"), 30_000), "the kept copy renders no chart data")
        filters, grid = box(page, "[data-test='dashboard-filters-panel']"), box(page, "[data-test='grid-container']")
        expect(before(filters, grid, True), f"filter bar {span(filters)} is not on the right of the grid {span(grid)}")
        return {"copy_id": kept["copy_id"], "charts": charts, "kpi": kpi(page, "Allocated Budget")}

    return [("12a-restart-kept-session-stays-arabic", kept_session), ("12b-restart-new-login-locale", new_login),
            ("12c-restart-kept-dashboard-renders", kept_copy)]


# ----------------------------------------------------------------------------- runner

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--locales", default="ar,en")
    parser.add_argument("--only", default="", help="comma separated substrings of check names")
    parser.add_argument("--keep", action="store_true", help="keep the 'RTL E2E copy' dashboard and the Arabic session for --after-restart")
    parser.add_argument("--after-restart", action="store_true", help="only the persistence checks (run --keep first, then restart the stack)")
    parser.add_argument("--cleanup", action="store_true", help="delete the kept dashboard and state files, then exit")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    only = [x for x in args.only.split(",") if x]
    locales = [x for x in args.locales.split(",") if x]
    SHOTS.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    def run(name: str, fn: Check, locale: str, ctx: Ctx) -> None:
        label = f"{name}[{locale}]"
        page = ctx.context.new_page()
        started = time.monotonic()
        record: dict[str, Any] = {"check": name, "locale": locale}
        try:
            if fn not in restart_fns:
                set_locale(page, locale)
            record.update({"status": "PASS", "detail": fn(ctx, page, locale)})
        except Skip as skip:
            record.update({"status": "SKIP", "detail": str(skip)})
        except AssertionError as failure:
            record.update({"status": "FAIL", "kind": "assertion", "detail": str(failure)})
        except Exception as exc:  # noqa: BLE001 - a timeout or a missing element: product or test, needs triage
            record.update({"status": "FAIL", "kind": "error", "detail": f"{type(exc).__name__}: {str(exc)[:400]}"})
        if record["status"] == "FAIL":
            try:
                shot = SHOTS / f"{name}-{locale}.png"
                page.screenshot(path=str(shot))
                record["screenshot"] = str(shot.relative_to(ROOT)).replace("\\", "/")
            except Exception:  # noqa: BLE001
                pass
        record["seconds"] = round(time.monotonic() - started, 1)
        results.append(record)
        print(f"[{record['status']}] {label}: {json.dumps(record['detail'], ensure_ascii=False)[:420]}")
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(viewport=VIEWPORTS["desktop"], locale="en-US", accept_downloads=True)
        context.set_default_timeout(15_000)
        page = context.new_page()
        login(page)
        ctx = Ctx(browser, context, resolve_ids(page), args)
        restart_checks = after_restart(browser, args)
        restart_fns = {fn for _, fn in restart_checks}
        try:
            if args.cleanup:
                removed = [delete_dashboard(page, d) for d in find_dashboards(page, COPY_TITLE)]
                for leftover in (STATE_FILE, STORAGE_FILE):
                    leftover.unlink(missing_ok=True)
                print(f"deleted {len(removed)} kept dashboard(s) and the state files")
                return 0
            if args.after_restart:
                for name, fn in restart_checks:
                    if not only or any(o in name for o in only):
                        run(name, fn, "ar", ctx)
            else:
                for name, fn, check_locales in CHECKS:
                    if only and not any(o in name for o in only):
                        continue
                    for locale in locales:
                        if locale in check_locales:
                            run(name, fn, locale, ctx)
                if args.keep:
                    set_locale(page, "ar")
                    context.storage_state(path=str(STORAGE_FILE))
        finally:
            try:
                if not (args.keep and not args.after_restart):
                    set_locale(page, "en")
            except Exception:  # noqa: BLE001
                pass
            context.close()
            browser.close()

    summary = {status: sum(1 for r in results if r["status"] == status) for status in ("PASS", "FAIL", "SKIP")}
    results_file = RESTART_RESULTS_FILE if args.after_restart else RESULTS_FILE
    results_file.write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "base_url": SUPERSET,
        "mode": "after-restart" if args.after_restart else "full", "summary": summary, "checks": results,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{summary['PASS']} passed, {summary['FAIL']} failed, {summary['SKIP']} skipped -> {results_file}")
    return 1 if summary["FAIL"] else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

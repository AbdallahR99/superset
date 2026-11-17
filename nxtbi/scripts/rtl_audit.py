"""RTL / LTR visual audit and regression check for the NxtBI Superset fork.

    python nxtbi/scripts/rtl_audit.py                       # ar + en, light, desktop
    python nxtbi/scripts/rtl_audit.py --locales ar --only dashboard,explore
    python nxtbi/scripts/rtl_audit.py --themes light,dark --viewports desktop,tablet,mobile
    python nxtbi/scripts/rtl_audit.py --update-baseline      # accept the current screenshots
    python nxtbi/scripts/rtl_audit.py --compare              # fail on visual drift from the baseline

Signs in through Keycloak (credentials from nxtbi/.env, never printed), walks the main
screens in every requested locale x theme x viewport, takes a screenshot of each state and
records layout probes that catch the usual right-to-left defects without a human looking:

  * <html dir/lang> matches the locale
  * no horizontal page scrollbar, no visible element pushed outside the viewport
  * the direction applied to code editors and chart canvases (must stay LTR)
  * text inputs that hold code (SQL, URIs, JSON, CSS) and <pre>/<code> are LTR
  * header controls that overlap each other or leave the navbar / page header box
  * left-to-right text reordered by the bidi algorithm: "-5" painted as "5-", "4 options" as
    "options 4", "Loading." as ".Loading"

Screenshots: nxtbi/out/rtl-audit/<locale>-<theme>-<viewport>/<screen>.png
Results:     nxtbi/out/rtl-audit/results.json   (accumulates across runs, keyed by locale/theme/viewport/screen)
Baseline:    nxtbi/tests/rtl-visual/baseline/...   (--update-baseline / --compare, needs Pillow)

Nothing is changed on the three NxtBI dashboards: states that need a saved change (the
horizontal filter bar) run on a temporary copy that is deleted again.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "rtl-audit"
BASELINE = ROOT / "tests" / "rtl-visual" / "baseline"
ENV = {
    k.strip(): v.strip()
    for k, _, v in (line.partition("=") for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines())
    if k.strip() and not k.lstrip().startswith("#")
}
SUPERSET = ENV.get("SUPERSET_PUBLIC_URL", "http://localhost:8088").rstrip("/")
VIEWPORTS = {"desktop": {"width": 1600, "height": 1000}, "tablet": {"width": 1024, "height": 800},
             "mobile": {"width": 390, "height": 844}}
RTL_LOCALES = {"ar", "fa", "he", "ur"}
DASHBOARDS = {"budget": "nxtbi-budget-execution", "trade": "nxtbi-trade-population",
              "service": "nxtbi-service-operations"}
SQL_DATABASE = "NxtBI Demo"
SQL_OK = ("SELECT sector_en, sector_ar, sum(spent_amount) AS spent FROM nxtbi.budget_execution "
          "GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20")
SQL_BAD = "SELECT * FROM nxtbi.no_such_table_rtl"
AUDIT_COPY_TITLE = "RTL audit tmp (horizontal filter bar)"

# Open antd popups (antd 6 class names; hidden ones stay in the DOM with a -hidden class).
DROPDOWN = ".ant-dropdown:not(.ant-dropdown-hidden)"
SUBMENU = ".ant-menu-submenu-popup:not(.ant-menu-submenu-hidden)"
SELECT_POPUP = ".ant-select-dropdown:not(.ant-select-dropdown-hidden)"
POPOVER = ".ant-popover:not(.ant-popover-hidden)"
TOOLTIP = ".ant-tooltip:not(.ant-tooltip-hidden)"
MODAL = ".ant-modal-container"

PROBE = r"""
() => {
  const de = document.documentElement;
  const vw = de.clientWidth;
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) !== 0;
  };
  const label = el => `${el.tagName.toLowerCase()}[${(el.getAttribute('data-test') || el.getAttribute('aria-label')
    || el.getAttribute('data-menu-id') || el.id || (el.innerText || '').trim().slice(0, 20)
    || String(el.className.baseVal ?? el.className).slice(0, 30)).replace(/^rc-menu-uuid-[^-]*-/, '')}]`;
  const box = r => `[${Math.round(r.left)},${Math.round(r.right)}]`;

  const offscreen = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right < -2 || r.left > vw + 2) {
      // ignore things that are clipped by a scrolling ancestor on purpose
      let clipped = false;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ps = getComputedStyle(p);
        if (/(auto|scroll|hidden|clip)/.test(ps.overflowX)) { clipped = true; break; }
      }
      if (!clipped && offscreen.length < 6) offscreen.push(`${label(el)} ${box(r)}`);
    }
  }

  const dirOf = sel => Array.from(document.querySelectorAll(sel)).slice(0, 40).map(e => getComputedStyle(e).direction);
  const count = (arr, v) => arr.filter(x => x === v).length;
  const editors = dirOf('.ace_editor, .monaco-editor');
  const canvases = dirOf('canvas');

  // (a) text that is code must be left-to-right
  const CODE_HINT = /(^|[\s_-])(sql|uri|url|json|css|cron|regex|jinja)($|[\s_-])|sqlalchemy|expression/i;
  const CODE_VALUE = /^\s*(select|with|insert|update|delete)\b|^[a-z][a-z0-9+.-]*:\/\/|^\s*[{[]|^\s*\{\{/i;
  const codeRtl = [];
  for (const el of document.querySelectorAll('pre, code, textarea, input[type=text], input:not([type])')) {
    // not code: Ace (isolates itself), select search boxes, list-view search filters
    if (!visible(el) || el.closest('.ace_editor, .ant-select, [data-test=filters-search]')) continue;
    const attrs = ['name', 'id', 'data-test', 'placeholder'].map(a => el.getAttribute(a) || '').join(' ');
    const isCode = /^(PRE|CODE)$/.test(el.tagName) || CODE_HINT.test(attrs)
      || CODE_VALUE.test(el.value || '') || CODE_VALUE.test(el.getAttribute('placeholder') || '');
    if (isCode && getComputedStyle(el).direction === 'rtl' && codeRtl.length < 6) {
      codeRtl.push(`${label(el)} "${(el.value || el.innerText || el.getAttribute('placeholder') || '').trim().slice(0, 30)}"`);
    }
  }

  // (b) header controls that overlap each other or leave their bar
  const titleInput = document.querySelector('[data-test=editable-title-input]');
  let pageHeader = document.querySelector('[data-test=dashboard-header-container]');
  if (!pageHeader && titleInput) {
    for (let p = titleInput.parentElement; p && p !== document.body; p = p.parentElement) {
      if (p.getBoundingClientRect().width > vw * 0.6) { pageHeader = p; break; }
    }
  }
  const headerOverlaps = [], headerClipped = [];
  for (const root of [document.querySelector('#main-menu'), pageHeader]) {
    if (!root) continue;
    const rr = root.getBoundingClientRect();
    const all = Array.from(root.querySelectorAll(
      'a, button, input, img, [role=button], [role=menuitem], .ant-tag, [data-test=metadata-bar] > *')).filter(visible);
    const leaves = all.filter(e => !all.some(o => o !== e && e.contains(o)));
    for (const e of leaves) {
      const r = e.getBoundingClientRect();
      if ((r.left < Math.max(rr.left, 0) - 2 || r.right > Math.min(rr.right, vw) + 2) && headerClipped.length < 6) {
        headerClipped.push(`${label(e)} ${box(r)} outside ${box(rr)}`);
      }
    }
    for (let i = 0; i < leaves.length; i++) {
      for (let j = i + 1; j < leaves.length; j++) {
        const a = leaves[i].getBoundingClientRect(), b = leaves[j].getBoundingClientRect();
        const ix = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ix > 3 && iy > 3 && headerOverlaps.length < 6) {
          headerOverlaps.push(`${label(leaves[i])} ${box(a)} x ${label(leaves[j])} ${box(b)}`);
        }
      }
    }
  }

  // (c) bidi sanity on text the browser reorders in an RTL context (measured, not guessed):
  //   sign:        "-5"          painted as "5-"
  //   number-word: "4 options"   painted as "options 4"  (untranslated or user text without dir="auto")
  //   punctuation: "Loading."    painted as ".Loading"
  const bidi = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  let seen = 0;
  for (let n = walker.nextNode(); n && seen < 4000 && bidi.length < 8; n = walker.nextNode()) {
    seen++;
    const text = n.nodeValue, parent = n.parentElement;
    if (!parent || text.trim().length < 2 || parent.closest('.ace_editor, pre, code, script, style, canvas') || !visible(parent)) continue;
    const at = i => { range.setStart(n, i); range.setEnd(n, i + 1); return range.getBoundingClientRect(); };
    const swapped = (first, second) => {
      const a = at(first), b = at(second);
      return a.width > 0 && b.width > 0 && Math.abs(a.top - b.top) < 4 && a.left > b.left + 1;
    };
    const quote = `"${text.trim().slice(0, 24)}" in ${label(parent)}`;
    let m;
    if ((m = /^(\s*)[-+\u2212]\s?\d/.exec(text)) && swapped(m[1].length, text.search(/\d/))) {
      bidi.push(`sign: ${quote}`);
    } else if ((m = /^(\s*)\d[\d.,]*\s+[A-Za-z]{2}/.exec(text)) && swapped(m[1].length, text.search(/[A-Za-z]/))) {
      bidi.push(`number-word: ${quote}`);
    } else if (!/[\u0590-\u08FF]/.test(text) && (m = /[A-Za-z][.:!?](\s*)$/.exec(text)) && swapped(m.index, m.index + 1)) {
      bidi.push(`punctuation: ${quote}`);
    }
  }

  const logo = document.querySelector('#main-menu a[data-test=internal-link] img, .navbar-brand, header img');
  const logoRect = logo && visible(logo) ? logo.getBoundingClientRect() : null;
  const bg = (getComputedStyle(document.body).backgroundColor.match(/[\d.]+/g) || [255, 255, 255]).map(Number);
  return {
    dir: de.getAttribute('dir'), lang: de.getAttribute('lang'),
    hscroll: de.scrollWidth > de.clientWidth + 1, scrollWidth: de.scrollWidth, clientWidth: de.clientWidth,
    offscreen,
    editors: editors.length, editorsRtl: count(editors, 'rtl'),
    canvases: canvases.length, canvasesRtl: count(canvases, 'rtl'),
    codeRtl, headerOverlaps, headerClipped, bidi,
    rtlStyleClasses: document.querySelectorAll('[class*="superset-rtl-"]').length,
    antRtl: document.querySelectorAll('[class*="-rtl"]').length,
    emotionStyleTags: document.querySelectorAll('style[data-emotion]').length,
    logoSide: logoRect ? (logoRect.left + logoRect.width / 2 < vw / 2 ? 'left' : 'right') : null,
    darkBackground: (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) < 110,
    errors: document.querySelectorAll('.ant-alert-error').length,
  };
}
"""

FETCH = r"""
async ([method, path, body]) => {
  const headers = {'Content-Type': 'application/json'};
  if (method !== 'GET') {
    headers['X-CSRFToken'] = (await (await fetch('/api/v1/security/csrf_token/')).json()).result;
  }
  const response = await fetch(path, {method, headers, body: body ? JSON.stringify(body) : undefined});
  let payload = null;
  try { payload = await response.json(); } catch (e) { /* not JSON */ }
  return {status: response.status, json: payload};
}
"""


# ----------------------------------------------------------------------------- shared helpers
# (imported by rtl_e2e.py)

def settle(page: Page, extra_ms: int = 1200) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:  # noqa: BLE001 - long polling pages never go idle
        pass
    page.wait_for_timeout(extra_ms)


def login(page: Page) -> None:
    page.goto(f"{SUPERSET}/login/")
    settle(page, 400)
    if "/login" not in page.url and "/realms/" not in page.url:
        return  # the session is still valid
    if "/realms/" not in page.url:
        page.get_by_text(re.compile("keycloak", re.I)).first.click()
        page.wait_for_url(re.compile(r"/realms/|" + re.escape(SUPERSET) + r"/(?!login)"), timeout=30_000)
    if "/realms/" in page.url:
        page.fill("#username", ENV.get("NXTBI_PLATFORM_ADMINS", "superset.admin@nxtbi.local").split(",")[0])
        if page.locator("#password").count() == 0:  # identity-first flow: username page first
            page.locator("#kc-login").click()
            page.wait_for_selector("#password")
        page.fill("#password", ENV["SUPERSET_SSO_ADMIN_PASSWORD"])
        page.locator("#kc-login").click()
        page.wait_for_url(re.compile(re.escape(SUPERSET)), timeout=30_000)
    settle(page, 400)


def goto(page: Page, path: str, wait: int = 1200) -> None:
    """Navigate, tolerating one short restart of the web container and an expired session."""
    url = path if path.startswith("http") else f"{SUPERSET}{path}"
    for attempt in (1, 2):
        try:
            response = page.goto(url)
            if response is not None and response.status >= 502:
                raise RuntimeError(f"HTTP {response.status}")
            break
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            page.wait_for_timeout(8000)
    settle(page, wait)
    if "/login" in page.url and "/login" not in url:
        login(page)
        page.goto(url)
        settle(page, wait)


def api(page: Page, path: str) -> Any:
    return page.evaluate("async p => (await (await fetch(p)).json())", path)


def api_write(page: Page, method: str, path: str, body: Any = None) -> dict[str, Any]:
    """POST/PUT/DELETE with the CSRF token of the browser session: {status, json}."""
    return page.evaluate(FETCH, [method, path, body])


def set_locale(page: Page, locale: str) -> None:
    goto(page, f"/lang/{locale}", 300)


def expected_dir(locale: str) -> str:
    return "rtl" if locale.split("_")[0] in RTL_LOCALES else "ltr"


def set_theme(page: Page, theme: str) -> bool:
    """Switch light/dark the way ThemeController persists it; True when the page really changed.

    ThemeController (superset-frontend/src/theme/ThemeController.ts) stores the mode under the
    localStorage key 'superset-theme-mode' ('default' | 'dark' | 'system') and reads it on load.
    """
    mode = "dark" if theme == "dark" else "default"
    goto(page, "/welcome/", 300)
    page.evaluate("mode => localStorage.setItem('superset-theme-mode', mode)", mode)
    page.reload()
    settle(page, 800)
    return bool(page.evaluate(PROBE)["darkBackground"]) == (mode == "dark")


def resolve_ids(page: Page) -> dict[str, Any]:
    """Dashboard ids and one chart id per viz type, taken from the NxtBI dashboards themselves.

    /api/v1/chart/?q=(filters:(viz_type eq ..)) also matches the example charts and returned
    nothing useful for 'big_number' (the NxtBI KPIs are 'big_number' and 'big_number_total'),
    so the lookup goes through /api/v1/dashboard/<slug>/charts and form_data.viz_type.
    """
    ids: dict[str, Any] = {"charts": {}, "by_viz": {}}
    for key, slug in DASHBOARDS.items():
        ids[key] = slug
        ids[f"{key}_id"] = api(page, f"/api/v1/dashboard/{slug}")["result"]["id"]
        for chart in api(page, f"/api/v1/dashboard/{slug}/charts")["result"]:
            viz = chart["form_data"].get("viz_type")
            ids["charts"][chart["slice_name"]] = chart["id"]
            ids["by_viz"].setdefault(viz, chart["id"])
    by_viz = ids["by_viz"]
    ids.update({
        "bar": by_viz.get("echarts_timeseries_bar"), "table": by_viz.get("table"),
        "pivot": by_viz.get("pivot_table_v2"), "pie": by_viz.get("pie"),
        "big_number": by_viz.get("big_number") or by_viz.get("big_number_total"),
    })
    return ids


def copy_dashboard(page: Page, slug: str, title: str, metadata_patch: dict[str, Any] | None = None) -> int:
    """Server-side copy that shares the charts; returns the id of the copy."""
    source = api(page, f"/api/v1/dashboard/{slug}")["result"]
    metadata = json.loads(source.get("json_metadata") or "{}")
    metadata["positions"] = json.loads(source.get("position_json") or "{}")
    created = api_write(page, "POST", f"/api/v1/dashboard/{source['id']}/copy/",
                        {"dashboard_title": title, "json_metadata": json.dumps(metadata)})
    if created["status"] != 200:
        raise RuntimeError(f"dashboard copy failed: HTTP {created['status']}")
    copy_id = int(created["json"]["result"]["id"])
    if metadata_patch:
        copied = json.loads(api(page, f"/api/v1/dashboard/{copy_id}")["result"].get("json_metadata") or "{}")
        copied.update(metadata_patch)
        api_write(page, "PUT", f"/api/v1/dashboard/{copy_id}", {"json_metadata": json.dumps(copied)})
    return copy_id


def find_dashboards(page: Page, title: str) -> list[int]:
    query = f"(filters:!((col:dashboard_title,opr:eq,value:'{title}')),page_size:50)"
    return [row["id"] for row in api(page, f"/api/v1/dashboard/?q={query}").get("result", [])]


def delete_dashboard(page: Page, dashboard_id: int) -> int:
    return int(api_write(page, "DELETE", f"/api/v1/dashboard/{dashboard_id}")["status"])


def sqllab_open(page: Page) -> None:
    """SQL Lab with an editor tab whose database is the NxtBI warehouse."""
    goto(page, "/sqllab/", 2000)
    if page.locator(".ace_editor").count() == 0:
        page.locator("[data-test='add-tab-icon'], [aria-label='Add tab'], .ant-tabs-nav-add").first.click()
        page.wait_for_timeout(2500)
    selector = page.locator("[data-test='DatabaseSelector']").first
    if SQL_DATABASE not in selector.inner_text():
        selector.click()
        popover = page.locator(POPOVER).last
        popover.locator("[data-test='select-database'] input").click()
        page.locator(f"{SELECT_POPUP} .ant-select-item-option").filter(has_text=SQL_DATABASE).first.click()
        page.wait_for_timeout(800)
        popover.locator("button.ant-btn-primary").last.click()
        page.wait_for_timeout(1200)


def sqllab_run(page: Page, sql: str, wait_selector: str, timeout: int = 45_000) -> None:
    page.locator(".ace_editor textarea").first.focus()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.type(sql, delay=4)
    page.keyboard.press("Escape")  # close the autocomplete popup
    page.locator("[data-test='run-query-action']").first.click()
    page.locator(f"[data-test='south-pane'] {wait_selector}").first.wait_for(timeout=timeout)
    page.wait_for_timeout(800)


def open_right_menu(page: Page, key: str) -> None:
    """Hover one of the navbar menus on the inline-end side: new-dropdown, theme-sub-menu,
    language-submenu, settings."""
    page.locator(f"#main-menu [data-menu-id$='-{key}']").first.hover()
    page.locator(SUBMENU).last.wait_for(timeout=8000)
    page.wait_for_timeout(500)


def open_menu_item(page: Page, trigger: str, item_suffix: str) -> None:
    """Click a dropdown trigger, then the menu item whose data-menu-id ends with the key."""
    page.locator(trigger).first.click()
    page.locator(f"{DROPDOWN} li[data-menu-id$='{item_suffix}']").first.click()


def hover_chart_point(page: Page, canvas_selector: str) -> dict[str, float] | None:
    """Move over a chart until an ECharts tooltip with text shows; returns the pointer position."""
    canvas = page.locator(canvas_selector).first
    canvas.scroll_into_view_if_needed()
    page.wait_for_timeout(1200)
    box = canvas.bounding_box()
    if not box:
        return None
    for fx, fy in ((0.5, 0.5), (0.3, 0.4), (0.6, 0.3), (0.5, 0.7), (0.4, 0.6), (0.7, 0.5), (0.25, 0.25)):
        x, y = box["x"] + box["width"] * fx, box["y"] + box["height"] * fy
        page.mouse.move(x, y, steps=6)
        page.wait_for_timeout(500)
        shown = page.evaluate(
            "() => [...document.querySelectorAll('.echarts-tooltip')].some(e => e.innerText.trim() && "
            "getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0)")
        if shown:
            return {"x": x, "y": y}
    return None


# ----------------------------------------------------------------------------- screens

Action = Callable[[Page], "Page | None"]


def screens(ids: dict[str, Any], state: dict[str, Any]) -> list[tuple[str, str, Action, str]]:
    """(group, name, action, viewports). Each action leaves the page in the state to capture.

    viewports: 'all', or 'wide' for states driven by hover menus / side-by-side panels that do
    not exist in the phone layout (skipped there and reported as SKIP).
    """
    budget = f"/superset/dashboard/{ids['budget']}/"

    def at(path: str, wait: int = 1200) -> Action:
        def run(page: Page) -> None:
            goto(page, path, wait)
        return run

    def login_page(page: Page) -> Page:
        # a signed-out context: the locale is passed through /lang/<locale> of that session
        locale = page.evaluate("() => document.documentElement.lang || 'en'")
        browser: Browser = page.context.browser  # type: ignore[assignment]
        context = browser.new_context(viewport=page.viewport_size, locale="en-US")
        anonymous = context.new_page()
        goto(anonymous, f"/lang/{locale}", 300)
        goto(anonymous, "/login/", 800)
        return anonymous

    def right_menu(key: str, hover_item: str = "") -> Action:
        def run(page: Page) -> None:
            goto(page, "/welcome/")
            open_right_menu(page, key)
            if hover_item:
                page.locator(f"{SUBMENU} li[data-menu-id$='{hover_item}']").first.hover()
                page.wait_for_timeout(400)
        return run

    def list_filter_open(page: Page) -> None:
        goto(page, "/dashboard/list/", 1500)
        page.locator("[data-test='compact-filter-pill']").first.click()
        page.wait_for_timeout(900)

    def chart_cards_bulk(page: Page) -> None:
        goto(page, "/chart/list/", 1500)
        page.locator("[data-test='appstore']").first.click()
        page.wait_for_timeout(1200)
        page.locator("[data-test='bulk-select']").first.click()
        page.wait_for_timeout(700)

    def database_modal(page: Page) -> None:
        goto(page, "/databaseview/list/")
        page.locator("[data-test='btn-create-database'], button:has(.anticon-plus)").first.click()
        page.locator(MODAL).first.wait_for(timeout=10_000)
        page.wait_for_timeout(1200)

    def dataset_edit(page: Page) -> None:
        goto(page, "/tablemodelview/list/", 1500)
        page.locator("[data-test='dataset-row-edit']").first.click()
        page.locator(MODAL).first.wait_for(timeout=15_000)
        page.wait_for_timeout(2000)

    def alert_modal(page: Page) -> None:
        goto(page, "/alert/list/", 1500)
        page.locator("button:has([data-test='plus'])").first.click()
        page.locator(MODAL).first.wait_for(timeout=10_000)
        page.wait_for_timeout(1200)

    def dashboard_filters_collapsed(page: Page) -> None:
        goto(page, budget, 2500)
        page.locator("[data-test='filter-bar__collapse-button']").first.click()
        page.wait_for_timeout(900)

    def dashboard_filter_select_open(page: Page) -> None:
        goto(page, budget, 2500)
        page.locator("[data-test='filter-bar'] .ant-select").nth(1).click()
        page.locator(SELECT_POPUP).first.wait_for(timeout=8000)
        page.wait_for_timeout(800)

    def dashboard_chart_menu(page: Page) -> None:
        goto(page, budget, 2500)
        page.locator("[data-test='slice-header'] button[id$='-controls']").first.click()
        page.locator(DROPDOWN).first.wait_for(timeout=8000)
        page.wait_for_timeout(500)

    def dashboard_header_menu(page: Page) -> None:
        goto(page, budget, 2500)
        page.locator("[data-test='actions-trigger']").first.click()
        page.locator(DROPDOWN).first.wait_for(timeout=8000)
        page.wait_for_timeout(500)

    def dashboard_filter_config(page: Page) -> None:
        goto(page, budget, 2500)
        open_menu_item(page, "[data-test='filterbar-orientation-icon']", "add-edit-filters-menu-key")
        page.locator(MODAL).first.wait_for(timeout=15_000)
        page.wait_for_timeout(1500)

    def dashboard_edit(page: Page) -> None:
        goto(page, budget, 2500)
        page.locator("[data-test='edit-dashboard-button']").click()
        page.locator("[data-test='dashboard-builder-sidepane']").wait_for(timeout=15_000)
        page.wait_for_timeout(1500)

    def dashboard_edit_selected(page: Page) -> None:
        dashboard_edit(page)
        page.locator("[data-test='dashboard-markdown-editor']").first.click()
        page.locator(".with-popover-menu--focused").first.wait_for(timeout=8000)
        page.locator("[data-test='chart-grid-component']").first.hover()  # hover menu + resize handles
        page.wait_for_timeout(600)

    def dashboard_properties(page: Page) -> None:
        dashboard_edit(page)
        open_menu_item(page, "[data-test='actions-trigger']", "edit_properties")
        page.locator(MODAL).first.wait_for(timeout=15_000)
        page.wait_for_timeout(1500)

    def dashboard_horizontal(page: Page) -> None:
        if "copy" not in state:
            for stale in find_dashboards(page, AUDIT_COPY_TITLE):
                delete_dashboard(page, stale)
            state["copy"] = copy_dashboard(page, ids["budget"], AUDIT_COPY_TITLE,
                                           {"filter_bar_orientation": "HORIZONTAL"})
        size = page.viewport_size or VIEWPORTS["desktop"]
        page.set_viewport_size({"width": min(size["width"], 1024), "height": size["height"]})  # force overflow
        try:
            goto(page, f"/superset/dashboard/{state['copy']}/", 3000)
        finally:
            state["restore_viewport"] = size

    def explore(key: str) -> Action:
        return at(f"/explore/?slice_id={ids[key]}", 3500)

    def explore_tooltip(page: Page) -> None:
        explore("bar")(page)
        if hover_chart_point(page, "[data-test='chart-container'] canvas") is None:
            raise RuntimeError("no ECharts tooltip appeared on hover")

    def explore_metric_popover(page: Page) -> None:
        explore("bar")(page)
        page.locator("[data-test='metrics'] [data-test='option-label'], [data-test='metric'] [data-test='option-label']").first.click()
        page.locator(POPOVER).first.wait_for(timeout=8000)
        page.wait_for_timeout(800)

    def explore_time_range(page: Page) -> None:
        explore("bar")(page)
        page.locator("[data-test='adhoc_filters'] [data-test='option-label']").first.click()
        page.locator(f"{POPOVER} [data-test='time-range-trigger']").first.click()
        page.wait_for_timeout(1200)

    def explore_data_pane(page: Page) -> None:
        explore("bar")(page)
        expand = page.locator("button:has(> span.anticon-down)")  # 'Expand data panel'
        if expand.count():  # the pane remembers its state: absent when it is already open
            expand.last.click()
        page.locator("[data-test='chart-container'] ~ * .ag-root-wrapper, .ag-root-wrapper").first.wait_for(timeout=15_000)
        page.wait_for_timeout(1200)

    def explore_save_modal(page: Page) -> None:
        explore("bar")(page)
        page.locator("[data-test='query-save-button']").click()
        page.locator(MODAL).first.wait_for(timeout=10_000)
        page.wait_for_timeout(1000)

    def explore_properties(page: Page) -> None:
        explore("bar")(page)
        open_menu_item(page, "[data-test='actions-trigger']", "edit_properties")
        page.locator(MODAL).first.wait_for(timeout=10_000)
        page.wait_for_timeout(1200)

    def sqllab_editor(page: Page) -> None:
        sqllab_open(page)
        page.locator(".ace_editor textarea").first.focus()
        page.keyboard.press("Control+A")
        page.keyboard.type(SQL_OK, delay=4)
        page.wait_for_timeout(600)

    def sqllab_results(page: Page) -> None:
        sqllab_open(page)
        sqllab_run(page, SQL_OK, ".ag-root-wrapper")

    def sqllab_error(page: Page) -> None:
        sqllab_open(page)
        sqllab_run(page, SQL_BAD, ".ant-alert-error")

    def sqllab_history_tab(page: Page) -> None:
        sqllab_open(page)
        page.locator("[data-test='south-pane'] .ant-tabs-tab").nth(1).click()
        page.wait_for_timeout(1500)

    def query_preview(page: Page) -> None:
        goto(page, "/sqllab/history/", 1500)
        page.locator("[data-test='open-sql-preview-0']").first.click()
        page.locator(MODAL).first.wait_for(timeout=10_000)
        page.wait_for_timeout(800)

    return [
        ("shell", "login", login_page, "all"),
        ("shell", "welcome", at("/welcome/"), "all"),
        ("shell", "settings-menu", right_menu("settings"), "wide"),
        ("shell", "user-menu", right_menu("settings", "logout"), "wide"),
        ("shell", "language-picker", right_menu("language-submenu"), "wide"),
        ("shell", "theme-menu", right_menu("theme-sub-menu"), "wide"),
        ("shell", "new-menu", right_menu("new-dropdown"), "wide"),
        ("shell", "dashboard-list", at("/dashboard/list/"), "all"),
        ("shell", "dashboard-list-filter-open", list_filter_open, "all"),
        ("shell", "chart-list-cards-bulk-select", chart_cards_bulk, "all"),
        ("shell", "dataset-list", at("/tablemodelview/list/"), "all"),
        ("shell", "database-list", at("/databaseview/list/"), "all"),
        ("shell", "database-modal", database_modal, "all"),
        ("shell", "dataset-edit-modal", dataset_edit, "all"),
        ("shell", "users-list", at("/users/"), "all"),
        ("shell", "roles-list", at("/roles/"), "all"),
        ("shell", "rls-list", at("/rowlevelsecurity/list/"), "all"),
        ("shell", "alerts-list", at("/alert/list/"), "all"),
        ("shell", "alert-report-modal", alert_modal, "all"),
        ("shell", "themes-list", at("/theme/list/"), "all"),
        ("shell", "css-templates-list", at("/csstemplatemodelview/list/"), "all"),
        ("shell", "not-found", at("/this-page-does-not-exist/"), "all"),
        ("dashboard", "dashboard-view", at(budget, 3000), "all"),
        ("dashboard", "dashboard-filter-bar-collapsed", dashboard_filters_collapsed, "wide"),
        ("dashboard", "dashboard-filter-select-open", dashboard_filter_select_open, "wide"),
        ("dashboard", "dashboard-chart-menu", dashboard_chart_menu, "wide"),
        ("dashboard", "dashboard-header-menu", dashboard_header_menu, "all"),
        ("dashboard", "dashboard-filter-config-modal", dashboard_filter_config, "wide"),
        ("dashboard", "dashboard-edit-mode", dashboard_edit, "wide"),
        ("dashboard", "dashboard-edit-selected-component", dashboard_edit_selected, "wide"),
        ("dashboard", "dashboard-properties-modal", dashboard_properties, "wide"),
        ("dashboard", "dashboard-horizontal-filter-bar", dashboard_horizontal, "wide"),
        ("dashboard", "dashboard-tabs", at(f"/superset/dashboard/{ids['trade']}/", 3000), "all"),
        ("dashboard", "dashboard-service-table", at(f"/superset/dashboard/{ids['service']}/", 3000), "all"),
        ("dashboard", "dashboard-standalone", at(f"{budget}?standalone=3", 3000), "all"),
        ("explore", "explore-bar", explore("bar"), "all"),
        ("explore", "explore-bar-tooltip", explore_tooltip, "wide"),
        ("explore", "explore-metric-popover", explore_metric_popover, "wide"),
        ("explore", "explore-time-range", explore_time_range, "wide"),
        ("explore", "explore-data-pane", explore_data_pane, "wide"),
        ("explore", "explore-save-modal", explore_save_modal, "all"),
        ("explore", "explore-properties-modal", explore_properties, "all"),
        ("explore", "explore-table", explore("table"), "all"),
        ("explore", "explore-pivot", explore("pivot"), "all"),
        ("explore", "explore-pie", explore("pie"), "all"),
        ("explore", "explore-big-number", explore("big_number"), "all"),
        ("sqllab", "sqllab-editor", sqllab_editor, "wide"),
        ("sqllab", "sqllab-results", sqllab_results, "wide"),
        ("sqllab", "sqllab-error", sqllab_error, "wide"),
        ("sqllab", "sqllab-history-tab", sqllab_history_tab, "wide"),
        ("sqllab", "query-history", at("/sqllab/history/", 1500), "all"),
        ("sqllab", "query-history-sql-preview", query_preview, "all"),
        ("sqllab", "saved-queries", at("/savedqueryview/list/", 1500), "all"),
    ]


def probe_issues(probe: dict[str, Any], want_dir: str, name: str) -> list[str]:
    issues = []
    if probe["dir"] != want_dir:
        if name == "not-found":
            # Flask serves superset/static/assets/404.html for unmatched URLs (error_handling.py,
            # show_http_exception): a static file outside spa.html, so no locale, lang or dir.
            issues.append(f"404 page is a static file served outside spa.html: html dir={probe['dir']!r}, "
                          f"lang={probe['lang']!r} (expected dir={want_dir!r})")
        else:
            issues.append(f"html dir={probe['dir']!r}, expected {want_dir!r}")
    if probe["hscroll"]:
        issues.append(f"horizontal page scroll ({probe['scrollWidth']} > {probe['clientWidth']})")
    if probe["offscreen"]:
        issues.append(f"offscreen: {probe['offscreen'][:3]}")
    if probe["editorsRtl"]:
        issues.append(f"{probe['editorsRtl']} code editor(s) rendered RTL")
    if probe["canvasesRtl"]:
        issues.append(f"{probe['canvasesRtl']} of {probe['canvases']} canvases inherit RTL")
    if probe["codeRtl"]:
        issues.append(f"code text rendered RTL: {probe['codeRtl'][:3]}")
    if probe["headerOverlaps"]:
        issues.append(f"overlapping header controls: {probe['headerOverlaps'][:3]}")
    if probe["headerClipped"]:
        issues.append(f"header controls outside their bar: {probe['headerClipped'][:3]}")
    if probe["bidi"]:
        issues.append(f"bidi reordering: {probe['bidi'][:4]}")
    if want_dir == "rtl" and probe["logoSide"] == "left" and probe["clientWidth"] > 800:
        issues.append("brand logo is on the left in RTL")
    if want_dir == "ltr" and probe["rtlStyleClasses"]:
        issues.append(f"{probe['rtlStyleClasses']} elements still carry a superset-rtl- class in LTR")
    return issues


def compare_images(current: Path, baseline: Path) -> float:
    from PIL import Image, ImageChops  # noqa: PLC0415 - optional dependency

    a, b = Image.open(current).convert("RGB"), Image.open(baseline).convert("RGB")
    if a.size != b.size:
        return 1.0
    diff = ImageChops.difference(a, b).convert("L")
    changed = sum(diff.histogram()[25:])
    return changed / (a.size[0] * a.size[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--locales", default="ar,en")
    parser.add_argument("--themes", default="light", help="light,dark")
    parser.add_argument("--viewports", default="desktop", help=",".join(VIEWPORTS))
    parser.add_argument("--only", default="", help="comma separated groups or screen-name substrings")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.02, help="max changed-pixel ratio for --compare")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    only = [x for x in args.only.split(",") if x]
    results: list[dict[str, Any]] = []
    OUT.mkdir(parents=True, exist_ok=True)

    def emit(record: dict[str, Any]) -> None:
        results.append(record)
        print(f"[{record['status']:5}] {record['locale']} {record['theme']} {record['viewport']} "
              f"{record['screen']}: {'; '.join(record['issues'])[:260]}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        for viewport in args.viewports.split(","):
            context = browser.new_context(viewport=VIEWPORTS[viewport], locale="en-US")
            context.set_default_timeout(15_000)
            page = context.new_page()
            console_errors: list[str] = []
            page.on("console", lambda m: console_errors.append(m.text[:160]) if m.type == "error" else None)
            login(page)
            ids = resolve_ids(page)
            state: dict[str, Any] = {}
            try:
                for locale in args.locales.split(","):
                    set_locale(page, locale)
                    for theme in args.themes.split(","):
                        base = {"locale": locale, "theme": theme, "viewport": viewport}
                        if not set_theme(page, theme):
                            emit({**base, "group": "shell", "screen": "theme-switch", "status": "ERROR",
                                  "issues": [f"theme {theme!r} was not applied (localStorage superset-theme-mode)"]})
                            continue
                        folder = OUT / f"{locale}-{theme}-{viewport}"
                        folder.mkdir(parents=True, exist_ok=True)
                        if not only:
                            for stale in folder.glob("*.png"):
                                stale.unlink()
                        want_dir = expected_dir(locale)
                        for group, name, action, where in screens(ids, state):
                            if only and not any(o == group or o in name for o in only):
                                continue
                            record: dict[str, Any] = {**base, "group": group, "screen": name}
                            if where == "wide" and viewport == "mobile":
                                emit({**record, "status": "SKIP", "issues": ["state does not exist in the phone layout"]})
                                continue
                            console_errors.clear()
                            target: Page | None = None
                            try:
                                target = action(page) or page
                                shot = folder / f"{name}.png"
                                target.screenshot(path=str(shot))
                                probe = target.evaluate(PROBE)
                                issues = probe_issues(probe, want_dir, name)
                                if (theme == "dark") != bool(probe["darkBackground"]) and name not in ("login", "not-found"):
                                    issues.append(f"page background does not match theme {theme!r}")
                                record.update({"status": "WARN" if issues else "OK", "issues": issues, "probe": probe,
                                               "screenshot": str(shot.relative_to(ROOT)).replace("\\", "/"),
                                               "console_errors": sorted(set(console_errors))[:5]})
                                if args.compare or args.update_baseline:
                                    reference = BASELINE / shot.relative_to(OUT)
                                    if args.update_baseline:
                                        reference.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.copyfile(shot, reference)
                                    elif reference.exists():
                                        ratio = compare_images(shot, reference)
                                        record["visual_diff"] = round(ratio, 4)
                                        if ratio > args.threshold:
                                            record["status"] = "DIFF"
                                            record["issues"].append(f"visual diff {ratio:.1%} > {args.threshold:.0%}")
                                    else:
                                        record["issues"].append("no baseline")
                            except Exception as exc:  # noqa: BLE001
                                record.update({"status": "ERROR",
                                               "issues": [f"{type(exc).__name__}: {str(exc)[:200]}"]})
                                try:
                                    page.screenshot(path=str(folder / f"{name}.error.png"))
                                except Exception:  # noqa: BLE001
                                    pass
                            finally:
                                if target is not None and target is not page:
                                    target.context.close()
                                if "restore_viewport" in state:
                                    page.set_viewport_size(state.pop("restore_viewport"))
                                try:
                                    page.keyboard.press("Escape")
                                    page.mouse.move(5, 5)
                                except Exception:  # noqa: BLE001
                                    pass
                            emit(record)
            finally:
                try:
                    if "copy" in state:
                        delete_dashboard(page, state["copy"])
                    page.evaluate("() => localStorage.setItem('superset-theme-mode', 'default')")
                    set_locale(page, "en")
                except Exception as exc:  # noqa: BLE001
                    print(f"cleanup failed: {type(exc).__name__}: {str(exc)[:160]}")
                context.close()
        browser.close()

    # results.json accumulates: a run replaces only the records of the screens it visited
    key = lambda r: (r["locale"], r["theme"], r["viewport"], r["screen"])  # noqa: E731
    visited = {key(r) for r in results}
    try:
        earlier = [r for r in json.loads((OUT / "results.json").read_text(encoding="utf-8")) if key(r) not in visited]
    except (OSError, ValueError, KeyError):
        earlier = []
    (OUT / "results.json").write_text(json.dumps(earlier + results, indent=2, ensure_ascii=False), encoding="utf-8")
    bad = [r for r in results if r["status"] in ("ERROR", "DIFF")]
    warn = [r for r in results if r["status"] == "WARN"]
    skipped = [r for r in results if r["status"] == "SKIP"]
    print(f"\n{len(results)} screens: {len(results) - len(bad) - len(warn) - len(skipped)} ok, "
          f"{len(warn)} with layout warnings, {len(skipped)} skipped, {len(bad)} errors/diffs "
          f"-> {OUT / 'results.json'}")
    return 1 if bad or (args.compare and warn) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

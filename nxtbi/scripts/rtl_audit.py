"""RTL / LTR visual audit and regression check for the NxtBI Superset fork.

    python nxtbi/scripts/rtl_audit.py                       # ar + en, light, desktop
    python nxtbi/scripts/rtl_audit.py --locales ar --only dashboard,explore
    python nxtbi/scripts/rtl_audit.py --themes light,dark --viewports desktop,mobile
    python nxtbi/scripts/rtl_audit.py --update-baseline      # accept the current screenshots
    python nxtbi/scripts/rtl_audit.py --compare              # fail on visual drift from the baseline

Signs in through Keycloak (credentials from nxtbi/.env, never printed), walks the main
screens in every requested locale x theme x viewport, takes a screenshot of each state and
records layout probes that catch the usual right-to-left defects without a human looking:

  * <html dir/lang> matches the locale
  * no horizontal page scrollbar
  * visible elements pushed outside the viewport
  * the direction actually applied to code editors and chart canvases (must stay LTR)

Screenshots: nxtbi/out/rtl-audit/<locale>-<theme>-<viewport>/NN-name.png
Results:     nxtbi/out/rtl-audit/results.json
Baseline:    nxtbi/tests/rtl-visual/baseline/...   (--update-baseline / --compare, needs Pillow)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Page, sync_playwright

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

PROBE = r"""
() => {
  const de = document.documentElement;
  const vw = de.clientWidth;
  const offscreen = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) continue;
    if (r.right < -2 || r.left > vw + 2) {
      // ignore things that are clipped by a scrolling ancestor on purpose
      let clipped = false;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ps = getComputedStyle(p);
        if (/(auto|scroll|hidden|clip)/.test(ps.overflowX)) { clipped = true; break; }
      }
      if (!clipped && offscreen.length < 6) {
        offscreen.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)} [${Math.round(r.left)},${Math.round(r.right)}]`);
      }
    }
  }
  const dirOf = sel => Array.from(document.querySelectorAll(sel)).slice(0, 40).map(e => getComputedStyle(e).direction);
  const count = (arr, v) => arr.filter(x => x === v).length;
  const editors = dirOf('.ace_editor, .monaco-editor');
  const canvases = dirOf('canvas');
  const logo = document.querySelector('.navbar-brand, a[class*="brand"], header img');
  const logoRect = logo ? logo.getBoundingClientRect() : null;
  return {
    dir: de.getAttribute('dir'), lang: de.getAttribute('lang'),
    hscroll: de.scrollWidth > de.clientWidth + 1, scrollWidth: de.scrollWidth, clientWidth: de.clientWidth,
    offscreen,
    editors: editors.length, editorsRtl: count(editors, 'rtl'),
    canvases: canvases.length, canvasesRtl: count(canvases, 'rtl'),
    rtlStyleClasses: document.querySelectorAll('[class*="superset-rtl-"]').length,
    antRtl: document.querySelectorAll('[class*="-rtl"]').length,
    logoSide: logoRect ? (logoRect.left + logoRect.width / 2 < vw / 2 ? 'left' : 'right') : null,
    errors: document.querySelectorAll('.ant-alert-error').length,
  };
}
"""


def settle(page: Page, extra_ms: int = 1200) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:  # noqa: BLE001 - long polling pages never go idle
        pass
    page.wait_for_timeout(extra_ms)


def login(page: Page) -> None:
    page.goto(f"{SUPERSET}/login/")
    settle(page, 400)
    page.get_by_text(re.compile("keycloak", re.I)).first.click()
    page.wait_for_url(re.compile(r"/realms/"))
    page.fill("#username", ENV.get("NXTBI_PLATFORM_ADMINS", "superset.admin@nxtbi.local").split(",")[0])
    if page.locator("#password").count() == 0:
        page.locator("#kc-login").click()
        page.wait_for_selector("#password")
    page.fill("#password", ENV["SUPERSET_SSO_ADMIN_PASSWORD"])
    page.locator("#kc-login").click()
    page.wait_for_url(re.compile(re.escape(SUPERSET)), timeout=30_000)
    settle(page, 400)


def api(page: Page, path: str) -> Any:
    return page.evaluate("async p => (await (await fetch(p)).json())", path)


def chart_id(page: Page, viz_type: str) -> int | None:
    q = f"(filters:!((col:viz_type,opr:eq,value:{viz_type})),order_column:id,order_direction:desc,page_size:1)"
    result = api(page, f"/api/v1/chart/?q={q}").get("result", [])
    return result[0]["id"] if result else None


def screens(ids: dict[str, Any]) -> list[tuple[str, str, Callable[[Page], None]]]:
    """(group, name, action). Each action leaves the page in the state to capture."""

    def goto(path: str, wait: int = 1200) -> Callable[[Page], None]:
        def run(page: Page) -> None:
            page.goto(f"{SUPERSET}{path}")
            settle(page, wait)
        return run

    def settings_menu(page: Page) -> None:
        goto("/welcome/")(page)
        page.locator("[data-test='right-menu'] .ant-menu-submenu-title, [class*='RightMenu'] .ant-menu-submenu-title").last.hover()
        page.wait_for_timeout(700)

    def dashboard_filters_collapsed(page: Page) -> None:
        goto(f"/superset/dashboard/{ids['dashboard']}/", 2500)(page)
        page.locator("[data-test='filter-bar__collapse-button']").first.click()
        page.wait_for_timeout(900)

    def dashboard_chart_menu(page: Page) -> None:
        goto(f"/superset/dashboard/{ids['dashboard']}/", 2500)(page)
        page.locator("[data-test='dashboard-slice-menu-trigger'], [aria-label='More Options']").first.click()
        page.wait_for_timeout(700)

    def dashboard_filter_select_open(page: Page) -> None:
        goto(f"/superset/dashboard/{ids['dashboard']}/", 2500)(page)
        page.locator("[data-test='filter-control-name']").nth(1).locator("xpath=ancestor::*[.//input][1]").locator("input").first.click()
        page.wait_for_timeout(1200)

    def explore_metric_popover(page: Page) -> None:
        goto(f"/explore/?slice_id={ids['bar']}", 3000)(page)
        page.locator("[data-test='metrics'] [data-test='option-label'], [data-test='metric'] [data-test='option-label']").first.click()
        page.wait_for_timeout(1000)

    def explore_time_range(page: Page) -> None:
        goto(f"/explore/?slice_id={ids['bar']}", 3000)(page)
        page.locator("[data-test='time-range-trigger']").first.click()
        page.wait_for_timeout(1000)

    def explore_tooltip(page: Page) -> None:
        goto(f"/explore/?slice_id={ids['bar']}", 3500)(page)
        box = page.locator("canvas").first.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.5)
            page.wait_for_timeout(900)

    def sqllab_query(page: Page) -> None:
        goto("/sqllab/", 2000)(page)
        if page.locator(".ace_editor").count() == 0:
            page.locator("[data-test='add-tab-icon'], [aria-label='Add tab'], .ant-tabs-nav-add").first.click()
            page.wait_for_timeout(2500)
        editor = page.locator(".ace_editor textarea").first
        editor.focus()
        page.keyboard.press("Control+A")
        page.keyboard.type("SELECT sector_en, sector_ar, sum(spent_amount) AS spent FROM nxtbi.budget_execution GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20")
        page.wait_for_timeout(600)

    def database_modal(page: Page) -> None:
        goto("/databaseview/list/")(page)
        page.locator("[data-test='btn-create-database'], button:has(.anticon-plus)").first.click()
        page.wait_for_timeout(1500)

    def dataset_edit(page: Page) -> None:
        goto("/tablemodelview/list/", 1500)(page)
        page.locator("[data-test='edit-alt'], [aria-label='Edit'], [data-test='dataset-row-action-edit']").first.click()
        page.wait_for_timeout(2500)

    def chart_cards_bulk(page: Page) -> None:
        goto("/chart/list/", 1500)(page)
        page.locator("[data-test='bulk-select']").first.click()
        page.wait_for_timeout(700)

    def language_picker(page: Page) -> None:
        goto("/welcome/")(page)
        page.locator("[class*='LanguagePicker'], [aria-label='Languages'], .f16").first.hover()
        page.wait_for_timeout(700)

    return [
        ("shell", "welcome", goto("/welcome/")),
        ("shell", "settings-menu", settings_menu),
        ("shell", "language-picker", language_picker),
        ("shell", "dashboard-list", goto("/dashboard/list/")),
        ("shell", "chart-list-bulk-select", chart_cards_bulk),
        ("shell", "dataset-list", goto("/tablemodelview/list/")),
        ("shell", "database-list", goto("/databaseview/list/")),
        ("shell", "database-modal", database_modal),
        ("shell", "dataset-edit-modal", dataset_edit),
        ("shell", "users-list", goto("/users/")),
        ("shell", "roles-list", goto("/roles/")),
        ("shell", "rls-list", goto("/rowlevelsecurity/list/")),
        ("shell", "alerts-list", goto("/alert/list/")),
        ("shell", "not-found", goto("/this-page-does-not-exist/")),
        ("dashboard", "dashboard-view", goto(f"/superset/dashboard/{ids['dashboard']}/", 3000)),
        ("dashboard", "dashboard-filter-bar-collapsed", dashboard_filters_collapsed),
        ("dashboard", "dashboard-filter-select-open", dashboard_filter_select_open),
        ("dashboard", "dashboard-chart-menu", dashboard_chart_menu),
        ("dashboard", "dashboard-edit-mode", goto(f"/superset/dashboard/{ids['dashboard']}/?edit=true", 3500)),
        ("dashboard", "dashboard-tabs", goto(f"/superset/dashboard/{ids['dashboard_tabs']}/", 3000)),
        ("dashboard", "dashboard-service-table", goto(f"/superset/dashboard/{ids['dashboard_table']}/", 3000)),
        ("dashboard", "dashboard-standalone", goto(f"/superset/dashboard/{ids['dashboard']}/?standalone=3", 3000)),
        ("explore", "explore-bar", goto(f"/explore/?slice_id={ids['bar']}", 3500)),
        ("explore", "explore-bar-tooltip", explore_tooltip),
        ("explore", "explore-metric-popover", explore_metric_popover),
        ("explore", "explore-time-range", explore_time_range),
        ("explore", "explore-table", goto(f"/explore/?slice_id={ids['table']}", 3500)),
        ("explore", "explore-pivot", goto(f"/explore/?slice_id={ids['pivot']}", 3500)),
        ("explore", "explore-pie", goto(f"/explore/?slice_id={ids['pie']}", 3500)),
        ("explore", "explore-big-number", goto(f"/explore/?slice_id={ids['big_number']}", 3500)),
        ("sqllab", "sqllab-editor", sqllab_query),
        ("sqllab", "sqllab-history", goto("/sqllab/history/", 1500)),
        ("sqllab", "saved-queries", goto("/savedqueryview/list/", 1500)),
    ]


def set_theme(page: Page, theme: str) -> None:
    page.evaluate(
        """mode => { for (const k of Object.keys(localStorage)) { if (/theme.?mode/i.test(k)) localStorage.setItem(k, mode); }
                      localStorage.setItem('superset-theme-mode', mode); }""",
        "dark" if theme == "dark" else "default",
    )


def compare_images(current: Path, baseline: Path) -> float:
    from PIL import Image, ImageChops  # noqa: PLC0415 - optional dependency

    a, b = Image.open(current).convert("RGB"), Image.open(baseline).convert("RGB")
    if a.size != b.size:
        return 1.0
    diff = ImageChops.difference(a, b).convert("L")
    changed = sum(1 for px in diff.getdata() if px > 24)
    return changed / (a.size[0] * a.size[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--locales", default="ar,en")
    parser.add_argument("--themes", default="light")
    parser.add_argument("--viewports", default="desktop")
    parser.add_argument("--only", default="", help="comma separated groups or screen-name substrings")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.02, help="max changed-pixel ratio for --compare")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    only = [x for x in args.only.split(",") if x]
    results: list[dict[str, Any]] = []
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        for viewport in args.viewports.split(","):
            context = browser.new_context(viewport=VIEWPORTS[viewport], locale="en-US")
            page = context.new_page()
            console_errors: list[str] = []
            page.on("console", lambda m: console_errors.append(m.text[:160]) if m.type == "error" else None)
            login(page)
            ids = {
                "dashboard": "nxtbi-budget-execution", "dashboard_tabs": "nxtbi-trade-population",
                "dashboard_table": "nxtbi-service-operations",
                "bar": chart_id(page, "echarts_timeseries_bar"), "table": chart_id(page, "table"),
                "pivot": chart_id(page, "pivot_table_v2"), "pie": chart_id(page, "pie"),
                "big_number": chart_id(page, "big_number"),
            }
            for locale in args.locales.split(","):
                page.goto(f"{SUPERSET}/lang/{locale}")
                for theme in args.themes.split(","):
                    page.goto(f"{SUPERSET}/welcome/")
                    set_theme(page, theme)
                    folder = OUT / f"{locale}-{theme}-{viewport}"
                    folder.mkdir(parents=True, exist_ok=True)
                    expected_dir = "rtl" if locale.split("_")[0] in RTL_LOCALES else "ltr"
                    for index, (group, name, action) in enumerate(screens(ids), start=1):
                        if only and not any(o == group or o in name for o in only):
                            continue
                        record: dict[str, Any] = {"locale": locale, "theme": theme, "viewport": viewport,
                                                  "group": group, "screen": name}
                        console_errors.clear()
                        try:
                            action(page)
                            shot = folder / f"{index:02d}-{name}.png"
                            page.screenshot(path=str(shot))
                            probe = page.evaluate(PROBE)
                            issues = []
                            if probe["dir"] != expected_dir:
                                issues.append(f"html dir={probe['dir']!r}, expected {expected_dir!r}")
                            if probe["hscroll"]:
                                issues.append(f"horizontal page scroll ({probe['scrollWidth']} > {probe['clientWidth']})")
                            if probe["offscreen"]:
                                issues.append(f"offscreen: {probe['offscreen'][:3]}")
                            if probe["editorsRtl"]:
                                issues.append(f"{probe['editorsRtl']} code editor(s) rendered RTL")
                            if probe["canvasesRtl"]:
                                issues.append(f"{probe['canvasesRtl']} of {probe['canvases']} canvases inherit RTL")
                            if expected_dir == "rtl" and probe["logoSide"] == "left":
                                issues.append("brand logo is on the left in RTL")
                            record.update({"status": "WARN" if issues else "OK", "issues": issues, "probe": probe,
                                           "screenshot": str(shot.relative_to(ROOT)).replace("\\", "/"),
                                           "console_errors": sorted(set(console_errors))[:5]})
                            if args.compare or args.update_baseline:
                                base = BASELINE / shot.relative_to(OUT)
                                if args.update_baseline:
                                    base.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copyfile(shot, base)
                                elif base.exists():
                                    ratio = compare_images(shot, base)
                                    record["visual_diff"] = round(ratio, 4)
                                    if ratio > args.threshold:
                                        record["status"] = "DIFF"
                                        record["issues"].append(f"visual diff {ratio:.1%} > {args.threshold:.0%}")
                                else:
                                    record["issues"].append("no baseline")
                        except Exception as exc:  # noqa: BLE001
                            record.update({"status": "ERROR", "issues": [f"{type(exc).__name__}: {str(exc)[:200]}"]})
                        results.append(record)
                        print(f"[{record['status']:5}] {locale} {theme} {viewport} {name}: {'; '.join(record['issues'])[:220]}")
            page.goto(f"{SUPERSET}/lang/en")
            context.close()
        browser.close()

    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    bad = [r for r in results if r["status"] in ("ERROR", "DIFF")]
    warn = [r for r in results if r["status"] == "WARN"]
    print(f"\n{len(results)} screens: {len(results) - len(bad) - len(warn)} ok, {len(warn)} with layout warnings, "
          f"{len(bad)} errors/diffs -> {OUT / 'results.json'}")
    return 1 if bad or (args.compare and warn) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

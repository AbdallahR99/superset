# NxtBI RTL tests against the running stack

Two host-side scripts drive a real Chromium (Playwright) against the demo stack at
`SUPERSET_PUBLIC_URL` (default `http://localhost:8088`). They sign in through Keycloak with the
platform admin from `nxtbi/.env` (never printed) and test whatever build is deployed.

| Script | Purpose | Output |
|---|---|---|
| `nxtbi/scripts/rtl_audit.py` | walks 53 screens/states per locale x theme x viewport, screenshot + layout probes, optional visual baseline | `nxtbi/out/rtl-audit/` |
| `nxtbi/scripts/rtl_e2e.py` | functional checks with geometry assertions, PASS / FAIL / SKIP | `nxtbi/out/rtl-e2e-results.json` |

Requirements (once): `pip install playwright pillow` and `playwright install chromium`.
`nxtbi/out/` is git-ignored.

## 1. Visual audit: `rtl_audit.py`

```bash
python nxtbi/scripts/rtl_audit.py                                  # ar + en, light, desktop (about 12 min)
python nxtbi/scripts/rtl_audit.py --locales ar --only dashboard,explore
python nxtbi/scripts/rtl_audit.py --locales ar --themes dark
python nxtbi/scripts/rtl_audit.py --viewports mobile               # also: tablet (1024px)
python nxtbi/scripts/rtl_audit.py --only sqllab-results --headed   # watch one state
```

- Screenshots: `nxtbi/out/rtl-audit/<locale>-<theme>-<viewport>/<screen>.png`
  (`<screen>.error.png` when the state could not be reached).
- `nxtbi/out/rtl-audit/results.json` accumulates: a run replaces only the records of the
  combinations and screens it visited. Delete the file for a clean slate.
- Status per screen: `OK`, `WARN` (a probe found something), `ERROR` (the state could not be
  reached: selector or product problem), `SKIP` (hover menus and side-by-side panels are not
  visited in the phone layout), `DIFF` (`--compare` only). Exit code 1 on `ERROR` / `DIFF`, and
  on `WARN` too when `--compare` is given.

Probes recorded for every screen (`probe` in results.json):

| Probe | Reported when |
|---|---|
| `dir`, `lang` | `<html>` does not match the locale |
| `hscroll`, `offscreen` | the page scrolls horizontally / a visible element sits outside the viewport and no ancestor clips it |
| `editorsRtl`, `canvasesRtl` | an Ace/Monaco editor or a chart canvas computes `direction: rtl` |
| `codeRtl` | a `<pre>`, `<code>`, or an input/textarea holding SQL, a URI, JSON, CSS (by name, placeholder or value) computes `direction: rtl` |
| `headerOverlaps`, `headerClipped` | two controls of the navbar or the dashboard / chart header intersect, or one leaves its bar |
| `bidi` | measured reordering of left-to-right text in an RTL context: `sign:` "-5" painted as "5-", `number-word:` "4 options" painted as "options 4", `punctuation:` "Loading." painted as ".Loading" (untranslated strings, or user text without `dir="auto"`) |
| `logoSide` | the brand is on the left on a wide RTL page |
| `rtlStyleClasses` | an element still carries a `superset-rtl-` class on an LTR page |
| `darkBackground` | the page background does not match the requested theme |

Things worth knowing:

- `--themes dark` writes `localStorage['superset-theme-mode'] = 'dark'` (the key
  `ThemeController` reads on load), reloads and verifies the background really is dark; a
  theme that does not apply is reported as an `ERROR` record named `theme-switch`.
- The `not-found` screen always warns: an unmatched URL is answered by Flask with the static
  file `superset/static/assets/404.html` (`superset/views/error_handling.py`,
  `show_http_exception`), which is not rendered through `spa.html`, so it carries no locale,
  `lang="en"` and no `dir`.
- The horizontal filter bar needs a saved dashboard setting, so that screen runs on a temporary
  copy ("RTL audit tmp (horizontal filter bar)") created through the API and deleted at the end.
  The three NxtBI dashboards are never modified.
- The SQL Lab screens select the "NxtBI Demo" database in the admin's current SQL Lab tab and
  leave a query text in it.

### Visual baseline

The baseline is a copy of the audit screenshots under `nxtbi/tests/rtl-visual/baseline/`, with
the same `<locale>-<theme>-<viewport>/<screen>.png` layout. It is committed, the `out/` folder
is not.

```bash
python nxtbi/scripts/rtl_audit.py --update-baseline     # accept the current screenshots as the baseline
python nxtbi/scripts/rtl_audit.py --compare             # fail when a screen drifts from the baseline
python nxtbi/scripts/rtl_audit.py --compare --threshold 0.05 --only dashboard
```

- `--update-baseline` copies every screenshot of the run into the baseline folder (use the same
  `--locales/--themes/--viewports/--only` selection you intend to compare later).
- `--compare` computes, per screen, the share of pixels whose grey-level difference from the
  baseline exceeds 24/255. Above `--threshold` (default 2 %) the screen is marked `DIFF`; a
  different image size counts as 100 %. Screens without a baseline get the note `no baseline`.
- Compare only on the machine and viewport the baseline was taken with: fonts and anti-aliasing
  differ between hosts. Relative dates ("3 hours ago") and data refreshes stay under the default
  threshold; a new chart on a dashboard does not, so refresh the baseline after intended changes
  and review the image diff in the pull request.
- The baseline does not exist yet. Create it once the RTL work of this round is deployed:
  `python nxtbi/scripts/rtl_audit.py --update-baseline`.

## 2. End-to-end checks: `rtl_e2e.py`

```bash
python nxtbi/scripts/rtl_e2e.py                    # every check in Arabic and in English (about 12 min)
python nxtbi/scripts/rtl_e2e.py --only 04,08       # by substring of the check name
python nxtbi/scripts/rtl_e2e.py --locales ar
python nxtbi/scripts/rtl_e2e.py --headed
```

Results go to `nxtbi/out/rtl-e2e-results.json` (`summary` + one record per check and locale);
the exit code is 1 when a check fails. A failing check leaves a screenshot in
`nxtbi/out/rtl-e2e/<check>-<locale>.png`. `kind: "assertion"` means a measured expectation was
not met (the message carries the numbers); `kind: "error"` means the flow itself broke
(timeout, missing element) and needs triage: product or test.

Each check runs in Arabic and, as a regression guard, in English with the layout assertions
inverted.

| Check | What it asserts |
|---|---|
| `01-login-and-navigation` | fresh browser: Keycloak login, language picker, `<html dir lang>`, brand at the inline start, then Dashboards, Charts, Datasets, SQL Lab through the nav |
| `02-main-page-layout` | filter bar on the inline-start side of the dashboard grid; Explore panels ordered datasource, controls, chart; list view title column at the start and action column at the end; modal close button at the inline end |
| `03-language-switching` | three English <-> Arabic round trips through the picker: no `superset-rtl-` / `ant-*-rtl` class left in English, no horizontal scroll, the number of Emotion `<style>` tags does not grow |
| `04-popups-in-viewport` | dropdowns, nav submenus, select popup, tooltip, popovers and a modal open inside the viewport next to their trigger (trigger and popup rectangles are measured) |
| `05-dashboard-edit-and-save` | "Save as" creates `RTL E2E copy`; edit mode (builder pane and Save button on the inline-end side); a markdown block is edited, saved, reloaded and read back through the API; the original dashboard is byte-identical; the copy is deleted |
| `06-native-filters` | applying a Channel filter changes the "Service Requests" KPI, "Clear all" restores it |
| `06b-cross-filter` | clicking a mark in a chart cross-filters the KPI and clicking it again clears it (SKIP when no chart reacts) |
| `07-echarts` | every chart canvas computes `direction: ltr`; the pie with Arabic categories paints a non-empty canvas and its data has Arabic labels; a tooltip appears on hover, inside the viewport, in the page direction |
| `08-sql-lab` | the editor is LTR and holds the typed query; the query on `nxtbi.budget_execution` returns Arabic `sector_ar` values; the result grid has the page direction and its columns are laid out from the inline start |
| `09-mixed-language-table` | "Recent Requests": `org_name_ar` and `org_name_en` cells equal the chart-data API values, every numeric cell of the first row equals the API value, no misplaced sign, and the table has the page direction |
| `10-theme-and-responsive` | dark theme through the theme menu keeps `dir` and the mirrored layout; at 1024px and 390px: no horizontal page scroll, no colliding header controls, the nav is usable. In Arabic every problem is tagged "same problem in English" or "ARABIC ONLY" |
| `11-download-as-image` | dashboard menu > Download > "Download as image" starts a file download (SKIP when the menu has no such entry) |

Not tested: server-side screenshots (alerts and reports, thumbnails). They are produced by a
headless browser whose session has no locale and therefore use `BABEL_DEFAULT_LOCALE`
(English, LTR), whatever the language of the recipient is
(`nxtbi/docs/rtl/03-surface-audit.md`, section 7).

Data the checks leave behind: none, except SQL Lab (the admin's current tab is pointed at
"NxtBI Demo" and holds the test query) and query history entries. Dashboards named
`RTL E2E copy` / `RTL E2E copy (en)` from an interrupted run are deleted at the start of the
next run.

### Persistence after a restart

```bash
python nxtbi/scripts/rtl_e2e.py --keep            # full run; keeps 'RTL E2E copy' and the Arabic session
# ... restart the stack ...
python nxtbi/scripts/rtl_e2e.py --after-restart   # only the three persistence checks
python nxtbi/scripts/rtl_e2e.py --cleanup         # delete the kept dashboard and the state files
```

`--after-restart` writes its results to `nxtbi/out/rtl-e2e-restart-results.json`.
`--keep` writes `nxtbi/out/rtl-e2e-state.json` (id of the kept dashboard) and
`nxtbi/out/rtl-e2e-storage.json` (browser storage state: it contains the session cookie of the
test admin, keep it out of version control; `--cleanup` removes it).

| Check | What it asserts |
|---|---|
| `12a-restart-kept-session-stays-arabic` | the kept cookie is still signed in and the UI is still Arabic / RTL (sessions are server-side in Redis). SKIP when the kept session is older than the 8 h session lifetime |
| `12b-restart-new-login-locale` | a new login starts in the default locale (the language is stored in the session, not in the user profile) and the picker switches it to Arabic |
| `12c-restart-kept-dashboard-renders` | `RTL E2E copy` still exists, shows the edited markdown and chart data, filter bar on the right |

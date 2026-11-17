# NxtBI Arabic (العربية) and RTL on Superset master @ f3f3d10d5c

Source: `nxtbi/docs/research/05-theming-i18n-rtl.md` (R05), plus R01 and R06 where cited. V = verified in code, D = docs-claimed, U = unverified. Nothing here was executed. Effort sizes (S/M/L) in the phased plan are rough estimates written for this document, not taken from the research.

## 1. How Arabic is enabled

| Step | Detail | Evidence |
|---|---|---|
| Language list | `LANGUAGES` is overwritten to `{}` by default (English only, no picker). Enable with `{"en": {"flag": "us", "name": "English"}, "ar": {"flag": "sa", "name": "Arabic"}}`; picker appears when more than one language is configured | V `superset/config.py:586,590-624`; `superset/views/base.py:303-347` |
| Default locale | `BABEL_DEFAULT_LOCALE = "en"` (or `"ar"`) | V `superset/config.py:614` |
| Switching | `GET /lang/<locale>` sets `session["locale"]`; stored only in the session cookie, no per-user column | V `superset/initialization/__init__.py:1835-1854` |
| Backend catalogues | `.po` compiled to `.mo` in the image only if build arg `BUILD_TRANSLATIONS=true` (`pybabel compile --use-fuzzy`) | V `Dockerfile:32,198-212` |
| Frontend packs | `npm run build-translation` writes `messages.json` per language; the node stage runs it only if `BUILD_TRANSLATIONS=true` (default `false`) | V `superset-frontend/package.json:46`; `Dockerfile:131` |
| Serving | `GET /language_pack/<lang>/` and hashed `script.js`, unauthenticated | V `superset/views/core.py:704-760` |
| Repo state | `superset/translations/ar/LC_MESSAGES/` holds only `messages.po`; nothing is compiled | V directory listing (R05 s4) |
| Failure mode | Without a pack the UI silently falls back to English (no crash) | V `superset/translations/utils.py:46-62`; `superset-frontend/src/preamble.ts:83-123` |
| Verify | `/language_pack/ar/` must return 200 and the `script.js` URL must load | R05 s6 |

The research image `nxtbi/superset-fork:local` is described as having Arabic language packs built; whether `/language_pack/ar/` returns 200 on it has not been checked here (see Demo status).

## 2. Arabic catalogue completeness

Read-only count over `superset/translations/*/LC_MESSAGES/messages.po` (R05 s4): 5950 msgids in total.

| Measure | Arabic |
|---|---|
| Translated, non-fuzzy | 3223 (54.2%) |
| Fuzzy | 2718 |
| Untranslated | 9 |

For comparison: de 99.0%, fa 58.1%, nl 55.1%, it/pt/sl/fr/ja about 83%, fi/th/ko near empty. The backend `.mo` build uses `--use-fuzzy` (fuzzy strings are shown). Frontend `po2json` fuzzy handling is U (likely excluded), so up to about 46% of React UI strings may appear in English. Action: review and accept fuzzy `ar` entries for demo screens in the fork's `.po`, then rebuild. FAB-served pages (classic login form) use FAB catalogues (D, upstream #29509).

## 3. What works under locale `ar`

| Area | Status | Evidence |
|---|---|---|
| Translated strings | Works, about 54% non-fuzzy | R05 s4 |
| ECharts month/day names | Works (locale map includes AR) | V `superset-frontend/plugins/plugin-chart-echarts/src/components/echartsLocale.ts` |
| Arabic glyphs | Needs an Arabic-capable font; default Inter has none | R05 s2 |
| dayjs / antd locale | Missing `ar`: date pickers, relative time and antd built-in strings stay English | V `superset-frontend/src/hooks/useLocale.ts:23-60` |
| D3 number/date formats | Configurable through `D3_FORMAT`, `D3_TIME_FORMAT` | V `superset/config.py:627-701` |
| Layout direction | Stays LTR everywhere; Arabic text aligns through Unicode bidi only | R05 s5 |
| Keycloak `locale` claim | No hook; needs custom code that sets `session["locale"]` | U (R05 s4) |

## 4. RTL gap table

No RTL support exists (V): no `dir`, `rtl`, `rtlcss`, `stylis-plugin-rtl` or emotion RTL cache; `spa.html` emits a bare `<html>`; the theme `ConfigProvider` sets no `direction`. Upstream: apache/superset#25258 (open since 2023-10, no delivery) and #29509 (Persian).

| Gap | Severity | Proper fix |
|---|---|---|
| No `dir`/`lang` on `<html>`; antd `ConfigProvider direction` not tied to locale | High | Set in `spa.html` and `Theme.tsx` from the bootstrap locale |
| Emotion CSS uses physical properties (margin-left/right, left/right) across the app | High | Emotion cache + `stylis-plugin-rtl`, or migrate to logical properties (large audit) |
| Dashboard grid (resize/drag handles, positions) | High | Library RTL support or mirrored handles |
| ECharts axes, legend, tooltips, y-axis side | Medium | Per-chart option transforms (`yAxis.position`, `inverse`) |
| SQL Lab / Ace editor (code must stay LTR) | Medium | Force `dir=ltr` on editor and results, mirror chrome only |
| Tables (DataTable, ag-grid pinned columns, sort icons) | Medium | ag-grid `enableRtl`; antd via `ConfigProvider` |
| Popovers, dropdowns, date pickers (placement, no `ar` locale) | Medium | `ConfigProvider direction` + `ar` locales |
| Directional icons (arrows, chevrons, breadcrumbs) | Low-Med | CSS mirror under `[dir=rtl]` |
| FAB login/auth pages | Low | Override Jinja templates or use a Keycloak-themed login |
| Emails, reports, screenshots | Low | Out of scope |

## 5. Demo customisations chosen (low risk)

Decision: **LTR layout + Arabic translation + Arabic-capable font + NxtBI theme tokens.** Global RTL is shown only as a clearly labelled experiment, if at all.

1. Mount `./nxtbi/static` to `/app/superset/static/nxtbi:ro` (logos, favicon, optional self-hosted fonts); do not shadow `static/assets` (R05 s2).
2. Theme (STABLE): `THEME_DEFAULT` / `THEME_DARK` with `brandAppName`, `brandLogoUrl`, `fontFamily` `'IBM Plex Sans Arabic', 'Noto Sans Arabic', Inter, ...` and `fontUrls`. Google Fonts hosts are already in the CSP allowlist; an offline demo needs self-hosted woff2 plus `@font-face` in `head_custom_extra.html`. Other font hosts need both `THEME_FONT_URL_ALLOWED_DOMAINS` and `TALISMAN_CONFIG` overridden (R05 s2, s7).
3. Set `ENABLE_UI_THEME_ADMINISTRATION = False` so a DB theme cannot silently override the config themes (R05 s3, s7).
4. Build with `BUILD_TRANSLATIONS=true`, set `LANGUAGES` (en + ar), check `/language_pack/ar/`.
5. Optional `D3_TIME_FORMAT` Arabic `months`, `shortMonths`, `days`; keep Latin digits.
6. Optional `EXTRA_CATEGORICAL_COLOR_SCHEMES` entry `nxtbi` (`isDefault: True`).
7. Arabic data content (for example `region_ar` columns) renders through bidi without any change (R06 s6).
8. Optional experiment: `html{direction:rtl}` via `head_custom_extra.html`. It flips only inline flow; physical CSS, popups, drawers, sliders and antd stay unmirrored, so icons and carets misalign (R05 s5). Inline scripts need a CSP nonce; visibility of `macros.get_nonce()` there is U.

## 6. Phased plan for real RTL support

Rough sizes only. All work is frontend and needs a custom image build (no config-only path).

| Phase | Work package | Effort | Gap closed | Upstream / reference |
|---|---|---|---|---|
| 0 | Add `lang`/`dir` to `spa.html`; `ConfigProvider direction` from locale in `Theme.tsx`; add `dayjs/locale/ar` and `antd/locale/ar_EG` in `useLocale.ts`; accept fuzzy `ar` entries | S | No `dir`/`lang`; missing `ar` locales | #25258 |
| 1 | Emotion cache with `stylis-plugin-rtl` for the app theme provider; force `dir=ltr` on Ace/SQL Lab results; ag-grid `enableRtl` | M | Physical CSS (first pass), SQL Lab, tables | #25258 |
| 2 | Dashboard grid RTL (drag/resize handles, positioning) | L | Dashboard grid | no upstream work known |
| 3 | ECharts per-chart option transforms (axis side, legend, tooltip); mirror directional icons under `[dir=rtl]` | M | ECharts, icons | #25258 |
| 4 | Logical-properties migration of remaining emotion styles; popover/dropdown placement audit | L | Residual physical CSS, popovers | #25258 |
| 5 | Keycloak-themed or overridden login pages; Keycloak `locale` claim to `session["locale"]` | S | FAB auth pages, locale persistence | #29509 |
| 6 | Playwright visual-regression suite per screen in `ar`; upstream the generic parts | M | QA, maintenance | https://github.com/apache/superset/issues/25258 |

Risks: the fork would diverge from master on high-churn frontend files (Ant Design 6 migration is recent, R05 header); no upstream maintainer commitment exists (#29509: maintainer unaware of any RTL effort).

## Demo status

Run on 2026-11-17 against the demo stack (`nxtbi/scripts/smoke_test.py`, `nxtbi/scripts/browser_check.py`; screenshots `11-arabic-dashboard-list.png` and `12-arabic-dashboard.png` in `nxtbi/docs/screenshots/`).

| Check | Result |
|---|---|
| Image built with `BUILD_TRANSLATIONS=true` | Arabic `messages.mo` and `messages.json` are in the image |
| `GET /language_pack/ar/` | 200, 5,941 non-empty entries (fuzzy entries are included by the build) |
| Language picker | English and Arabic offered; `/lang/ar` switches the session |
| Navigation, buttons, filter bar actions, pivot totals | Rendered in Arabic |
| Arabic data values (`sector_ar`, `region_ar`, org names) | Stored, queried (SQL Lab, MCP, REST) and rendered correctly |
| Font | `IBM Plex Sans Arabic` applied through theme tokens (loaded from Google Fonts by the browser) |
| Layout direction under `ar` | `ltr` (measured with `getComputedStyle(document.documentElement).direction`): no RTL |

Observed in the Arabic screenshots (these are the visible symptoms of the gaps above):

- The navigation bar, filter bar and tables keep the left-to-right order; only the text inside each element is Arabic.
- Mixed-direction labels are scrambled by the browser's bidi algorithm because nothing sets a direction: pie labels read `%19.11 :label` and the pie total reads `4.54 :label B`.
- Strings that are missing or untranslated stay English next to Arabic ones (for example `SQL`, chart titles and filter names, which are content, not UI strings).
- Date pickers and relative times stay English: the frontend ships no `ar` locale for dayjs or Ant Design.

Not done: no global `dir="rtl"` experiment was shipped, because it produces a half-mirrored interface.

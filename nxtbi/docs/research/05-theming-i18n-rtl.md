# 05 - Branding, theming, i18n, Arabic and RTL (commit f3f3d10d5c, post 7.0.0rc2)

Legend: **V** = VERIFIED-IN-CODE (path:line), **D** = DOCS-CLAIMED, **U** = UNVERIFIED.
Paths relative to repo root. Frontend stack at this commit: antd **^6.6.8** (`superset-frontend/package.json:159`), echarts ^6.1.0, dayjs ^1.11.23, emotion 11. NOTE: `docs/admin_docs/configuration/theming.mdx` still says "Ant Design v5"; UPDATING.md:2368 ("Ant Design upgraded from v5 to v6") is authoritative (tokens unchanged; `cssVar: true/false` coerced).

## 1. Theme system

| Item | Finding | Ev |
|---|---|---|
| Lifecycle | STABLE (introduced 6.0, no feature flag). Per-theme editors/ACL added later (UPDATING.md:1550). | V config.py:1245-1377 |
| Precedence | (1) DB system theme if `ENABLE_UI_THEME_ADMINISTRATION=True` (default **True**), (2) `THEME_DEFAULT`/`THEME_DARK` from config, (3) built-in `_THEME_DEFAULT_BASE`; per-dashboard theme (bolt button) layered on top | V config.py:1250-1253,1362; superset/views/base.py:410-463 |
| Partial overrides | `THEME_DEFAULT`/`THEME_DARK` are **deep-merged** onto built-ins (`_merge_theme_dicts`); only changed tokens needed; dark base already has `"algorithm":"dark"` | V views/base.py:419-428; config.py:1327-1337 |
| Disable dark | `THEME_DARK = None` forces single theme | V config.py:1356 |
| Start mode | `THEME_DEFAULT_MODE` = `"default"` / `"dark"` / `"system"` (default system) | V config.py:1365 |
| Algorithm | `"default"` / `"dark"` / `"compact"` (string or list). Backend rewrites algorithm to match the slot (`enforce_theme_algorithm`), preserving `compact` | V themes/utils.py (ANTD_ALGORITHMS, enforce_theme_algorithm); views/base.py:451-454 |
| Validation (backend) | `is_valid_theme`: structure/type only (`token` dict, `components` dict, `hashed`/`inherit` bool, `algorithm`). Invalid -> warning logged, theme **cleared to `{}`** (built-in used). `brandSpinnerSvg` sanitized, `brandSpinnerUrl` via `sanitize_url`. `fontUrls`: https only, host in allowlist, max `THEME_FONTS_MAX_URLS`=15 - **enforced on API/import save only**, config-defined themes skip it | V themes/utils.py:156-240; themes/schemas.py:35-56; views/base.py:394-407 |
| Validation (frontend) | Unknown antd tokens filtered by `allowedAntdTokens`; custom tokens should be registered in `EXTRA_THEME_TOKENS` (default `[]`) | V superset-frontend/src/theme/utils/antdTokenNames.ts; config.py:1243 |
| Theme CRUD API | `/api/v1/theme/`: POST, PUT/DELETE `<pk>`, bulk DELETE, `export/`, `import/`, `<pk>/set_system_default` PUT, `<pk>/set_system_dark` PUT, `unset_system_default`/`unset_system_dark` DELETE, `system` GET. UI: Settings > Themes (`src/pages/ThemeList`). Edit/delete limited to theme editors or Admin | V superset/themes/api.py:205-833; UPDATING.md:1561 |
| Per-dashboard theme | Dashboard edit mode theme dropdown | D theming.mdx |
| Extra token groups | top-level `echartsOptionsOverrides`, `echartsOptionsOverridesByChartType`; `resultsGrid*` tokens (SQL Lab); `colorEditorSelection` | D theming.mdx; V config.py:1308 |

### Superset-specific tokens (verified: superset-frontend/packages/superset-core/src/theme/types.ts:130-175; defaults config.py:1275-1309)
`brandAppName`, `brandLogoUrl`, `brandLogoAlt`, `brandLogoHref`, `brandLogoHeight` (default "24px"), `brandLogoMargin` ("18px 0"), `brandIconMaxWidth` (37), `brandSpinnerUrl`, `brandSpinnerSvg`, `fontUrls` (string[]), `fontFamily`, `fontFamilyCode`, `fontSizeXS`, `fontSizeXXL`, `fontWeightNormal/Light/Strong/Bold`, `transitionTiming`, `colorEditorSelection`. All standard antd seed/map tokens (`colorPrimary`, `colorLink`, `colorBgBase`, `colorTextBase`, `borderRadius`, ...) work.

### Legacy keys
| Key | Status | Ev |
|---|---|---|
| `APP_NAME` | Backend fallback only (logs, MCP, emails); **no longer drives title/branding**; use `brandAppName` | V UPDATING.md:3144 |
| `APP_ICON` | Only feeds default `brandLogoUrl` at config import; if you replace THEME_DEFAULT set `brandLogoUrl` yourself | V config.py:502-505,1279 |
| `LOGO_TARGET_PATH` | Works: `sync_theme_logo_href()` re-run after superset_config load, writes `brandLogoHref` | V config.py:511-513,1340-1352,3996 |
| `LOGO_TOOLTIP`, `LOGO_RIGHT_TEXT`, `APP_ICON_WIDTH` | DEPRECATED/unused (use `brandLogoHeight`) | V config.py:518-527 |
| `HIDE_NAVBAR_LOGO` | Works (python flag, not a token) | V config.py:516 |
| `FAVICONS` | **Still works**, rendered by spa.html (`rel/type/sizes/href`; non-http hrefs get `assets_prefix`) | V config.py:131; superset/templates/superset/spa.html (head_css block) |
| `CUSTOM_FONT_URLS` | **REMOVED** -> `token.fontUrls` | V UPDATING.md:3167 |
| `THEME_OVERRIDES` | REMOVED (5.x -> new theming) | V UPDATING.md:3228 |
| `EXTRA_CATEGORICAL_COLOR_SCHEMES` | Works; list of `{id,label,colors[],isDefault?}`; also `EXTRA_SEQUENTIAL_COLOR_SCHEMES` | V config.py:1237,1380; views/base.py:681-684 |

## 2. Serving logo / favicon / fonts without a frontend rebuild
* Flask serves `superset/static/**` at `/static/**` (default favicon `/static/assets/images/favicon.png`, config.py:131). `/app/superset/static/assets` is a COPY layer from the node stage (Dockerfile:311,403): **mount a NEW sibling dir** (e.g. `./nxtbi/static:/app/superset/static/nxtbi:ro`) instead of shadowing `assets/`. Then `brandLogoUrl: "/static/nxtbi/logo-light.svg"`, `FAVICONS=[{"href": "/static/nxtbi/favicon.png"}]`.
* `data:` URL logos work for `<img>` under default CSP (`img-src` includes `'self' blob: data:`, config.py:3156-3159). Spinner: `brandSpinnerSvg` (served as data-URI img, spa.html) or `brandSpinnerUrl`.
* **Fonts**: `fontUrls` are injected as CSS `@import url("...")` (superset-frontend/src/theme/ThemeController.ts:1054-1067). Allowed hosts (save-time + CSP `style-src`/`font-src`): fonts.googleapis.com, fonts.gstatic.com, use.typekit.net/.com (`THEME_FONT_URL_ALLOWED_DOMAINS`, config.py:1372). CSP lists are computed at config import (config.py:3186,3190), so adding a host needs overriding **both** `THEME_FONT_URL_ALLOWED_DOMAINS` and a rebuilt `TALISMAN_CONFIG`. Offline demo: self-host woff2 in mounted `/static/nxtbi/fonts/` and declare `@font-face` in an inline `<style>` inside `superset/templates/head_custom_extra.html` (included in every SPA page: spa.html:118; mount-override the file). `style-src 'unsafe-inline'` + `font-src 'self'` already permit this.
* Tab title = `brandAppName` (spa.html fallback 'Superset').
* `script-src` is `'self' 'strict-dynamic'` + nonce: inline `<script>` in head_custom_extra needs `nonce="{{ macros.get_nonce() }}"` (`macros` imported at top of spa.html; visibility inside the include: U).
* Inter (default font) has no Arabic glyphs; Arabic falls back to OS font unless fontFamily changed.

## 3. Ready-to-paste NxtBI theme (only keys verified above)
```python
# superset_config.py
APP_NAME = "NxtBI"
FAVICONS = [{"href": "/static/nxtbi/favicon.png"}]
_NXT_FONT = "'IBM Plex Sans Arabic', 'Noto Sans Arabic', Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
_NXT_FONT_URLS = [
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&display=swap",
]
_NXT_BRAND = {
    "brandAppName": "NxtBI",
    "brandLogoAlt": "NxtBI",
    "brandLogoHref": "/",
    "brandLogoHeight": "28px",
    "brandLogoMargin": "14px 0",
    "fontUrls": _NXT_FONT_URLS,
    "fontFamily": _NXT_FONT,
    "colorPrimary": "#0B7F8A",   # teal (AA contrast with white text)
    "colorLink": "#0B7F8A",
    "colorInfo": "#2F80C0",
    "colorSuccess": "#2FB383",
    "colorWarning": "#F2B134",
    "colorError": "#E04355",
    "borderRadius": 6,
}
THEME_DEFAULT = {
    "algorithm": "default",
    "token": {**_NXT_BRAND,
        "brandLogoUrl": "/static/nxtbi/logo-light.svg",
        "colorBgBase": "#FFFFFF",
        "colorTextBase": "#0B2545",        # navy
        "colorEditorSelection": "#CFEFF1"},
}
THEME_DARK = {
    "algorithm": "dark",
    "token": {**_NXT_BRAND,
        "brandLogoUrl": "/static/nxtbi/logo-dark.svg",
        "colorPrimary": "#27C3CF", "colorLink": "#27C3CF",
        "colorBgBase": "#0B2545",
        "colorEditorSelection": "#1D4E63"},
}
THEME_DEFAULT_MODE = "default"            # light first, deterministic for demo
ENABLE_UI_THEME_ADMINISTRATION = False    # True lets DB system themes override the config themes
```
Notes: palette values are proposals (no brand asset verified); logo is per theme so the dark slot needs its own `brandLogoUrl`. Google Fonts needs internet from the browser; use the self-host route for offline demos. `colorBgBase`/`colorTextBase`/`borderRadius` are standard antd seed tokens (passed through `allowedAntdTokens`; exact membership of each not individually checked: U).

## 4. i18n

| Topic | Finding | Ev |
|---|---|---|
| Default state | Config defines 30 languages then **overwrites `LANGUAGES = {}`** ("i18n off by default"): English only, no picker. Picker shows iff `len(languages) > 1` | V config.py:590-624; views/base.py:303-347 |
| Enable | `LANGUAGES = {"en": {"flag":"us","name":"English"}, "ar": {"flag":"sa","name":"Arabic"}}`; `BABEL_DEFAULT_LOCALE = "en"` (or "ar") | V config.py:586,614 |
| Switching | `GET /lang/<locale>` sets `session["locale"]`, redirects to Referer. Persistence = Flask session cookie only (no per-user DB column) | V superset/initialization/__init__.py:1835-1854 |
| Locale -> frontend | `common.locale` from `get_locale()`, normalized; region codes (zh_TW, pt_BR) kept only if in `LANGUAGES` | V views/base.py:621-632,675 |
| Backend catalogs | `.po` -> `.mo`: `pybabel compile` or `flask fab babel-compile --target superset/translations` (`scripts/translations/generate_mo_files.sh`). Dockerfile runs `pybabel compile --use-fuzzy -d /app/translations_mo` only if `BUILD_TRANSLATIONS=true` | V Dockerfile:198-212 |
| Frontend packs | `npm run build-translation` (= `scripts/po2json.sh` -> `po2json-cli.js`) writes `superset/translations/<lang>/LC_MESSAGES/messages.json` (gitignored). Node stage runs it iff `BUILD_TRANSLATIONS=true`; **default `"false"`** | V superset-frontend/package.json:46; Dockerfile:32,131; .gitignore:118-120 |
| Serving | `GET /language_pack/<lang>/` (JSON) and content-hashed `GET /language_pack/<lang>/<12hex>/script.js` (spa.html loads it before the bundle -> `window.__SUPERSET_LANGUAGE_PACK__`); unauthenticated | V superset/views/core.py:704-760; spa.html tail_js |
| Pack missing | Backend: no `.mo` -> English. Frontend: no version -> no script tag; preamble fetches `/language_pack/ar/` -> 404 -> warns, `configure()` English, `dayjs.locale('en')`. **Silent English fallback**, no crash | V superset/translations/utils.py:46-62; views/base.py:719-754; superset-frontend/src/preamble.ts:83-123 |
| Repo state | `superset/translations/ar/LC_MESSAGES/` holds only `messages.po`. Must build with `BUILD_TRANSLATIONS=true` | V directory listing |
| D3 | `D3_FORMAT` {decimal, thousands, grouping, currency}; `D3_TIME_FORMAT` {dateTime,date,time,periods,days,shortDays,months,shortMonths}; passed in bootstrap, applied by `setupFormatters` | V config.py:627-701; views/base.py:676-677; preamble.ts:58-62 |
| ECharts | Locale loader map **includes AR** (and FA) | V superset-frontend/plugins/plugin-chart-echarts/src/components/echartsLocale.ts |
| dayjs / antd locale | `useLocale.ts` imports dayjs locales only for en, fr, es, it, zh-cn, zh-tw, ja, de, pt, pt-br, ru, ko, cs, sk, sl, nl; antd `LOCALE_MAPPING` same set -> **no `ar`**: date pickers, relative time and antd built-in strings stay English under `ar` | V superset-frontend/src/hooks/useLocale.ts:23-60 |
| Keycloak `locale` claim | No existing hook. Needs custom code (custom security manager / `before_request` / `FLASK_APP_MUTATOR` setting `session["locale"]` from OIDC claim, must be a key of `LANGUAGES`). FAB default locale selector order not read | U |

### Arabic catalogue completeness (read-only script, all `superset/translations/*/LC_MESSAGES/messages.po`)
Total msgids (excluding header, plurals counted once) = **5950**. Arabic: untranslated (empty msgstr) **9**, fuzzy **2718**, non-fuzzy translated **3223 = 54.2%**.

| lang | translated non-fuzzy | fuzzy | note |
|---|---|---|---|
| de | 99.0% | 61 | best covered |
| it / pt / sl / fr / ja | 84.1 / 83.0 / 83.0 / 82.9 / 82.8% | ~920-1020 | |
| **ar** | **54.2%** | 2718 | fa 58.1%, nl 55.1% |
| fi / th / ko | 1.3 / 1.2 / 5.6% | ~5600-5860 | essentially empty |

Fuzzy handling: backend `.mo` build uses `--use-fuzzy` (fuzzy shown); frontend po2json fuzzy handling unconfirmed (no "fuzzy" string in `po2json-cli.js`; library default likely excludes fuzzy: U). Expect up to ~46% of Arabic strings to be English in the React UI. Action: review/accept fuzzy `ar` entries for demo screens in the fork's `.po`, rebuild. Tooling: `scripts/translations/backfill_po.py` (AI backfill), `babel_update.sh`, `check_translation_regression.py`, `do-not-translate.txt` (UPDATING.md:2345). FAB-served pages (classic login form) use FAB catalogs (upstream issue 29509, D).

## 5. RTL

Searched `superset-frontend/src`, `plugins`, `packages/superset-ui-core/src` for `dir=`, `rtl`, `direction=`, stylis/rtlcss, ConfigProvider direction.
* **No RTL support exists** (V). `direction=` hits are only antd `<Space direction="vertical|horizontal">` (layout axis) in ~12 files; no `rtl`, `dir="rtl"`, `rtlcss`, `stylis-plugin-rtl`, emotion RTL cache. Theme `ConfigProvider` (superset-frontend/packages/superset-core/src/theme/Theme.tsx; `superset-ui-core/src/components/AntdThemeProvider`) sets no `direction`.
* `spa.html` emits bare `<html>` (no `lang`, no `dir`); no other file in `superset/templates` contains `dir` (V grep).
* Upstream: apache/superset#25258 "Superset does not support Arabic language -RTL- layout" (open since 2023-10; suggestion: run rtlcss over static CSS; no delivery) and #29509 (Persian; maintainer unaware of any RTL effort). No merged SIP found. https://github.com/apache/superset/issues/25258 , https://github.com/apache/superset/issues/29509

### Locale `ar` today
Works: translated strings (~54% frontend; backend higher with fuzzy), ECharts Arabic month/day names, Arabic glyphs given a font.
Partial: antd/dayjs locale (English dates/pickers).
Layout stays **LTR** (navbar, menus, tables, dashboard grid, drawers); Arabic text aligns via Unicode bidi only.

### Config/CSS-only tweaks (demo scope)
| Tweak | How | Effect / limits |
|---|---|---|
| Arabic font | `fontFamily` + `fontUrls` (section 3) | Safe |
| Global RTL experiment | inline `<style>html{direction:rtl}</style>` and/or nonce'd script setting `document.documentElement.dir='rtl'` from bootstrap locale, in mounted `head_custom_extra.html` | Flips inline flow/alignment/flex order only. Physical CSS (margin-left, left:, absolute popups, drawers, sliders, transforms) not mirrored -> misaligned icons, carets, tooltips; antd stays logically LTR (no ConfigProvider direction) |
| Content-level RTL | Arabic dataset/column/title text renders via bidi; per-element `dir="rtl"` in Markdown dashboard components if sanitizer allows (U) | Safe, local |
| dayjs/antd Arabic | needs code change in `useLocale.ts` (add `dayjs/locale/ar`, `antd/locale/ar_EG`) | frontend rebuild, not config |

Recommendation: ship **LTR UI + Arabic translation + Arabic font** for the demo; treat global RTL as an explicitly labelled experiment only.

### RTL gaps
| Gap | Sev | Proper fix |
|---|---|---|
| No `dir`/`lang` on `<html>`; no antd `ConfigProvider direction` tied to locale | High | set in spa.html + Theme.tsx from bootstrap locale |
| Emotion CSS uses physical properties (margin-left/right, left/right) across app | High | emotion cache + `stylis-plugin-rtl`, or migrate to logical properties (large audit) |
| Dashboard grid (resize/drag handles, positions) | High | library RTL support / mirrored handles |
| ECharts axes, legend, tooltips, y-axis side | Medium | per-chart option transforms (`yAxis.position`, `inverse`) |
| SQL Lab / Ace editor (code must stay LTR; mirror chrome only) | Medium | force `dir=ltr` on editor/results |
| Tables (DataTable, ag-grid pinned columns, sort icons) | Medium | ag-grid `enableRtl`, antd via ConfigProvider |
| Popovers/dropdowns/date pickers (placement, no `ar` locale) | Medium | ConfigProvider direction + ar locales |
| Directional icons (arrows, chevrons, breadcrumbs) | Low-Med | CSS mirror for `[dir=rtl]` |
| FAB login/auth pages | Low | override Jinja templates or use Keycloak-themed login |
| Emails/reports/screenshots | Low | out of scope |

## 6. Recommended low-risk demo customizations
1. Mount `./nxtbi/static -> /app/superset/static/nxtbi:ro` (logo-light.svg, logo-dark.svg, favicon.png, optional fonts/).
2. Paste section 3; keep Talisman defaults (self/data images, Google Fonts already allowed).
3. Build with `--build-arg BUILD_TRANSLATIONS=true`; set `LANGUAGES` (en + ar) so the picker appears; verify `/language_pack/ar/` returns 200 and the script.js URL loads.
4. Optional `D3_TIME_FORMAT` Arabic `months/shortMonths/days`; keep Latin digits.
5. Add `EXTRA_CATEGORICAL_COLOR_SCHEMES` with a teal/navy `nxtbi` scheme (`isDefault: True`).
6. Publish the RTL gap table as a known limitation; future frontend work package: ConfigProvider direction, stylis-plugin-rtl cache, `useLocale` ar additions, ag-grid RTL, dashboard grid.
7. Future (out of scope): Keycloak `locale` claim -> `session["locale"]`.

## 7. Risks / unverified
* fontUrls to hosts outside the allowlist load but CSP blocks them unless `TALISMAN_CONFIG` is also overridden.
* `ENABLE_UI_THEME_ADMINISTRATION=True` (default) lets a DB system theme silently beat config themes.
* Jinja include context for `macros.get_nonce()` in head_custom_extra.html: U.
* po2json fuzzy handling and FAB locale-selector order: U.

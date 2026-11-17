# 01 - Upstream research: RTL / Arabic work in apache/superset

Scope: what upstream already tried or merged, what is reusable on this fork, and what reviewers rejected.
Fork state checked: branch `feature/nxtbi-arabic-rtl`, upstream base `f3f3d10d5c` (2026-11-16). Research date 2026-11-17.
Method: GitHub API (PR/issue/review/thread/check data), public compare API, npm registry, `git`/`grep` on the fork, and the installed `superset-frontend/node_modules`.
Paths below are relative to the repo root unless they start with `node_modules/` (then relative to `superset-frontend/`).

## 0. Headline findings

| # | Finding | Evidence |
|---|---------|----------|
| 1 | Upstream has NO merged RTL support. The only RTL PR (#34629) was closed unmerged by its own author on 2026-10-08. | `closed_by: ceenayekta`, `merged: false`, https://github.com/apache/superset/pull/34629 |
| 2 | The fork has no direction plumbing at all: no `stylis-plugin-rtl`, no `stylisPlugins`, no `direction=` on `ConfigProvider`, no `getDirectionFromLocale`/`rtlLanguages`. | repo-wide grep over `superset-frontend` returned 0 matches; `packages/superset-core/src/theme/Theme.tsx:306` renders `<ConfigProvider theme={...}>` with no `direction` |
| 3 | Correction to the earlier finding "no lang on `<html>`": the template has a bare `<html>` (`superset/templates/superset/spa.html:16`) but the SPA sets `lang` at runtime. `dir` is never set. | `superset-frontend/src/views/App.tsx:68-70` (`document.documentElement.lang = ...`) |
| 4 | Maintainers want RTL ("this is a feature we'd love to land", rusackas 2026-06-22) and offered to redo it "against the current theme architecture" (2026-09-29). No follow-up PR was found. | #34629 comments; PR searches for rtl/right-to-left/stylis-plugin-rtl/direction returned nothing newer (search-limited, see Unverified) |
| 5 | The architecture of #34629 was explicitly praised by the last human-driven review ("LTR/RTL Emotion caches via stylis-plugin-rtl, keyed by direction, is a clean approach"). The blockers were rebase drift, lockfile churn, non-RTL CSS edits, and a few correctness bugs. | EnxDev review comment 2026-06-26 on #34629 |
| 6 | Arabic catalogue: both translation PRs are merged and in the fork, but the catalogue has since been rewritten by sync/backfill bots. Current: 5950 msgids, 3223 non-fuzzy (54.2%), 2718 fuzzy (45.7%), 9 untranslated; 1690 `Machine-translated via backfill_po.py` comments. | counted from `superset/translations/ar/LC_MESSAGES/messages.po`; `git log` on that file |
| 7 | Fuzzy entries ARE shipped to users: backend `.mo` via `pybabel compile --use-fuzzy` (`Dockerfile:208`), frontend JSON has no fuzzy filter (`superset-frontend/scripts/po2json.js:91`). | so 45.7% of Arabic UI text is unreviewed machine output |
| 8 | `stylis-plugin-rtl@2.1.1` is compatible with the fork's stylis (4.2.0) but is unmaintained since 2021; `@mui/stylis-plugin-rtl@9.5.0` (2026-10-09) is a maintained drop-in fork. | npm registry, section 6 |

## 1. PR #34629 "feat: RTL Text Support"

### 1.1 Facts

| Field | Value |
|-------|-------|
| URL / author | https://github.com/apache/superset/pull/34629 / `ceenayekta` (fork `ceenayekta/superset`, branch `rtl-support`) |
| Opened / closed | 2025-08-09 / 2026-10-08T14:12:45Z, closed by the author, not merged, draft at close |
| Size at head `c70153b` | 42 commits, 25 files, +618 / -409 (most of it lockfiles and tests) |
| Base SHA recorded | `8fed514e79`; rusackas: "over 2400 commits behind" (2026-09-29) |
| Labels | `requires:rebase`, `global:theming`, `dependencies:npm`, `packages`, `review:draft` |
| CI at head | Only 7 check runs exist: labeler (success), Netlify docs preview (success/neutral), "Sync PR to desired state" (skipped). The main frontend/backend workflows did not run on the final head. EnxDev at `430eb59`: "CI is fully red ... `lint-frontend` was skipped this run". `mergeable_state: dirty`. |
| Human reviews | justinpark (MEMBER) CHANGES_REQUESTED 2025-08-11; EnxDev request-changes comment 2026-06-26; EnxDev COMMENTED 2026-09-14 ("didn't find a correctness issue in this pass"). Never approved. |
| Bot reviews | Copilot, CodeAnt AI, Bito, Korbit: 36 review threads, 34 resolved |

### 1.2 Why and by whom it was closed

1. 2025-08-11 justinpark requested changes: "some of the CSS modifications included are not related to RTL".
2. Author went quiet for months; maintainers pinged 2025-11-17, 2026-02-13, 2026-05-05, 2026-06-22. Author reported connectivity problems on 2026-01-27 and asked to hand it over.
3. The theme code moved under the PR three times: `superset-ui-core` -> `packages/superset-core/src/ui/theme/` (#35308, fork commit `9546ee37e5`) -> `packages/superset-core/src/theme/`. An earlier iteration (`b17dccc`, merge-base 2025-12-05) still patched `src/ui/theme/Theme.tsx`.
4. 2026-09-29 rusackas: rebase "not a quick one anymore ... git can't even resolve the conflicts as a rename", set to draft, offered to "pick up a fresh implementation of RTL support against the current theme architecture".
5. 2026-10-08 the author closed it: "the theme provider was refactored three times ... rebasing the branch more than four times ... I've decided not to invest further time in it."

Nobody rejected the feature or the architecture. It died of drift.

### 1.3 Architecture at head `c70153b`

| Concern | What the PR did | File (PR head) |
|---------|-----------------|----------------|
| Where direction is stored | `direction?: TextDirection` on `SupersetSpecificTokens`, i.e. a field of the Emotion theme object (`theme.direction`). Also added `"direction": "ltr"` as a token in `THEME_DEFAULT`. | `packages/superset-core/src/theme/types.ts`, `superset/config.py` |
| Type | `export type TextDirection = 'ltr' \| 'rtl'` (replaced an earlier `DirectionType` import from `antd/es/config-provider`, which bots flagged as a forbidden direct antd import). | `types.ts`, re-exported from `theme/index.tsx` |
| Emotion | Two caches created once per `Theme` instance: `createCache({ key: 'superset-ltr' })` and `createCache({ key: 'superset-rtl', stylisPlugins: [stylisRTLPlugin] })`. Provider picks `emotionCaches[direction] ?? emotionCaches.ltr`. | `Theme.tsx` (`createEmotionCaches`, `emotionCaches`) |
| Ant Design | `<ConfigProvider theme={antdConfig} direction={direction}>`. No `StyleProvider`, no popup-container changes. | `Theme.tsx` |
| Document | `useEffect(() => { documentElement.setAttribute('dir', direction); setAttribute('data-direction', direction) }, [direction])` inside `Theme.SupersetThemeProvider`. | `Theme.tsx` |
| API | `Theme.setDirection(dir)`; `setConfig` preserves the previous direction; `ThemeController.setDirection` + `notifyListeners()`; `setDirection` added to `ThemeContextType` and `ThemeProvider`. | `Theme.tsx`, `src/theme/ThemeController.ts`, `src/theme/ThemeProvider.tsx` |
| Locale -> direction | `getLanguageCodeFromLocale` = `locale.split(/[-_]/)[0].toLowerCase()`; `getDirectionFromLocale` = membership in `rtlLanguages`; `getBootstrapLocale` = `common.menu_data.navbar_right.locale \|\| common.locale \|\| 'en'`. Called once from the `ThemeController` constructor (`initializeDirectionFromLocale`). | new `src/utils/localeUtils.ts` |
| RTL language list | `['ar','fa','he','iw','sd','dv','ps','ug','ur','yi'] as const` (reviewers had `kd` and `pk` removed as non-language codes). | `src/constants.ts` |
| Nested dashboard theme | `CrudThemeProvider` read `themeContext.theme.theme.direction` and called `createdTheme.setDirection(parentDirection)`. | `src/components/CrudThemeProvider.tsx` |
| Portals | Nothing explicit. Relied on React context reaching antd popups, plus `<html dir>`. | - |
| Backend template | No change to `spa.html`. Only the `config.py` token. No config key such as `RTL_LANGUAGES`. | - |
| Dependencies | `stylis-plugin-rtl ^2.1.1` added to `superset-frontend/package.json`, `packages/superset-core/package.json` and `docs/package.json` (+ `docs/yarn.lock`), the last two only because the Netlify docs build compiles `superset-core` from source. | - |

### 1.4 Piece-by-piece decision against the fork

All touched files still exist at the same paths (`git ls-files`). `src/utils/localeUtils.ts` does not exist yet.

| Piece | Fork state | Decision | Notes for the implementer |
|-------|-----------|----------|---------------------------|
| `TextDirection` type + export | `types.ts:112` (`SupersetSpecificTokens`), `:532` (`ThemeContextType`) | REUSE AS IS | Keep it Superset-owned; never import `DirectionType` from antd. |
| `theme.direction` on the Emotion theme | not present | REUSE THE IDEA | Good read API (`useTheme().direction`). Do not make it a user-editable theme token (see pitfalls P7). |
| `"direction": "ltr"` in `THEME_DEFAULT` | `superset/config.py:1297` area unchanged | OBSOLETE | Direction must follow locale, not theme JSON. A dashboard CRUD theme could otherwise flip one dashboard. |
| Two Emotion caches, RTL one with stylis plugin | fork still calls `createCache({ key: 'superset' })` on every `setConfig` (`Theme.tsx:163`) and in provider state (`:262`) | REUSE THE IDEA | Add `prefixer` (P1). Keep LTR key `'superset'` so LTR output stays identical. Hold the caches per `Theme` instance or module-level, not per `setConfig`. |
| `Theme.setDirection` / preserve in `setConfig` | `setConfig(config, baseTheme)` now has two params (`Theme.tsx:127`); single `updateProviders` callback was replaced by `providerListeners` + `notifyProviders` (`:235-251`) with `useLayoutEffect` registration (`:283-300`) | REUSE THE IDEA | PR code does not apply; rewrite against `notifyProviders`. |
| `<ConfigProvider direction>` | `Theme.tsx:306` | REUSE AS IS | One-line change. |
| `<html dir>` write inside `SupersetThemeProvider` | not present; `lang` is written in `src/views/App.tsx:70`, `data-theme-mode` in `src/theme/ThemeProvider.tsx:67` | REUSE THE IDEA | Do it once at app level (and server-side in `spa.html`), not in every provider instance (P3, P9). |
| `ThemeController.setDirection` + constructor init | constructor at `ThemeController.ts:133`; other `Theme` factories at `:260`, `:288`, `:612` | REUSE THE IDEA | Initialise from locale before first render. A public runtime setter is optional because language change is a full page load (`LanguagePicker.tsx:65` is an `href`). |
| `setDirection` in `ThemeContextType` / `ThemeProvider` | `types.ts:532`, `ThemeProvider.tsx:82-85` pattern | REUSE THE IDEA | Only if a runtime toggle is wanted (Storybook, tests). CodeAnt flagged it as an API-breaking context change. |
| `localeUtils.ts` + its test | file absent | REUSE AS IS | Already handles `ar_SA` and `ar-SA`. Use it in `App.tsx` next to the `lang` write. |
| `rtlLanguages` constant | `src/constants.ts` exists (`Actions` enum at `:212`) | REUSE AS IS | Co-locate with `localeUtils`. |
| `CrudThemeProvider` direction inheritance | rewritten: `parsedTheme` memo (`:58`), stable `dashboardThemeRef` (`:82-85`), in-place `setConfig` in `useLayoutEffect` (`:94-97`) | OBSOLETE (code) / REUSE THE IDEA | Every `Theme` instance must inherit direction; solve centrally rather than per call site (P4). |
| `LanguagePicker` `useEffect` calling `setDirection` | removed again before head | OBSOLETE | Reviewers: a "get menu items" hook must not mutate global theme. |
| `DynamicEditableTitle`: `.input-sizer` `left: -9999px` -> `visibility: hidden; pointer-events: none`; skip `scrollLeft = scrollWidth` in RTL | fork still has `left: -9999px` (`:66`) and the unconditional `scrollLeft` (`:114-115`) | REUSE AS IS | Final form was reviewer-approved. In RTL an off-screen-left element creates horizontal scroll. |
| `PageHeaderWithActions`: `css={fn}` -> `css={fn(theme)}`, conditional dropdown wrapper | fork `:159-175` unchanged | OBSOLETE | Not RTL-related. Physical `margin-right`/`margin-left` at `:79`, `:95`, `:121` are flipped by the plugin automatically. |
| `Menu.tsx`: `.main-nav.ant-menu-horizontal { display: flex }` | `className="main-nav"` at `:456`, `float: left` at `:74` | REUSE THE IDEA | Only if a real RTL defect is reproduced; unscoped version was rejected (breaks inline/mobile menu). |
| `SubMenu.tsx`: `.menu { justify-content: space-between }` | `:88`; floats at `:63`, `:85` | OBSOLETE | Dropped during review as non-RTL. |
| `ListViewCard` `TitleRight` `right:` | `:96-101` still `right: ${theme.sizeUnit * 2}px` | REUSE THE IDEA | justinpark asked for `inset-inline-end`. The `theme.direction === 'rtl' ? left : right` variant was wrong under the plugin (double flip). |
| `DashboardBuilder` `style` -> `css` on `Droppable` | `:946` still `style={draggableStyle}` with `marginLeft` (`:713-715`) | OBSOLETE (code) | Bito: `Droppable` ignores `css`. Real issue remains: inline styles are not flipped (P6). |
| `RightMenu` destructuring `setDirection` | `:188-194` | OBSOLETE | - |
| Tests (`Theme.documentDirection.test.tsx`, `localeUtils.test.ts`, `ThemeController.test.ts`, `CrudThemeProvider.test.tsx`) | absent | REUSE THE IDEA | Port the cases; use `test()` not `describe()`, reset `dir` in `beforeEach` (Bito). |

## 2. Arabic translation PRs

| PR | State | What it changed | In fork? |
|----|-------|-----------------|----------|
| [#29586](https://github.com/apache/superset/pull/29586) `chore(translations): Arabic translations` (abdilra7eem) | Merged 2024-08-26 by mistercrunch, shipped in 5.0.0 | Human translation of `ar/LC_MESSAGES/messages.po` only (+4606/-3606); at the time 3820 translated, 3 fuzzy, 1 untranslated. Body: "more work is still needed for RTL text direction support. This is only the translation." | Yes, commit `4e346180e0`; 6/6 sampled added `msgstr` lines still verbatim at HEAD |
| [#41705](https://github.com/apache/superset/pull/41705) `feat(i18n): backfill Arabic (ar) translations (AI-generated, needs review)` (rusackas) | Merged 2026-07-03 | Machine-filled all untranslated entries via `scripts/translations/backfill_po.py`; every generated entry flagged `#, fuzzy` with a `Machine-translated via backfill_po.py` comment (+2032/-462). Body states fuzzy entries render in the UI. | Yes, commit `4e2160079a`; 6/6 sampled lines present |

Later commits that also rewrote the Arabic catalogue (all in the fork): `e333135a0d` #41827 (exposes `ar` in `LANGUAGES`, `superset/config.py:614`), `cba2574241` #44611 (cleared 1,188 fuzzy entries with broken placeholders), `6cad838c82` #44742 (dropped the `po2json` package; `scripts/po2json.sh` now runs `po2json-cli.js` on `gettext-parser`), `2918a7b94d` #44397 (translator context comments), `3823c6dc2c` #45583 and `117d7a667c` #45940 (bot catalogue sync), `2649e3bbf4` #46034 (re-backfill of 29 catalogues with a newer model plus a weekly workflow).

Consequences:
- `.github/workflows/backfill-translations.yml:19-21` runs weekly (`cron: "0 6 * * 2"`) upstream and `sync-translation-catalogs.yml` rewrites catalogues. Any fork edit to `ar/messages.po` will conflict on every upstream merge. Reviewed Arabic strings should be upstreamed, or kept in a fork-owned overlay applied at build time.
- De-fuzzing is the upstream-accepted review signal ("verify each and remove the `#, fuzzy` flag", #41705). `scripts/translations/check_translation_regression.py` treats untranslated -> fuzzy as not a regression.
- `LANGUAGES = {}` is the shipped default (`superset/config.py:624`), so Arabic appears only when the deployment config enables it.
- `superset-frontend/src/hooks/useLocale.ts:43-59` has no `ar` in `LOCALE_MAPPING` and no `dayjs/locale/ar` import (`:23-38`); ECharts does have `AR` (`plugins/plugin-chart-echarts/src/components/echartsLocale.ts:49`).

## 3. PR #42323 (RTL-safe filter fix)

| Field | Value |
|-------|-------|
| URL | https://github.com/apache/superset/pull/42323 `fix(native-filters): keep filter value input caret at inline start` |
| State | Merged 2026-07-23 by yousoph; supersedes #42266 |
| In fork | Yes: commit `df8bbb548a`; `superset-frontend/src/filters/components/common.ts:34` and `src/chartCustomizations/components/common.ts:34` |
| Fix | Adds `text-align: start;` to the shared `FilterPluginStyle` wrapper so an inherited `text-align: center` cannot centre the caret. Body: "it is RTL-safe". |
| Test | `src/filters/components/common.test.tsx` with `expect(el).toHaveStyleRule('text-align', 'start')` for both copies |

Precedent it sets for upstream-acceptable style:
1. Logical values/properties (`start`, `inline-start`) instead of `left`/`right`. Same request from justinpark on #34629 ("change `right` to `inset-inline-end`").
2. Wrapper-level rule, not an override of antd internals: the first attempt's nested `.ant-select-content` override was dropped in review.
3. A CSS comment explaining why, plus a `toHaveStyleRule` unit test.
4. Small, single-purpose PR (3 files, +51).

It is the only commit since 2025-06 in the fork's history whose message mentions RTL/inline-start semantics (`git log --grep`). Logical properties are rare in the fork: `margin-inline` 7 lines / 6 files, `padding-inline` 7 / 6, `inset-inline` 5 / 4, versus physical `margin-left|right` 366 lines / 181 files, `padding-left|right` 150 / 86, `left:`/`right:` 230 / 105, `text-align: left|right` 51 / 41, `float` 9 / 7, `border-left|right` 57 / 29 (non-test `.ts/.tsx` under `src`, `packages`, `plugins`). This is why a central flip is needed; hand-converting is ~860 lines.

## 4. PR #44471 (Dashboard V2 / embeddable widgets) - state only

| Field | Value |
|-------|-------|
| URL | https://github.com/apache/superset/pull/44471 `feat(dashboard-v2): embeddable widgets for host apps, artifacts and extensions` (msyavuz) |
| State | Open, not draft, not merged; base branch `dashboard-v2` (not `master`); 188 files, +19949/-2013; last update 2026-09-30; `mergeable_state: unstable`; labelled `risk:db-migration`; self-described POC |
| In fork | No. `git ls-files` has 0 paths under `packages/superset-widgets/`, `src/core/dashboard/`, `DashboardBuilderV2` |

Theme/provider APIs it relies on (from its patches):

| API | Where in #44471 | Implication for direction |
|-----|-----------------|---------------------------|
| `Theme.fromConfig({...themeConfig, algorithm})` from `@apache-superset/core/theme` | `packages/superset-widgets/src/embed/SupersetProvider.tsx` | A widget host builds its own `Theme`. No `ThemeController`, no bootstrap data, no Redux. Direction must be settable on a bare `Theme` (config field or `fromConfig` option). |
| `theme.SupersetThemeProvider` with a new prop `withGlobalStyles={false}` | same file; adds the prop in `packages/superset-core/src/theme/Theme.tsx` | Direction must not depend on `GlobalStyles`. The provider signature will conflict textually with any edit we make there; keep our change to that function small. |
| "Nothing leaks into the host page's global styles" | provider doc comment | The provider must not write `<html dir>` when embedded. Document-level writes belong to the Superset app shell only. |
| `useTheme()` from `@apache-superset/core/theme` | `src/core/dashboard/StaticGrid.tsx` | The natural way for a widget to read direction is `useTheme().direction`. |
| `getPopupContainer={() => document.body}` | `widgets/FilterSelectWidget.tsx` | Popups leave any `dir` wrapper. Only context-borne direction (antd `ConfigProvider`, Emotion cache) reaches them. |
| `AnyThemeConfig`, `ThemeAlgorithm` | `embed/session.tsx`, `SupersetArtifactProvider.tsx` | Unchanged by us. |

Compatibility rule: direction = state of the `Theme` instance, applied by `SupersetThemeProvider` through (a) the Emotion cache choice and (b) `ConfigProvider direction`, readable as `useTheme().direction`. The app shell additionally sets `<html dir lang>`.

## 5. Other upstream RTL / bidi work since mid-2025

| Item | State | Relevance |
|------|-------|-----------|
| Issue [#25258](https://github.com/apache/superset/issues/25258) "Superset does not support Arabic language -RTL- layout" | Closed as completed 2026-06-05 by rusackas: "mostly (?) done, but we're open to PRs" | Closed while #34629 was still open; RTL is in fact not done. msyavuz (2025-07-28) suggested antd `ConfigProvider` direction. OmarIthawi (2025-08-19) gave the icon rule: mirror directional arrows/back/forward; never mirror logos, flags, globes, maps. |
| Issue [#29509](https://github.com/apache/superset/issues/29509) "Support for Persian (fa) language" | Closed not_planned 2024-07-18 by its author | Translation loading bug (`jed.js ... reading 'domain'`), not RTL. Persian catalogue landed later (#29580 = fork `a5f986fec5`, #41701 = fork `46a153d17e`). |
| SIP for RTL/i18n direction | None found | Issue search for RTL/right-to-left/direction returned only the two issues above. |
| #36100 / #36111 "Persian calendar date control" | Closed (2025-11-14, 2026-06-23); neither number appears in the fork's `git log` | Jalali date picker; not in fork. Idea only. |
| #44527 "Calendar date picker option to the Time range filter" | Open | Touches the date filter UI that RTL will also touch; watch for conflicts. |
| #39330 `Intl.DurationFormat` for localized durations | Merged, fork `108e40cbb6` | Build on it: locale-aware formatting precedent using native `Intl`. |
| #44554 Big Number alignment control | Merged, fork `bc1abf498d` | Alignment choices here are physical left/center/right; decide explicitly whether they mirror. |
| #35308 move theme to `superset-core` | Merged, fork `9546ee37e5` | The refactor that broke #34629. Theme code lives in `packages/superset-core/src/theme/`. |
| #46034 weekly AI backfill + #45583/#45940 catalogue sync | Merged, in fork | See section 2. |
| Open PRs worth borrowing code from | None | #34629 (closed) is the only source. |

## 6. Library facts

### 6.1 Stylis / Emotion

| Fact | Evidence |
|------|----------|
| Root `stylis` is 4.2.0, pinned exactly by `@emotion/cache@11.14.0` (`"stylis": "4.2.0"`) | `superset-frontend/package-lock.json:37484-37485`, `:3364-3374` |
| A second stylis 4.4.0 is nested under `@ant-design/cssinjs@2.1.2` (and `geostyler`) | `package-lock.json:286-298`, `:332-334`, `:21721` |
| `stylis-plugin-rtl` latest = 2.1.1, published 2021-10-19, `peerDependencies: { stylis: "4.x" }`, `dependencies: { cssjanus: "^2.0.1" }`, MIT | https://registry.npmjs.org/stylis-plugin-rtl |
| Compatible: 4.2.0 satisfies `4.x`, and every symbol the plugin imports (`COMMENT, compile, DECLARATION, IMPORT, RULESET, serialize, strlen, KEYFRAMES, MEDIA, SUPPORTS`) exists in 4.2.0 | `node_modules/stylis/src/Enum.js:5-21`; plugin `dist/stylis-rtl.js` |
| It will bind to the hoisted root stylis 4.2.0, the same copy Emotion uses; antd's nested 4.4.0 is unaffected | lockfile layout above |
| `@mui/stylis-plugin-rtl` latest = 9.5.0, published 2026-10-09, peer `stylis: 4.x`, deps `cssjanus ^2.3.1` + `@babel/runtime`, MIT. Same code plus one change: also flips rules whose parent is `@layer` | https://registry.npmjs.org/@mui/stylis-plugin-rtl ; its `index.mjs` header: "Copied from ... stylis-plugin-rtl ... with a modification ... to handle layer rules" |
| stylis 4.2.0 already exports `LAYER` | `node_modules/stylis/src/Enum.js:21` |
| Passing `stylisPlugins` REPLACES Emotion's default `[prefixer]` | `node_modules/@emotion/cache/dist/emotion-cache.browser.development.esm.js:451` (`defaultStylisPlugins = [prefixer]`) and `:495` (`options.stylisPlugins \|\| defaultStylisPlugins`) |
| `prefixer` is exported by stylis 4.2.0 | `node_modules/stylis/src/Middleware.js:42` |
| `cssjanus` is not yet in the lockfile (new transitive dependency, Apache-2.0, latest 2.3.1) | `grep cssjanus package-lock.json` = 0 hits; registry |
| What cssjanus flips: `left/right` properties and values, 4-value `margin/padding` shorthands, `border-radius`, `float`, `text-align`, `cursor: e/w-resize`, `background-position`, `box-shadow`/`text-shadow` x-offset, `transform: translateX()/translate()`, and `direction: ltr <-> rtl` | `cssjanus@2.3.1/src/cssjanus.js:149-173`, `:379-406` |
| Opt-out: `/* @noflip */` or `/*! @noflip */` before a rule or a declaration | `cssjanus.js:89`, `:114`; plugin README recommends the `/*!` form because minifiers strip normal comments |
| Not processed by either plugin: rules nested in at-rules other than `@media`/`@supports`/`@keyframes` (and `@layer` for the MUI fork), e.g. `@container` | plugin source: parent-type check |
| Production build uses `@swc/plugin-emotion@20.0.2` | `superset-frontend/webpack.config.js:288`, `package-lock.json:12403-12404` |

The stylis plugin only sees CSS that goes through Emotion (`styled`, `css`, `Global`). It does not see: inline `style={{}}` props, antd's own styles (separate cssinjs engine), ag-grid CSS, ECharts canvas, static `.css/.less` files, or user dashboard CSS.

### 6.2 Alternatives considered

| Option | Verdict |
|--------|---------|
| `stylis-plugin-rtl@2.1.1` | Works. Unmaintained 5 years. It is what #34629 used and what reviewers accepted. |
| `@mui/stylis-plugin-rtl@9.5.0` | Same behaviour, actively released, MIT, handles `@layer`. Preferred technically; a new dependency name upstream has not seen. |
| Logical properties only, no plugin | Matches maintainer taste (#42323, justinpark) but needs ~860 line edits across ~300 files and constant vigilance. Realistic only as incremental clean-up on top of the plugin. |
| `rtlcss` (4.3.0, PostCSS) | Build-time tool for static CSS. Not applicable to runtime Emotion; possibly useful for static stylesheets only. |
| `@ant-design/cssinjs` `StyleProvider` transformers | `legacyLogicalPropertiesTransformer` converts logical -> physical for old browsers (`node_modules/@ant-design/cssinjs/es/transformers/legacyLogicalProperties.js`). It would BREAK antd RTL. The fork does not use `StyleProvider` (0 grep hits); keep it that way. |

### 6.3 Ant Design 6 (installed 6.6.8, `package-lock.json:15557-15558`)

| Topic | Fact | Evidence |
|-------|------|----------|
| Switch | `<ConfigProvider direction="rtl">`; value travels by React context | `node_modules/antd/es/config-provider/index.js:110`, `:227` |
| Styling | Components add a `*-rtl` class and their styles use logical properties | ~123 files under `antd/es` reference `-rtl`, 96 use `Inline(Start\|End)`; 1 style file uses physical margin/padding |
| Popup placement | Default placement mirrors automatically when not specified: Dropdown, Dropdown.Button, Select, TreeSelect, table filter dropdown, Menu item tooltip | `antd/es/dropdown/dropdown.js:108`, `dropdown-button.js:89`, `select/index.js:212`, `tree-select/index.js:194`, `table/hooks/useFilter/FilterDropdown.js:454`, `menu/MenuItem.js:110` |
| Explicit placement | An explicit `placement="bottomLeft"` is honoured as written and does not mirror | same lines: the direction branch is only the fallback |
| Portals | Popups, Modal, Drawer, Tooltip read direction from context, so they work when rendered under the provider, including with `getPopupContainer` (28 fork files use it) | `antd/es/modal/Modal.js`, `drawer/Drawer.js`, `tooltip/index.js` consume `direction` |
| Static APIs | `Modal.confirm()` etc. render outside the React tree and miss context unless `ConfigProvider.config({ holderRender })` is set. Fork has 7 `Modal.confirm/info/...` call sites, 0 static `message`/`notification`, and no `holderRender` | `antd/es/config-provider/index.js:64-96`; fork grep |
| Icons | `@ant-design/icons` has no RTL handling; nothing mirrors automatically | no `rtl` in `node_modules/@ant-design/icons/es/components/AntdIcon.js` or `Context.js` |
| Locale | Separate from direction: `ConfigProvider locale`; fork loads antd locales in `src/hooks/useLocale.ts:43-59`, no `ar_EG` | - |

Other roots that bypass the main provider and need the same treatment: `src/views/menu.tsx:43-63` (own `createCache({ key: 'menu' })` + bare Emotion `ThemeProvider`, no antd `ConfigProvider`), `src/embedded/index.tsx:233`, `plugins/plugin-chart-cartodiagram/src/components/ChartLayer.tsx:201`, and the pass-through `packages/superset-ui-core/src/components/AntdThemeProvider/index.tsx:26`.

## 7. Reuse plan

| Step | Take from | Target in fork | Decision |
|------|-----------|----------------|----------|
| 1 | #34629 `localeUtils.ts` + `rtlLanguages` + tests | new `superset-frontend/src/utils/localeUtils.ts` (ASF header) | REUSE AS IS |
| 2 | #34629 `TextDirection`, `direction?` on theme type | `packages/superset-core/src/theme/types.ts:112`, export in `theme/index.tsx` | REUSE AS IS |
| 3 | #34629 dual Emotion cache | `Theme.tsx:163`, `:259-263`, `:303` | REUSE THE IDEA: `stylisPlugins: [prefixer, rtlPlugin]`, LTR key stays `'superset'`, RTL key `'superset-rtl'`, caches built once |
| 4 | #34629 `ConfigProvider direction` | `Theme.tsx:306` | REUSE AS IS |
| 5 | #34629 `Theme.setDirection` | `Theme.tsx` next to `toggleDarkMode` (`:174`), via `notifyProviders` | REUSE THE IDEA; add a default every new `Theme` inherits so `fromConfig` (`:97`), `CrudThemeProvider.tsx:85`, `ThemeController.ts:260/288/612` need no per-site code |
| 6 | #34629 controller init from locale | `ThemeController.ts:133` constructor, before first `applyTheme` | REUSE THE IDEA |
| 7 | #34629 `<html dir>` effect | `src/views/App.tsx:70` beside `lang`; plus server-side `<html lang dir>` in `superset/templates/superset/spa.html:16` | REUSE THE IDEA (moved out of the provider) |
| 8 | #34629 `DynamicEditableTitle` fix | `packages/superset-ui-core/src/components/DynamicEditableTitle/index.tsx:64-66`, `:114-115` | REUSE AS IS |
| 9 | justinpark's request | `ListViewCard/index.tsx:101` -> `inset-inline-end` | REUSE THE IDEA |
| 10 | #42323 pattern | every new per-component fix: logical property + comment + `toHaveStyleRule` test | REUSE AS PRECEDENT |
| 11 | #34629 dependency wiring | `superset-frontend/package.json`, `packages/superset-core/package.json`, `docs/package.json` (+ both lockfiles) | REUSE THE IDEA; regenerate locks with the package manager only |
| 12 | #34629 `config.py` token, `LanguagePicker` effect, `RightMenu`, `SubMenu`, `PageHeaderWithActions`, `DashboardBuilder` edits, `CrudThemeProvider` patch | - | OBSOLETE, do not port |
| 13 | New, not in any upstream PR | `src/views/menu.tsx:43`, `src/embedded/index.tsx:233`, `ConfigProvider.config({ holderRender })`, `useLocale.ts` `ar` entries, LTR islands for code/SQL, icon mirroring list | must be designed here |

## 8. Pitfalls raised by reviewers (and found while verifying) that we must avoid

| # | Pitfall | Source | What to do |
|---|---------|--------|------------|
| P1 | `stylisPlugins: [rtlPlugin]` silently drops Emotion's vendor prefixer in the RTL cache only | Verified in `@emotion/cache` source (`:451`, `:495`); not caught in #34629 | Always `[prefixer, rtlPlugin]` |
| P2 | Double flip: branching on `theme.direction` to emit `left` vs `right` inside Emotion CSS gets flipped back by the plugin | CodeAnt thread 2026-03-13, author's reply 2026-03-17 | Write LTR physical CSS and let the plugin flip, or use logical properties. Never both for the same declaration |
| P3 | `dir` attribute written only on change, so first paint is LTR and pages without the language picker never switch | EnxDev "Functional" finding; Copilot/CodeAnt "dir attribute not reset" | Set `dir` before first render (template + bootstrap), always write both values |
| P4 | New `Theme` instances default to LTR (dashboard CRUD theme, `createDashboardThemeProvider`) | CodeAnt thread 2026-06-26; at head fixed for `CrudThemeProvider` only, by hand | Central default, not per-call-site propagation; add a test rendering a dashboard theme under an RTL locale |
| P5 | Locale parsing split on `-` only; Superset emits underscore locales (`pt_BR`, `zh_TW`) | EnxDev, CodeAnt | Split on `/[-_]/`, lowercase, test `ar_SA` and `ar-SA` |
| P6 | Inline `style={{ marginLeft }}` and static CSS are invisible to the plugin | Bito on `DashboardBuilder` (`style` vs `css`); verified by plugin design | Convert inline physical styles to logical (`marginInlineStart`) where they matter, e.g. `DashboardBuilder.tsx:713-715`, `:946` |
| P7 | `direction` as a required/theme-JSON token is a breaking change and lets a theme override locale | CodeAnt "Breaking change"; `config.py` edit | Optional field, derived from locale only, not serialised by `toSerializedConfig` (`Theme.tsx:170`) |
| P8 | cssjanus flips `direction: ltr` to `rtl`, so "force LTR" rules for code/SQL written in Emotion CSS invert in the RTL cache | Verified `cssjanus.js:379-381` | Use the HTML attribute `dir="ltr"` (plus `unicode-bidi: isolate` or `<bdi>`) for LTR islands, or `/*! @noflip */` |
| P9 | Writing `<html dir>` from every `SupersetThemeProvider` instance: nested dashboard providers, docs pages with many providers, and embedded widgets on a host page (#44471) | Derived from fork `Theme.tsx:228-234` comment and #44471 provider contract | Document-level writes only in the app shell |
| P10 | Non-RTL CSS refactors mixed into the PR | justinpark CHANGES_REQUESTED; EnxDev "Should-fix" | One concern per change; justify each component edit with an RTL screenshot or test |
| P11 | Unscoped `.main-nav { display: flex }` breaks antd inline/mobile menu | CodeAnt + EnxDev | Scope to `.ant-menu-horizontal` or avoid |
| P12 | Runtime import of a type-only symbol and direct `antd` imports fail `isolatedModules` and the repo's custom lint rule | EnxDev, CodeAnt custom_rule threads | `import type`, Superset-owned `TextDirection` |
| P13 | Lockfile churn: replacing `package-lock.json`/`docs/yarn.lock` wholesale changed unrelated versions; Bito flagged unsynced entries | rusackas 2026-06-28, author 2026-06-28, Bito 2026-06-27 | `npm install <pkg>` / `yarn add <pkg>` only; review the lock diff |
| P14 | Forgetting `docs/` and `packages/superset-core/package.json`: docs build compiles `superset-core` source and failed on Netlify | author 2026-06-28 | Declare the plugin wherever `Theme.tsx` is compiled |
| P15 | A hook that returns menu items also mutating global theme | EnxDev nit | Keep direction initialisation in the controller/app shell |
| P16 | Forcing `scrollLeft` in RTL inputs (sign conventions differ by browser) | CodeAnt thread 2026-03-17 | Skip manual scroll in RTL |
| P17 | Hiding a measuring element with `opacity: 0` (still intercepts clicks) or `left: -9999px` (scrollbar in RTL) | EnxDev; author 2025-08-15 | `visibility: hidden; pointer-events: none` |
| P18 | Long-lived branch against a moving theme system | closing comments | Keep the core change small (Theme.tsx, types, localeUtils, App shell) and rebase often; #44471 will touch `SupersetThemeProvider`'s signature |
| P19 | Test hygiene: `dir` attributes leaking between tests; removed tests not replaced | Bito 2026-06-26 | Reset in `beforeEach`; cover LTR -> RTL -> LTR |
| P20 | Explicit antd `placement` props do not mirror; icons never mirror | Verified in antd 6.6.8 source; OmarIthawi on #25258 | Audit explicit placements; maintain an allow-list of directional icons to mirror |

## 9. Unverified

- That no newer upstream RTL PR exists: GitHub search only; one title search timed out. Draft PRs with unusual wording could be missed.
- Whether `@swc/plugin-emotion@20.0.2` strips `/* @noflip */` comments in production builds. Needs a build-output test before relying on noflip; `/*! @noflip */` is the documented safer form.
- Whether an unknown `direction` key inside antd `theme.token` would be emitted as a CSS variable. Avoided by not storing direction in the antd token config.
- CI results of the main workflows for #34629: no runs exist on the final head, so "would it have passed" is unknown.
- Contents of the `dashboard-v2` branch beyond #44471's diff were not inspected.
- The antd counts (123 / 96 files) come from a recursive grep of `antd/es` and are approximate.
- An empty untracked file `files` and `nxtbi/dev/`, `nxtbi/docker-compose.dev.yml` appeared in the working tree during this research (timestamps 12:14-12:15 on 2026-11-17). None of the commands run for this document writes them; they look like another task's output and were left untouched.

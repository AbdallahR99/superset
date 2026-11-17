# 02 - Direction architecture (locale -> direction -> providers)

Scope: fork `feature/nxtbi-arabic-rtl` (= apache/superset master @ `f3f3d10d5c`). Read-only research; every fork claim has `path:line`.
Paths are relative to repo root; `FE/` = `superset-frontend/`. Counts were produced with ripgrep over `*.{ts,tsx,js,jsx}` excluding tests, stories, `node_modules`, `lib`, `esm`, `dist`.

## 0. Verdict on the earlier finding

| Earlier claim | Status | Evidence |
|---|---|---|
| No `dir` on `<html>` | TRUE | `superset/templates/superset/spa.html:16` is a bare `<html>`; static `404.html`/`500.html` hard-code `<html lang="en">` (`FE/src/assets/staticPages/404.html:21`, `500.html:21`) |
| No `lang` on `<html>` | PARTLY FALSE | set client-side, SPA entry only: `FE/src/views/App.tsx:68-70` (`document.documentElement.lang`). Not set in the `embedded` entry, never server-side |
| No antd `ConfigProvider direction` | TRUE | only two `ConfigProvider` renders, neither passes `direction`: `FE/packages/superset-core/src/theme/Theme.tsx:306`, `FE/packages/superset-ui-core/src/components/AntdThemeProvider/index.tsx:26` |
| No stylis RTL plugin | TRUE | `createCache({ key: 'superset' })` with no `stylisPlugins` at `Theme.tsx:163` and `Theme.tsx:262`; `stylis-plugin-rtl`/`cssjanus` absent from `FE/package-lock.json` |
| `useLocale.ts` has no `ar` | TRUE | dayjs imports `FE/src/hooks/useLocale.ts:23-38`, antd map `:43-60` (16 locales, no ar/fa/he) |
| ECharts map has AR | TRUE | `FE/plugins/plugin-chart-echarts/src/components/echartsLocale.ts:46` (AR), `:54` (FA) |
| Existing RTL/direction code | NONE | repo-wide grep for `rtl`, `dir=`, `direction: 'rtl'`, `unicode-bidi` finds only two comments (`FE/src/filters/components/common.ts:33`, `FE/src/chartCustomizations/components/common.ts:33`) and an unrelated editor selection type (`FE/packages/superset-core/src/editors/index.ts:103`) |

Upstream: issue https://github.com/apache/superset/issues/25258 (closed) and PR https://github.com/apache/superset/pull/34629 "feat: RTL Text Support" (closed 2026-10-08, NOT merged, 25 files). That PR stored `direction` as a theme token in `THEME_DEFAULT`, created an LTR/RTL cache pair per `Theme` instance and passed `stylisPlugins: [stylisRTLPlugin]` without the prefixer. Sections 6-7 deliberately differ on all three points.

## 1. Locale lifecycle (as built)

| Stage | What happens | Evidence |
|---|---|---|
| Allowed locales | `LANGUAGES` defaults to `{}` (i18n off); FAB then forces `{"en": ...}`. Fork demo enables `en` + `ar`, default `en` | `superset/config.py:586,590-621,624`; FAB v5.3.0 `flask_appbuilder/babel/manager.py:16-17`; `nxtbi/config/superset_config.py:395-399` |
| Locale selector | FAB `BabelManager.get_locale`: (1) request arg `_l_=<lang>` if in `LANGUAGES`, per request, not persisted; (2) `session["locale"]`; (3) else writes `BABEL_DEFAULT_LOCALE` into the session. No `Accept-Language` negotiation | FAB v5.3.0 `babel/manager.py:34,48-61` (https://github.com/dpgaspar/Flask-AppBuilder/blob/v5.3.0/flask_appbuilder/babel/manager.py); pinned `requirements/base.txt:123` |
| Switch route | `GET /lang/<locale>`: 404 if unknown, `session["locale"] = locale`, `refresh()`, 302 to `Referer` | `superset/initialization/__init__.py:1835-1853` |
| Persistence | Flask session only. No user-model column, no API. Lost on `session.clear()` | only writer `superset/initialization/__init__.py:1848`; `superset/security/session_invalidation.py:145` |
| Bootstrap payload | `common.locale` = `get_locale()` normalised (`zh_TW` kept if configured, else base language); memoised 60 s per `(user_id, locale)`; `menu_data.navbar_right.{languages,locale,show_language_picker}`; `common.language_pack` is `None` unless an operator override supplies one | `superset/views/base.py:583-586,621-632,675,698-716,303-306,346-354` |
| Language pack | content-addressed classic script `/language_pack/<lang>/<version>/script.js` sets `window.__SUPERSET_LANGUAGE_PACK__`, loaded before the entry bundle; none for `en` | `superset/views/base.py:719-754`; `superset/views/core.py:720-757`; `spa.html:178-180,187-203` |
| Templates served | only `spa.html` (all views, via `render_app_template`) and `oauth2.html` (popup, English text). No FAB HTML templates remain. Embedded renders `spa.html` directly with `entry="embedded"`, bypassing `get_spa_template_context` | `superset/templates/superset/`; `superset/views/base.py:249-271,811-902,908-910`; `superset/embedded/view.py:121-128`; `superset/templates/superset/oauth2.html:21,37` |
| Client init | `preamble.ts` (prepended to every webpack entry) `configure()`s the translator, `lang = common.locale`, `setupFormatters(..., lang)`, then `dayjs.locale(toDayjsLocale(lang))`. For `ar` this is a silent no-op: `dayjs/locale/ar` is never imported and dayjs ignores unknown names | `FE/src/preamble.ts:52,56,58-62,91-92,108-112`; `FE/webpack.config.js:252-258`; `FE/node_modules/dayjs/esm/index.js:15-35` |
| Language picker | plain anchors `<Typography.Link href={languages[k].url}>` -> full navigation to `/lang/<k>` -> full reload | `FE/src/features/home/LanguagePicker.tsx:65`; `FE/src/features/home/RightMenu.tsx:401,643` |
| antd locale | NOT global. `useLocale()` (redux `common.locale`) is consumed by one component and passed to a local `ConfigProvider` | `FE/src/hooks/useLocale.ts:79-108`; `FE/src/explore/components/controls/DateFilterControl/components/CustomFrame.tsx:51,118` |
| ECharts locale | `common.locale.toUpperCase()` -> `loadLocale` -> `registerLocale` -> `init(dom, null, { locale })` | `FE/plugins/plugin-chart-echarts/src/components/Echart.tsx:190-192,206-215` |
| ag-grid locale | 9 pagination strings through `t()`; no `enableRtl`; single render site | `FE/plugins/plugin-chart-ag-grid-table/src/AgGridTable/index.tsx:840`; `FE/packages/superset-ui-core/src/components/ThemedAgGridReact/index.tsx:202` |
| Reports/screenshots | webdriver has no locale handling -> machine session -> `BABEL_DEFAULT_LOCALE` | no match for `locale` in `superset/utils/webdriver.py`, `screenshots.py`, `machine_auth.py` |
| Embedded SDK | no locale option; arbitrary `urlParams` are appended to the iframe URL, so `_l_=ar` works today | `superset-embedded-sdk/src/index.ts:401-407,451` |

## 2. Theme / provider architecture (as built)

Provider stack rendered by `Theme.SupersetThemeProvider` (`FE/packages/superset-core/src/theme/Theme.tsx:302-311`):
`EmotionCacheProvider(cache)` > emotion `ThemeProvider(theme)` > `<GlobalStyles/>` > antd `ConfigProvider theme={antdConfig}` > children.

| Fact | Evidence |
|---|---|
| A NEW Emotion cache (`key: 'superset'`, no nonce/container/stylisPlugins) is created on every provider mount and on every `setConfig()` (theme switch, dark toggle, dashboard theme change). Emotion itself warns that same-key caches "fight" | `Theme.tsx:163,262`; `FE/node_modules/@emotion/cache/src/index.ts:58-59`. Introduced by PR #31590 (`dd129fa403`); no rationale found in code (UNVERIFIED why) |
| `ConfigProvider` receives only `theme` (no `direction`, `locale`, `getPopupContainer`) | `Theme.tsx:306` |
| antd nested `ConfigProvider` inherits every unset key from its parent, so `direction` set once at the root reaches nested providers and portals | `FE/node_modules/antd/es/config-provider/index.js:311-318` |
| `GlobalStyles` renders inside every provider (also nested dashboard ones); already uses one logical property | `FE/packages/superset-core/src/theme/GlobalStyles.tsx:38-39,116` |
| Global singleton `themeObject = Theme.fromConfig()`; public exports `styled`, `css`, `ThemeProvider`, `EmotionCacheProvider`, `createEmotionCache`, `useTheme` | `FE/packages/superset-core/src/theme/index.tsx:34-42,50-63` |
| Host wrapper adds `ThemeContext`, swaps `currentTheme.SupersetThemeProvider`, already writes an `<html>` attribute (`data-theme-mode`) | `FE/src/theme/ThemeProvider.tsx:36,67-70,184-190` |
| `ThemeController` owns the global `Theme`, mutates it in place (`setConfig`) | `FE/src/theme/ThemeController.ts:136,146,1025,1044`; `createDashboardThemeProvider` `:288-333` |
| Dashboard theme = NESTED provider from a second `Theme` instance, updated in place | `FE/src/components/CrudThemeProvider.tsx:82-92,97,133-135`; mounted at `FE/src/dashboard/containers/DashboardPage.tsx:629` |
| Per-chart nested `ConfigProvider` (only `getPopupContainer`, for fullscreen) | `FE/src/dashboard/components/gridComponents/ChartHolder/ChartHolder.tsx:339` |
| Module state in `@apache-superset/core` can be duplicated per webpack chunk (reason the language pack lives on `window`) | `FE/packages/superset-core/src/translation/TranslatorSingleton.ts:38-44` |
| Module federation shares `react`, `react-dom`, `antd`, `@apache-superset/core` as eager singletons; `@emotion/react` is NOT shared. Extensions receive the core namespaces on `window.superset` | `FE/webpack.config.js:187-210`; `FE/src/extensions/ExtensionsStartup.tsx:56-68` |

Every provider instance and React root:

| Kind | Location | Note |
|---|---|---|
| Emotion cache + ConfigProvider | `Theme.tsx:163,262,303-310` | the only production one; all roots go through it |
| Emotion cache `key: 'menu'` | `FE/src/views/menu.tsx:43-45,63-64` | `menu` entry (`webpack.config.js:325`); no backend template contains `app-menu`, so it is dead code. Leave untouched |
| ConfigProvider (pass-through) | `AntdThemeProvider/index.tsx:22-27` | used at `ChartHolder.tsx:339`, `CustomFrame.tsx:118` |
| ConfigContext readers | `FE/packages/superset-ui-core/src/components/Select/Select.tsx:159-161`, `AsyncSelect.tsx:164-166` | read `getPopupContainer` only |
| Root: SPA | `FE/src/views/index.tsx:28-34` -> `App` -> `FE/src/views/RootContextProviders.tsx:34,45` | standalone and report-screenshot modes use this same entry (`superset/views/core.py:326,370,630`; `spa.html:65-71,140`) |
| Root: embedded | `FE/src/embedded/index.tsx:233-235` -> `FE/src/embedded/EmbeddedContextProviders.tsx:54-57,71` | in-memory theme storage; Switchboard `setThemeConfig`/`setThemeMode` at `index.tsx:327-364` |
| Root: plugin-private | `FE/plugins/plugin-chart-cartodiagram/src/components/ChartLayer.tsx:201` | `createRoot` per map feature; gets theme and locale as plain args, no host context |
| Test wrappers | `FE/spec/helpers/testing-library.tsx:91-98`, `FE/packages/superset-core/src/testing.tsx:27`, `FE/packages/superset-ui-core/src/spec/index.tsx:27` | default wrapper is a bare emotion `ThemeProvider` unless `useTheme: true` |
| Webpack entries | `preamble`, `theme` (prod only), `menu`, `spa`, `embedded`, `service-worker` | `FE/webpack.config.js:321-328` |

## 3. Portals, popups, out-of-tree DOM

| Mechanism | Sites | RTL consequence |
|---|---|---|
| antd `getPopupContainer`/`getContainer` | 53 uses in 28 files; ~20 force `() => document.body` (e.g. `FE/src/features/tags/TagModal.tsx:338`, `FE/src/explore/components/controls/DateFilterControl/DateFilterLabel.tsx:391`) | fine once `<html dir>` exists: React context (antd direction, Emotion cache) crosses portals, CSS `direction` is inherited from `<html>` |
| `ReactDOM.createPortal` | `FE/src/components/Chart/ChartContextMenu/ChartContextMenu.tsx:444`; `FE/src/dashboard/components/resizable/ResizableContainer.tsx:399` | context preserved; both place with JS pixel coordinates (see 4c) |
| `react-reverse-portal` | `FE/src/views/App.tsx:188,280`; `FE/src/dashboard/components/nativeFilters/FilterBar/FilterControls/FilterControls.tsx:196`, `FilterControl.tsx:60` | context preserved; the detached node has no `dir` of its own, so inheritance from `<html>` is mandatory |
| Modals / toasts | `Modal.useModal` (`FE/src/components/Datasource/DatasourceModal/index.tsx:128`), one static `Modal.confirm` (`FE/src/features/apiKeys/ApiKeyList.tsx:82`, renders outside ConfigProvider), in-tree toasts with physical CSS (`FE/src/components/MessageToasts/Toast.tsx:50,62,70`) | static call needs `ConfigProvider.config`/`useModal`; toasts are flipped by the plugin |
| react-dnd | `HTML5Backend` at `RootContextProviders.tsx:48`; custom layer `FE/src/dashboard/components/dnd/AddSliceDragPreview.tsx:81`; `DragDroppable.tsx:222` | drag layer positions with x/y in JS |
| ECharts tooltip | DOM appended to `document.body`, class `echarts-tooltip`; HTML string built with inline `text-align`/`padding-left` | `FE/plugins/plugin-chart-echarts/src/utils/tooltip.ts:36-40`; `FE/packages/superset-ui-core/src/utils/tooltip.ts:130-131` (inline, not flipped) |
| ag-grid | popups stay inside the grid root (no `popupParent` anywhere); `enableRtl` exists in the installed version | `FE/node_modules/ag-grid-community/dist/types/src/entities/gridOptions.d.ts:1144` |
| Ace | autocomplete popup is re-parented by hand | `FE/packages/superset-ui-core/src/components/AsyncAceEditor/index.tsx:264-306`; editor at `:562` |
| Off-screen helpers | `left: -9999px` style hacks create a horizontal scrollbar in RTL documents | `FE/src/utils/downloadAsImage.tsx:358-361` (cssText), `FE/packages/superset-ui-chart-controls/src/shared-controls/components/RadioButtonControl.tsx:130` (style object), `FE/packages/superset-ui-core/src/dimension/svg/createHiddenSvgNode.ts:26` |
| Second antd copy | geostyler bundles antd 5.29.3 with its own ConfigContext | `FE/package-lock.json` (`node_modules/geostyler/node_modules/antd`); `FE/src/explore/components/controls/LayerConfigsControl/GeoStylerWrapper.tsx:28` |

## 4. Styling inventory

Legend: (a) camelCase physical props in JS objects (`marginLeft`, `paddingRight`, `borderLeft*`, `textAlign:'left'`...), NOT fixed by a stylis plugin unless the object goes through Emotion `css()`; (a2) JS object keys `left:`/`right:` (estimate; in plugins mostly ECharts option keys); (c) JS geometry (`getBoundingClientRect`, `offsetLeft`, `scrollLeft`, `clientX`, `translateX`, `scrollWidth`...); (d) antd physical placement (`placement="...Left/Right"`, `align="left"`, `tabPosition`, `expandIconPosition`, `iconPosition`); (css) physical declarations inside Emotion template literals, which the plugin DOES flip; (log) logical properties already present.

| Area | (a) | (a2) | (c) | (d) | (css) flipped | (log) |
|---|---|---|---|---|---|---|
| `src/dashboard` | 14 | 12 | 22 in 11 files | 14 | 185 | 4 |
| `src/explore` | 19 | 8 | 24 in 12 | 25 | 113 | 4 |
| `src/SqlLab` | 4 | 1 | 2 in 1 | 6 | 36 | 0 |
| `src/features` | 3 | 1 | 1 in 1 | 17 | 113 | 6 |
| `src/components` | 4 | 3 | 24 in 9 | 7 | 68 | 1 |
| `src/pages` | 0 | 0 | 0 | 11 | 40 | 0 |
| `packages/superset-ui-core` | 21 | 7 | 31 in 12 | 10 | 79 | 6 |
| `packages/superset-ui-chart-controls` | 2 | 5 | 1 in 1 | 3 | 16 | 0 |
| `plugins/*` | 8 | 52 | 62 in 36 | 2 | 135 | 0 |
| Whole frontend | 76 in 45 files | n/a | ~167 in 84 | 95 in 76 | 790 in 298 | ~30 in 19 |

(b) Plain stylesheets still bundled: one own file, `FE/plugins/plugin-chart-point-cluster-map/src/MapLibre.css`. Third-party CSS imports: `maplibre-gl.css` (`plugins/preset-chart-deckgl/src/DeckGLContainer.tsx:47`, `plugin-chart-point-cluster-map/src/MapLibre.tsx:33`), `ol/ol.css` (`plugin-chart-cartodiagram/src/CartodiagramPlugin.tsx:29`), `react-js-cron/dist/styles.css` (`packages/superset-ui-core/src/components/CronPicker/index.tsx:25`), `react-checkbox-tree.css` (`src/dashboard/components/filterscope/treeIcons.tsx:20`), `geostyler/dist/index.css` (`GeoStylerWrapper.tsx:28`), `@fontsource/*` (`GlobalStyles.tsx:22-28`), FAB `flags16.css` (`spa.html:104`). No `.less`. Strict single-line `style={{...}}` with a physical prop: 9 in 7 files.
antd only flips DEFAULT placements; an explicit `placement` is never mirrored (`FE/node_modules/antd/es/dropdown/dropdown.js:108`, `select/index.js:212`), so the 95 (d) sites need a helper.
Resizers: `re-resizable` (`FE/src/components/ResizableSidebar/index.tsx:20`, `FE/src/explore/components/ExploreViewContainer/index.tsx:55`, `ResizableContainer.tsx:28`, `FE/packages/superset-ui-core/src/components/Modal/Modal.tsx:33`), `react-split` (`FE/src/explore/components/ExploreChartPanel/index.tsx:21`), antd `Splitter` (`App.tsx:211`, `FE/src/SqlLab/components/SqlEditor/index.tsx:966`, `FE/src/SqlLab/components/AppLayout/index.tsx:105`).

Top 40 files by weighted score (3a + 3c + 2d + css + a2), false positives removed (`theme/types.ts` matches the `screenXS` tokens; `eChartOptionsSchema.ts` matches zod keys). All under `FE/`:

| # | File | a/css/c/d | # | File | a/css/c/d |
|---|---|---|---|---|---|
| 1 | `src/dashboard/components/resizable/ResizableContainer.tsx` | 0/10/7/0 | 21 | `src/components/Datasource/FoldersEditor/hooks/useDragHandlers.ts` | 0/0/5/0 |
| 2 | `src/dashboard/components/DashboardBuilder/DashboardBuilder.tsx` | 5/8/2/1 | 22 | `src/dashboard/components/nativeFilters/FilterBar/FilterControls/GroupByFilterCard.tsx` | 2/4/0/2 |
| 3 | `src/explore/components/controls/OptionControls/index.tsx` | 0/19/1/0 | 23 | `packages/superset-ui-chart-controls/src/utils/headerGroups.ts` | 0/6/0/1 |
| 4 | `plugins/plugin-chart-table/src/TableChart.tsx` | 2/12/3/1 | 24 | `src/features/datasets/AddDataset/DatasetPanel/DatasetPanel.tsx` | 0/9/0/0 |
| 5 | `packages/superset-ui-core/src/components/ButtonGroup/index.tsx` | 9/0/0/0 | 25 | `src/dashboard/components/DashboardGrid.tsx` | 0/4/2/0 |
| 6 | `src/explore/components/ControlPanelsContainer.tsx` | 4/4/0/5 | 26 | `src/dashboard/components/AddSliceCard/AddSliceCard.tsx` | 0/6/2/0 |
| 7 | `src/explore/components/controls/DndColumnSelectControl/useResizeButton.tsx` | 0/0/8/0 | 27 | `src/utils/downloadAsImage.tsx` | 0/1/4/0 |
| 8 | `src/components/Chart/ChartContextMenu/ChartContextMenu.tsx` | 0/1/7/0 | 28 | `packages/superset-ui-core/src/components/Collapse/Collapse.tsx` | 0/2/0/6 |
| 9 | `packages/superset-ui-core/src/components/DropdownContainer/DropdownContainer.tsx` | 0/5/6/0 | 29 | `src/features/alerts/AlertReportModal.tsx` | 0/12/0/1 |
| 10 | `src/dashboard/components/filterscope/FilterScopeSelector.tsx` | 0/20/0/0 | 30 | `src/explore/components/controls/ColumnConfigControl/ColumnConfigItem.tsx` | 3/1/0/1 |
| 11 | `plugins/plugin-chart-horizon/src/HorizonRow.tsx` | 0/0/6/0 | 31 | `src/explore/components/controls/VizTypeControl/VizTypeGallery.tsx` | 0/10/0/1 |
| 12 | `plugins/plugin-chart-ag-grid-table/src/styles/index.tsx` | 0/13/1/0 | 32 | `packages/superset-ui-core/src/components/Button/index.tsx` | 4/0/0/0 |
| 13 | `packages/superset-ui-core/src/components/Table/VirtualTable.tsx` | 0/2/5/0 | 33 | `src/explore/components/controls/CustomListItem/index.tsx` | 4/0/0/0 |
| 14 | `packages/superset-ui-core/src/components/Modal/Modal.tsx` | 0/8/1/0 | 34 | `plugins/plugin-chart-table/src/DataTable/hooks/useSticky.tsx` | 0/0/4/0 |
| 15 | `plugins/plugin-chart-pivot-table/src/react-pivottable/Styles.ts` | 0/13/0/0 | 35 | `src/features/home/Menu.tsx` (+ `RightMenu.tsx`) | 0/7/0/1 |
| 16 | `src/features/home/SubMenu.tsx` | 0/15/0/0 | 36 | `packages/superset-ui-core/src/components/DynamicEditableTitle/index.tsx` | 0/1/3/0 |
| 17 | `src/features/databases/DatabaseModal/styles.ts` | 0/16/0/0 | 37 | `src/dashboard/components/gridComponents/Tabs/Tabs.tsx` (+ `TabsRenderer/TabsRenderer.tsx`) | 1/5/2/0 |
| 18 | `src/components/Datasource/FoldersEditor/TreeItem.styles.ts` | 0/13/1/0 | 38 | `src/dashboard/components/dnd/AddSliceDragPreview.tsx` | drag layer |
| 19 | `src/explore/components/ExploreViewContainer/index.tsx` | 1/5/1/1 | 39 | `packages/superset-ui-core/src/utils/tooltip.ts` | inline HTML `:130-131` |
| 20 | `src/dashboard/components/nativeFilters/FilterBar/FilterControls/FilterControlShared.tsx` | 1/5/0/3 | 40 | `packages/superset-ui-chart-controls/src/shared-controls/components/RadioButtonControl.tsx` | `left:-9999px` `:130` |

Highest-risk pattern (not countable by grep): a JS-measured pixel value interpolated into an Emotion rule (`left: ${x}px`). The plugin would turn it into `right: Xpx`. Rows 1, 7, 8, 9, 13, 34, 38 must be read line by line; inline `style={{ left }}` stays physical and correct.

## 5. Type surface: where `direction` may live

| Candidate | Decision | Why |
|---|---|---|
| Theme JSON / `SerializableThemeConfig` / `THEME_DEFAULT` | NO | themes are DB rows applied per dashboard (`CrudThemeProvider.tsx:63-74`); direction is a per-user locale property. antd `ThemeConfig` has no direction. `FE/packages/superset-core/src/theme/types.ts:75-82`. Backend `is_valid_theme` type-checks only `token/components/hashed/inherit/algorithm` and silently accepts unknown top-level keys (`superset/themes/utils.py:136-149`), so nothing would stop a stray value |
| `EXTRA_THEME_TOKENS` | NO | whitelist for deployment-specific tokens in the theme editor (`superset/config.py:1239-1243`, `FE/src/theme/utils/antdTokenNames.ts:35`) |
| `SupersetSpecificTokens.direction` | YES, runtime-only | `types.ts:112-270`; injected by the provider so `({ theme }) => theme.direction` works in `styled`. Never serialised: `toSerializedConfig()` reads `antdConfig` (`Theme.tsx:170-172`). Must be stripped from user tokens because `...antdConfig.token` is spread into `theme` (`Theme.tsx:149-151`). Not in `allowedAntdTokens` (`types.ts:277`) and not in `SUPERSET_CUSTOM_TOKENS` (`antdTokenNames.ts:44`), so the editor keeps flagging it as unknown |
| antd `ConfigProvider direction` | YES | the antd-native slot |
| Bootstrap `common.direction` | YES | next to `common.locale` (`superset/views/base.py:675`; type `FE/src/types/bootstrapTypes.ts:167`) |
| `ThemeContextType` / `ThemeController` | NO setter | direction is constant for a page lifetime (section 6.5); `types.ts:532-562` unchanged |

## 6. Proposed architecture

### 6.1 Single source of truth
Server computes direction from the active Babel locale; the DOM carries it; React reads the DOM once at the root and then propagates through the Emotion theme.

- Server: `babel.Locale.text_direction` returns `'rtl'`/`'ltr'` from CLDR (Babel v2.17.0 `babel/core.py:1067-1075`; pinned `requirements/base.txt:25`), so no hand-kept list on the backend. `flask_babel.get_locale()` already yields a `Locale`.
- Transport: `<html lang dir>` for first paint plus `common.direction` in the bootstrap payload.
- Client truth: `document.documentElement.dir`. The DOM is used, not module state, because `@apache-superset/core` modules can be instantiated more than once (`TranslatorSingleton.ts:38-44`).
- Client fallback list (tests, storybook, missing attribute): `RTL_LANGUAGES = ['ar','fa','he','iw','ur','ps','sd','ug','yi','dv','ckb']`, matched on the base language subtag.
- Public API, new file `FE/packages/superset-core/src/theme/direction.ts`, re-exported from `theme/index.tsx` (already an export path, `FE/packages/superset-core/package.json` `"./theme"`): `type Direction`, `RTL_LANGUAGES`, `getDirectionForLocale(locale)`, `getDocumentDirection()`, `useDirection()` (= emotion theme `direction` ?? document), `getEmotionCache(direction)`, `noFlip`, `LtrIsolate`, `flipPlacement(placement, direction)`.
- Kill switch: backend config `RTL_LAYOUT_ENABLED = True`; when false the helper returns `'ltr'` and the whole client stays LTR.

### 6.2 Provider changes (`Theme.tsx`)
```tsx
// direction.ts - one cache per direction for the whole page, survives duplicated module copies
const REG = Symbol.for('superset.emotion.caches');
export function getEmotionCache(direction: Direction): EmotionCache {
  const reg = ((globalThis as any)[REG] ||= {});
  return (reg[direction] ||= createCache(
    direction === 'rtl'
      ? { key: 'superset-rtl', stylisPlugins: [prefixer, rtlPlugin] } // prefixer from 'stylis'
      : { key: 'superset' },                                          // unchanged LTR output
  ));
}
// Theme.tsx
SupersetThemeProvider({ children, direction: prop }: { children: React.ReactNode; direction?: Direction }) {
  const parent = useEmotionTheme() as Partial<SupersetTheme>;         // {} at the root
  const direction = prop ?? parent.direction ?? getDocumentDirection();
  const [state, setState] = React.useState({ theme: this.theme, antdConfig: this.antdConfig });
  const theme = React.useMemo(() => ({ ...state.theme, direction }), [state.theme, direction]);
  return (
    <EmotionCacheProvider value={getEmotionCache(direction)}>
      <ThemeProvider theme={theme}>
        <GlobalStyles />
        <ConfigProvider theme={state.antdConfig} direction={direction}>{children}</ConfigProvider>
      </ThemeProvider>
    </EmotionCacheProvider>
  );
}
```
- Distinct keys are mandatory: an Emotion class is `key-hash(unflipped source)`, so one key for two directions would give one class name two different bodies.
- Remove the cache from `notifyProviders`/listener state (`Theme.tsx:159-164,235-251,259-263,284-294`). Result: nested dashboard providers, theme switches and dark toggles all reuse the two page-level caches, so no duplicate `<style>` containers and no stale-cache class of bug. This changes current behaviour (new cache per update), so regression-test dark toggle and dashboard theme switch.
- `stylisPlugins` REPLACES Emotion's default `[prefixer]` (`@emotion/cache/src/index.ts:40,89`); pass `[prefixer, rtlPlugin]`.
- Strip `direction` from user tokens in `setConfig` right after `Theme.tsx:129`.
- `GlobalStyles.tsx`: no direction rule needed (the attribute does it); add `.echarts-tooltip` rules only if tooltips must be forced to one direction.
- antd needs nothing else: its own CSS-in-JS (`@ant-design/cssinjs` 2.1.2) is logical-property based and keyed on `direction`; it does not pass through the Emotion cache.

Why `stylis-plugin-rtl` and not a mass rewrite: 790 physical declarations in 298 files would become a permanent merge-conflict surface against upstream. Policy: plugin for existing code, logical properties for new or touched code (the plugin leaves them alone; 19 files already use them). Considered and deferred: a custom stylis plugin that rewrites physical to logical properties (single cache, isolation by `dir` attribute alone), because it changes LTR output for every user and needs its own maintenance.

cssjanus behaviour that matters (cssjanus 2.3.0 `src/cssjanus.js:149-173,375-396`): flips `left/right`, 4-value shorthands, `border-radius`, shadows, background-position, `e/w-resize` cursors, `translate`/`translateX`, and ALSO `direction: ltr` <-> `rtl`. A rule written to force LTR with CSS would be inverted, so isolation uses the `dir` attribute, never CSS `direction`.

### 6.3 LTR isolation primitive
```tsx
export const noFlip = '/* @noflip */';   // usage: css`${noFlip} left: 0;`
export function LtrIsolate({ as: Tag = 'div', children, ...rest }) {
  const parent = useEmotionTheme();
  const theme = React.useMemo(() => ({ ...parent, direction: 'ltr' as const }), [parent]);
  return (
    <EmotionCacheProvider value={getEmotionCache('ltr')}>
      <ThemeProvider theme={theme}>
        <ConfigProvider direction="ltr"><Tag dir="ltr" {...rest}>{children}</Tag></ConfigProvider>
      </ThemeProvider>
    </EmotionCacheProvider>
  );
}
```
- Subtree effect: Emotion styles are not flipped, antd renders LTR, the UA stylesheet gives `[dir]` elements `direction: ltr; unicode-bidi: isolate`.
- Inline identifiers inside Arabic sentences (column names, SQL fragments, numbers with units): `<bdi dir="ltr">` via `LtrIsolate as="bdi"`. User-authored text (dashboard and chart titles, markdown): `dir="auto"`.
- `noFlip` is passed as an INTERPOLATION so no build-time minifier can strip it. Verified by source only: `@emotion/babel-plugin` keeps comments containing `@` (`FE/node_modules/@emotion/babel-plugin/src/utils/minify.js:39-45`), stylis-plugin-rtl 2.1.1 re-serialises comments before calling cssjanus (`dist/stylis-rtl.js`), cssjanus honours the directive (`src/cssjanus.js:114`). `@swc/plugin-emotion` 20.0.2 (production, `FE/webpack.config.js:286-293`) is UNVERIFIED for literal comments, hence the interpolation. Jest gate in 6.6 is mandatory.
- Apply at choke points: `FE/packages/superset-ui-core/src/chart/components/SuperChart.tsx` (`chartWithoutWrapper` at `:280-281`, used at `:296,299`; container div in `SuperChartCore.tsx:318`; all charts LTR by default, then opt selected viz types back in from one host-side set: table, pivot, ag-grid, big number, handlebars), `AsyncAceEditor/index.tsx:562`, `FE/packages/superset-ui-core/src/components/CodeSyntaxHighlighter/index.tsx:171,192`, `FE/src/core/editors/EditorHost.tsx` (extension editors). Canvas text keeps shaping Arabic correctly inside `dir="ltr"`; only the base direction changes, which avoids trailing-minus and reordered-punctuation artefacts in axis labels.
- Caveat: popups portalled to `body` from inside an island get LTR context but inherit `rtl` from `<html>`; give those popups a `getPopupContainer` inside the island.

### 6.4 Locale wiring
| Library | Change | Evidence that the asset exists |
|---|---|---|
| dayjs | `import 'dayjs/locale/ar'` (+ `fa`, `he`, `ur`) in `useLocale.ts:23-38`. Do NOT extend `preParsePostFormat`: the `ar` locale ships digit conversion that only activates with that plugin, and `dates.ts` does not load it. `ar` sets `weekStart: 6`, which shifts `startOf('week')` | `FE/node_modules/dayjs/locale/ar.js`; `FE/packages/superset-ui-core/src/utils/dates.ts:30-37` |
| antd | add `ar: ar_EG`, `fa: fa_IR`, `he: he_IL`, `ur: ur_PK` to `LOCALE_MAPPING` (`useLocale.ts:43-60`); preload in `initPreamble` (every entry awaits it: `views/index.tsx:31`, `embedded/index.tsx:65`) and mount one `<AntdThemeProvider locale>` inside `SupersetThemeProvider` in `RootContextProviders.tsx:45` and `EmbeddedContextProviders.tsx:71`. It cannot use `useLocale()` there: that hook needs redux, which is mounted below (`RootContextProviders.tsx:45-46`) | `FE/node_modules/antd/locale/ar_EG.js`, `fa_IR.js`, `he_IL.js`, `ur_PK.js` |
| ECharts | nothing for locale (AR/FA present). Keep the canvas container LTR via 6.3; fix inline styles in `utils/tooltip.ts:130-131` | `FE/node_modules/echarts/i18n/langAR-obj.js` |
| ag-grid | in `ThemedAgGridReact/index.tsx:202` add `enableRtl={useDirection() === 'rtl'}` before `{...props}`. Init-time option, acceptable because direction is page-constant. Optional: merge `AG_GRID_LOCALE_EG` under the plugin's `localeText` | `gridOptions.d.ts:1144`; `@ag-grid-community/locale@36.3.0` exports `AG_GRID_LOCALE_EG`, `_IR`, `_IL`, `_PK` |
| Ace | no RTL mode; wrap in `LtrIsolate` | `AsyncAceEditor/index.tsx:562` |
| Formatters | `setCurrencyLocale(locale)` and duration formatter receive `ar` (`FE/src/setup/setupFormatters.ts:46,84`). Whether `Intl` then emits Arabic-Indic digits is UNVERIFIED; decide `ar-u-nu-latn` explicitly | - |

### 6.5 Switching language
Reload stays, and is the only safe option: the picker is a server round trip (`LanguagePicker.tsx:65` -> `superset/initialization/__init__.py:1848-1853`); module-level `t()` constants are evaluated once (`preamble.ts:79-87`, `menu.tsx:53-58`); the translator, dayjs global locale, ECharts instances (`Echart.tsx:214`) and formatter registries are initialised once. Consequence: direction is immutable per page load, so the provider needs no setter and the caches never switch. A live toggle exists only as the `direction` prop for tests and storybook.
Persistence gaps to decide separately: locale lives only in the Flask session; embedded and report contexts should pass `?_l_=ar` (FAB `manager.py:51-56`; SDK `urlParams` at `superset-embedded-sdk/src/index.ts:401-407`).

### 6.6 Test strategy
Existing infra: `snapshotSerializers: ['@emotion/jest/serializer']` (`FE/jest.config.js:77`), `expect.extend(matchers)` (`FE/spec/helpers/setup.ts:24,35`), `toHaveStyleRule` already used in 15 test files. Jest uses `@emotion/babel-plugin` (`FE/babel.config.js:56`), production uses SWC, so one Playwright check is required.

| Test file (new unless noted) | Asserts |
|---|---|
| `packages/superset-core/src/theme/direction.test.ts` | `getDirectionForLocale` table (`ar`, `ar_SA`, `fa`, `he`, `en`, `zh_TW`, `sr_Latn`, `''`); `getDocumentDirection` follows `<html dir>` |
| `.../theme/emotionCache.test.tsx` | `getEmotionCache('rtl')` is referentially stable, key `superset-rtl`; `margin-left: 4px` -> `toHaveStyleRule('margin-right','4px')`; `padding: 1px 2px 3px 4px` -> `1px 4px 3px 2px`; vendor prefixes still emitted; `${noFlip} left: 0` stays `left`; logical properties untouched |
| `.../theme/SupersetThemeProvider.test.tsx` (extend) | with `dir="rtl"` an antd `Button` has `ant-btn-rtl`; a nested provider from a second `Theme` inherits rtl with the same cache object; after `theme.setConfig()` x3 the number of `style[data-emotion^="superset"]` nodes does not grow |
| `.../theme/LtrIsolate.test.tsx` | inside an rtl root: `dir="ltr"`, child keeps `margin-left`, antd child has no `-rtl` class, `theme.direction === 'ltr'` |
| `spec/helpers/testing-library.tsx` (edit `:76-98`) | new `direction` option sets `<html dir>`, forces the `useTheme` wrapper, resets in `afterEach` |
| `tests/unit_tests/...` (pytest) | `get_text_direction('ar') == 'rtl'`, `'en'`, garbage -> `'ltr'`, kill switch; rendered `spa.html` contains `<html lang="ar" dir="rtl">`; `common['direction']` |
| `playwright/tests/` | production build: `/lang/ar` -> `html[dir=rtl]`, a known flipped rule and a `noFlip` rule checked through `getComputedStyle` |
Note: `Theme.test.tsx:51-54` mocks `@emotion/cache` to return `{}`; keep `createCache` imported as the default export and put cache assertions in files without that mock.

## 7. Change list, in an order that keeps the app working

| Step | File | Change | Visible effect |
|---|---|---|---|
| 1 | `FE/packages/superset-core/package.json` (`dependencies` `:95`), `FE/package.json`, lockfile | add deps (section 8) | none |
| 1 | `FE/packages/superset-core/src/theme/direction.ts` (new), `theme/index.tsx`, `theme/types.ts:112` | API from 6.1; `direction?: Direction` on `SupersetSpecificTokens` | none |
| 1 | `FE/packages/superset-core/src/theme/Theme.tsx` | 6.2: memoised cache, `direction` on ConfigProvider and theme, strip user `token.direction` | none while `<html>` has no `dir` |
| 2 | `SuperChart.tsx`, `AsyncAceEditor/index.tsx`, `CodeSyntaxHighlighter/index.tsx`, `src/core/editors/EditorHost.tsx` | wrap in `LtrIsolate` | none in LTR (adds `dir="ltr"`) |
| 3 | `FE/src/hooks/useLocale.ts`, `FE/src/preamble.ts`, `RootContextProviders.tsx`, `EmbeddedContextProviders.tsx`, `ThemedAgGridReact/index.tsx` | 6.4 | Arabic dates and antd strings; layout still LTR |
| 4 | tests from 6.6 | - | none |
| 5 | `superset/translations/utils.py` | `get_text_direction(locale) -> Literal['ltr','rtl']` using `Locale.parse(str(locale), sep='_').text_direction`, `'ltr'` on any error or when `RTL_LAYOUT_ENABLED` is false | none |
| 5 | `superset/views/base.py:675` | `"direction": get_text_direction(language)` in the cached payload (cache key already includes locale, `:583-586`) | none |
| 5 | `superset/views/base.py:893-902`, `superset/embedded/view.py:121-128` | pass `html_lang` (locale with `_` -> `-`) and `html_dir` to the template; these are the only two `spa.html` render sites | none |
| 5 | `superset/templates/superset/spa.html:16` | `<html lang="{{ html_lang | default('en') }}" dir="{{ html_dir | default('ltr') }}">`; spinner at `:145` is centred with physical inline CSS and is unaffected | THE SWITCH: RTL locales flip |
| 5 | `FE/src/preamble.ts` (after `:56`), `FE/src/views/App.tsx:68-70`, `FE/src/types/bootstrapTypes.ts:167` | move the `lang` assignment into the preamble (covers embedded) and set `dir` from `common.direction ?? getDirectionForLocale(lang)` only if the attribute is missing | none |
| 6 | inventory files (section 4), static `Modal.confirm`, off-screen helpers, `flipPlacement` at the 95 (d) sites | per-area fixes | progressive polish |
Steps 1-4 are inert for every locale because nothing emits `dir` yet; step 5 is one small backend commit that can be reverted or disabled by config.

## 8. New npm dependencies (exact pins)

| Package | Pin | Checked against | Why |
|---|---|---|---|
| `stylis-plugin-rtl` | `2.1.1` | registry latest; `peerDependencies: { stylis: "4.x" }`, `dependencies: { cssjanus: "^2.0.1" }`; CJS `main` + ESM `module` | the RTL flip |
| `stylis` | `4.2.0` | must equal the copy `@emotion/cache@11.14.0` pins (`"stylis": "4.2.0"`) and that is hoisted at `FE/node_modules/stylis` (4.2.0), so plugin, prefixer and Emotion share one compiler | direct import of `prefixer` |
| `@types/stylis` (dev) | `4.2.7` | registry latest; stylis 4.2.0 ships no typings, none installed | TS types |
| `cssjanus` (transitive) | resolves to 2.3.x | 2.3.0 source inspected; 2.3.1 is latest | - |
| `@ag-grid-community/locale` (optional) | `36.3.0` | matches `ag-grid-community` 36.3.0 (`FE/package.json:157`) | Arabic grid strings |
Already present: `@emotion/jest` 11.14.2, `@emotion/react` 11.14.0, antd 6.6.8, echarts 6.1.0, dayjs 1.11.23.

## 9. Open items / UNVERIFIED
- Nothing here was executed: no install, no build, no test run. Section 6 code is a shape derived from reading sources.
- `@swc/plugin-emotion` comment handling; Jest resolution of `stylis-plugin-rtl` without a `transformIgnorePatterns` change; `Intl` digit output for `ar`.
- Why upstream recreates the Emotion cache on each `setConfig`.
- Extensions that bundle their own `@emotion/react` (it is not a federation singleton) will not see the host cache; they must import `styled`/`css` from `@apache-superset/core/theme`, or `@emotion/react` must be added to `shared` (contract change, needs a decision).
- geostyler's private antd 5 copy will not inherit `direction`.
- `Inter` and `IBM Plex Mono` (`GlobalStyles.tsx:22-28`) have no Arabic glyphs (no `U+06xx` range in `FE/node_modules/@fontsource/inter/400.css`; Plex Mono subsets are latin/cyrillic/vietnamese per its `metadata.json`); an Arabic-capable `fontFamily` is a theme-token decision outside this document.

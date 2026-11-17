# 03 - RTL surface audit (defect prediction)

Scope: `superset-frontend/` on `feature/nxtbi-arabic-rtl` (apache/superset `f3f3d10d5c` + nxtbi/ only). Read-only static audit, no build, nothing run in a browser.
Assumed target state: `<html dir="rtl" lang="ar">`, antd `ConfigProvider direction="rtl"`, Emotion CSS mirrored by `stylis-plugin-rtl` (2.1.1 -> `cssjanus ^2.0.1`, peer `stylis 4.x`; installed `stylis 4.2.0`, `@emotion/cache 11.14.0`).
All paths are relative to `superset-frontend/` unless they start with `superset/`. Verdicts: **FLIP** (let it mirror), **FIX** (code change), **ISOLATE-LTR** (force `dir="ltr"`).

## 1. Baseline verified on this commit

| Earlier claim | Status | Evidence |
|---|---|---|
| No `dir` on `<html>` | TRUE | `superset/templates/superset/spa.html:16` (`<html>`), `:140` (`<body>`); only template dir is `superset/templates/superset/` (spa.html + partials) so every Superset page is the SPA |
| No `lang` on `<html>` | **PARTLY FALSE** | set at runtime, SPA entry only: `src/views/App.tsx:70`; not set in embedded entry (`src/embedded/index.tsx`) nor `src/views/menu.tsx` |
| No antd `direction` | TRUE | single provider `packages/superset-core/src/theme/Theme.tsx:303-310` (`<ConfigProvider theme=...>`), no `direction`, no `locale` |
| No stylis RTL plugin | TRUE | `createCache({ key: 'superset' })` at `Theme.tsx:163` and `:262`; second cache `createCache({ key: 'menu' })` at `src/views/menu.tsx:43-45` |
| `useLocale` has no `ar` | TRUE | `src/hooks/useLocale.ts:23-38` (dayjs imports), `:43-60` (`LOCALE_MAPPING`); bundles exist: `node_modules/antd/locale/ar_EG.js`, `node_modules/dayjs/locale/ar.js` |
| ECharts locale map has AR | TRUE | `plugins/plugin-chart-echarts/src/components/echartsLocale.ts:49`; applied at `Echart.tsx:190-192`, `:215-216` |
| ag-grid RTL | not enabled | no `enableRtl` anywhere; single mount `packages/superset-ui-core/src/components/ThemedAgGridReact/index.tsx:202-204` |
| Legacy nvd3 charts | **GONE** | no `nvd3` in any `package.json`; plugin list = 17 dirs under `plugins/` |
| Upstream RTL | none | https://github.com/apache/superset/issues/25258 (closed, no implementation) |

Installed versions (from `node_modules/*/package.json`): antd 6.6.8, echarts 6.1.0, ag-grid-community 36.3.0, re-resizable 6.11.2, react-split 2.0.14 / split.js 1.6.5, react-dnd 11.1.3, @dnd-kit/core 6.3.1, react-ace 10.1.0, ace-builds 1.45.2, react-arborist 3.16.0, react-window 2.4.1, react-table 7.8.0.
Plain stylesheets are almost absent (3 local `.css` files); third-party CSS imported: react-checkbox-tree, react-js-cron, geostyler, ol, maplibre-gl. So the stylis plugin covers nearly all first-party CSS.

## 2. What the stylis/cssjanus flip does and does not do (drives every verdict)

Checked in `cssjanus` master `src/cssjanus.js` (lines 149-173, 379-407).

| Construct | Flipped? | Consequence |
|---|---|---|
| `margin/padding/border-left/right`, `left:`/`right:`, `float`, `text-align`, 4-value shorthands, `border-radius`, `box-shadow` x-offset | yes | ~1000 static declarations mirror for free -> FLIP |
| `transform: translateX(n)` / `translate(n, ..)` | yes (sign) | centering idiom `left:50%; translateX(-50%)` stays centred (`src/dashboard/containers/DashboardPage.tsx:136-138`, `HoverMenu.tsx:60-61`) |
| `translate3d(..)`, `rotate(..)`, `scaleX(..)` | no | rotated collapse icons point the wrong way |
| `left`/`right` inside parentheses, e.g. `linear-gradient(to right, ..)` | no | gradients keep physical direction |
| `direction: ltr` | **yes -> `rtl`** | never isolate with CSS `direction: ltr` in Emotion; use the HTML `dir="ltr"` attribute (or `/* @noflip */`, UNVERIFIED through Emotion) |
| `cursor: e-resize/w-resize` | yes | `col-resize`, `nwse-resize` unchanged |
| Logical properties (`inset-inline-*`, `margin-inline-*`) | no (already correct) | 15 files already use them; mixing is safe (`src/features/home/Menu.tsx:140-143`) |
| Inline `style={{ marginLeft }}` / `style.left = ..` / HTML strings | **no** | must be hand-converted; 60 camelCase physical props outside `css`/`styled` |
| Emotion CSS holding a **JS-measured physical pixel** (`left: ${clientX}px`) | **yes, wrongly** | the dangerous class: element lands mirrored. Move to inline `style` |
| JS pixel math (`clientX`, `getBoundingClientRect().right`, `scrollLeft`, `delta.x`) | no | must branch on direction |
| antd explicit `placement="bottomLeft"` etc. | no | antd only flips the *default* (`node_modules/antd/es/dropdown/dropdown.js:108`); 65 explicit physical placements in the codebase |

Library RTL behaviour verified in `node_modules`: antd Slider auto-reverses (`antd/es/slider/index.js:108-110`); antd Splitter is RTL-aware (`antd/es/splitter/Splitter.js:57-58`); antd Drawer placement is physical (`antd/es/drawer/Drawer.js:230`); re-resizable handles are inline-styled and physical (`re-resizable/lib/resizer.js:36-41`, math `lib/index.js:451-462`); split.js has no RTL support (https://github.com/nathancahill/split/issues/739, open); react-arborist indents with inline `paddingLeft` (`react-arborist/dist/module/components/row-container.js:35`); Ace forces `.ace_editor { direction: ltr; text-align: left }` in its own injected CSS; ag-grid forces `:where(.ag-ltr){direction:ltr}` unless `enableRtl` (`ag-grid-community/dist/types/src/entities/gridOptions.d.ts:1144`).

## 3. Central switches (one edit each)

| Purpose | Where | Change |
|---|---|---|
| Document direction, all entries (SPA, embedded, legacy menu) | `src/preamble.ts:55-56` (`lang` already resolved) and `superset/templates/superset/spa.html:16` | set `documentElement.dir/lang` before first paint; export `isRtl()` from one module |
| antd direction + locale | `packages/superset-core/src/theme/Theme.tsx:306` | `<ConfigProvider direction locale>` |
| Emotion mirroring | `Theme.tsx:163`, `:262`, `src/views/menu.tsx:43` | `createCache({ key, stylisPlugins: [prefixer, rtlPlugin] })`; use a different `key` per direction |
| Popup placement swap | wrappers `packages/superset-ui-core/src/components/{Tooltip,Popover,Dropdown}/index.tsx` (`Dropdown/index.tsx:95,117,124`) | map `*Left<->*Right`, `left<->right` when RTL; `Drawer/index.tsx:21` is a bare re-export and needs a wrapper |
| Direction-implying icons | `packages/superset-ui-core/src/components/Icons/BaseIcon.tsx:39-106` | add `mirrorInRtl` prop (`transform: scaleX(-1)` inline) |
| ag-grid | `ThemedAgGridReact/index.tsx:202` | `enableRtl={isRtl}`; covers SQL Lab results, Explore data panes (`src/components/GridTable/index.tsx:213`) and the ag-grid table chart (`plugins/plugin-chart-ag-grid-table/src/AgGridTable/index.tsx`) |
| **Chart plot-area isolation** | `packages/superset-ui-core/src/chart/components/SuperChartCore.tsx:306-318` (the `<div {...containerProps}>` every plugin renders into) | `containerProps.dir = metadata.direction ?? 'ltr'`; add optional `direction?: 'ltr' \| 'inherit'` to `ChartMetadata` (`chart/models/ChartMetadata.ts:28-62`) and set `'inherit'` only for HTML families (section 6). Fallback if metadata change is unwanted: wrapper div at `src/components/Chart/ChartRenderer.tsx:688` with a viz-type allow-list (misses direct `SuperChart` users such as DrillBy/Matrixify) |
| ECharts host only | `plugins/plugin-chart-echarts/src/components/Echart.tsx:475-477` | `dir="ltr"` on `<Styles className={ECHARTS_HOST_CLASS}>` |
| Code/SQL isolation | `packages/superset-ui-core/src/components/CodeSyntaxHighlighter/index.tsx:171,192`, `AsyncAceEditor/index.tsx` wrapper, `packages/superset-core/src/theme/GlobalStyles.tsx:42-73` | `dir="ltr"` attribute on wrappers; global `pre, code, kbd, samp { unicode-bidi: isolate; text-align: left }` guarded with noflip |

## 4. Area audit

### 4.1 Shell, list views, shared components (group A)

| Surface | Mechanism / evidence | Verdict |
|---|---|---|
| Top nav brand, items | Emotion physical CSS `src/features/home/Menu.tsx:67-74`; antd Menu | FLIP |
| Brand tooltip, mobile drawer | `Menu.tsx:439` `placement="bottomLeft"`; `RightMenu.tsx:803` Drawer `placement="right"` | FIX (placement swap) |
| Right menu, language picker | `RightMenu.tsx:104-105`; `LanguagePicker.tsx:44,64-66` (flag `<i>` + link) | FLIP; add `ar` flag/name check, keep language names in their own script |
| SubMenu / page tabs / buttons | `SubMenu.tsx:53-65,84-86` floats + `right:` | FLIP |
| ListView table, filters, bulk select | `src/components/ListView/ListView.tsx:65,166,186,202`; `:720` `placement="left"`; `Filters/CompactFilterTrigger.tsx:150` | FLIP + placement swap |
| Card view | `ListView/CardCollection.tsx:53-54`; `packages/superset-ui-core/src/components/ListViewCard/index.tsx` | FLIP |
| Pagination | antd Pagination (RTL-aware) via ListView/TableView | FLIP |
| Toasts | `src/components/MessageToasts/ToastPresenter.tsx:34-35` (`right:0; margin-right:50px`), `Toast.tsx:50,62` | FLIP (toasts move to bottom-left, accepted) |
| Modal (draggable/resizable) | re-resizable `enable.right` `Modal/Modal.tsx:219-236`; physical drag bounds `:366-376` | keep; P2 (centred box, physical math is self-consistent) |
| DropdownContainer (overflow -> "More") | `DropdownContainer.tsx:190-194` compares `child.right > container.right`; `:206-209` `remainingSpace = containerRight - buttonRight` | **FIX P0**: in RTL overflow is past the *left* edge, never detected |
| Chart context menu anchor | `src/components/Chart/ChartContextMenu/ChartContextMenu.tsx:471-481` uses `css={{ position:'fixed', left: clientX }}` | **FIX P0**: Emotion flips to `right: clientX`; use inline `style` |
| Interactive table header resize/reorder | `Table/utils/InteractiveTableUtils.ts:116-131` uses `event.offsetX` vs `offsetWidth`; `oldX` deltas | FIX P1 (zone on wrong edge, delta inverted) |
| VirtualTable scroll sync | `Table/VirtualTable.tsx:193-198` copies `scrollLeft` | verify (negative `scrollLeft` in RTL); P2 |
| DynamicEditableTitle | `DynamicEditableTitle/index.tsx:115` `scrollLeft = scrollWidth` | FIX P2 |
| Select | `Select/styles.tsx:30,58,109,134,150-170`; antd Select | FLIP |
| Directional icons | 11x `Icons.RightOutlined` used as expand chevrons (e.g. `src/components/DatabaseSelector/index.tsx:523,564`, `DrillBySubmenu.tsx:424`, `FoldersEditor/TreeItem.tsx:330`); `CaretRightFilled` `DatasourceEditor.tsx:2737`; `RollbackOutlined` `src/pages/ArchivedList/index.tsx:139`; Undo/Redo `src/dashboard/components/Header/index.tsx:714,736` | FIX P2 via `mirrorInRtl`; do NOT mirror Undo/Redo, play (`CaretRightOutlined` run query), align-left/right controls |
| Arrow glyphs in strings | `t('View All »')` `src/features/home/{ChartTable.tsx:209,DashboardTable.tsx:225,SavedQueries.tsx:293}`; `→` `src/utils/softDeleteCopy.ts:166,203` | FIX in translation (use `«` / `←`) |
| Dataset folders editor (dnd-kit tree) | depth projection from `delta.x` `src/components/Datasource/FoldersEditor/hooks/useDragHandlers.ts:223,262`; stack offsets `styles.tsx:146-147`; indentation `TreeItem.styles.ts:33,79,188` (Emotion, flips) | FIX P1: negate `delta.x` in RTL |
| Dataset layout sidebar | `src/features/datasets/DatasetLayout/index.tsx` uses `ResizableSidebar` | see 4.2 |
| Database modal, alerts/reports, RLS, CSS templates, annotations, themes, users/roles/groups, login, welcome | all React (`src/views/routePaths.ts:20-60`), antd forms + Emotion; popups pinned to body/modal (`DatabaseModal/index.tsx:1365`, `RoleFormItems.tsx:87`) | FLIP; isolate SQLAlchemy URI, host, JSON, cron expression, CSS/JSON editors |

### 4.2 Dashboard (group B)

| Surface | Mechanism / evidence | Verdict |
|---|---|---|
| Layout persistence | `position_json` holds child order + `meta.width` in grid columns, `meta.height` (`src/dashboard/util/newComponentFactory.ts:47-70`); no x/left/right pixel value stored. Sidebar widths in localStorage are scalar | direction-neutral; an LTR-authored dashboard simply mirrors (first child on the right). Product decision needed if authors want fixed visual order |
| Row/Column flow, gutters | flex row `gridComponents/Row/Row.tsx:89,96,137`; `Column/Column.tsx:90,114` | FLIP |
| Row/Column drop zones | index-based empty drop targets `Row.tsx:385-405,440-470`; `dnd/handleDrop.ts:71-104` ignores left/right | safe |
| **Tab reorder (react-dnd)** | `util/getDropPosition.ts:150-151,176-178,189-190` returns physical `DROP_LEFT/RIGHT`; `util/dnd-reorder.ts:75-84,114-117` maps LEFT=before, RIGHT=after; indicator `gridComponents/Tabs/Tabs.tsx:90,454-455` | **FIX P0**: tab lands on the wrong side and indicator shows opposite the pointer. Fix in one place: swap the two pointer-derived results in `getDropPosition` when RTL (lines 178, 189-190 only; 134 and 198 are logical append/prepend) |
| Tab reorder (dnd-kit) | `TabsRenderer/TabsRenderer.tsx:36-47,221` (`translate3d`, inline) | safe; keyboard sorting direction UNVERIFIED |
| Tab bar | antd Tabs; `tabBarStyle={{ paddingLeft }}` inline `TabsRenderer.tsx:377`, `DashboardBuilder/DashboardContainer.tsx:366`; ping gradients `TabsRenderer.tsx:141-151` | FIX P2 (`paddingInlineStart`) |
| **Grid resize handles** | re-resizable; edges `util/resizableConfig.ts:20-29` (`right`, `bottom`, `bottomRight`); classes `resizable/ResizableContainer.tsx:76-79`; handle CSS `:136-161`; width from `delta.width` `:272` | **FIX P1**: handle stays on the anchored (right) edge while the box grows leftward. Switch to `left`/`bottomLeft` in RTL in `resizableConfig.ts` + `HANDLE_CLASSES` + `ResizableHandle.tsx:20-32`; `delta.width` stays valid |
| Resize cursor label, column guides | inline physical `ResizableContainer.tsx:236-251`; `DashboardGrid.tsx:393-397` (symmetric grid) | safe |
| **Vertical filter bar width resize** | `src/components/ResizableSidebar/index.tsx:24-26` (absolute overlay), `:69-75` `enable={{ right }}`; mounted `DashboardBuilder.tsx:921-929` | **FIX P0**: handle sits at the viewport edge, not at the content boundary; use `left` in RTL |
| Filter bar position/collapse | `nativeFilters/FilterBar/Vertical.tsx:75-118` (flips); collapse icon inline `rotate(90deg)` `Vertical.tsx:329-332`, CSS `rotate(-90deg)` `FilterBar/Header/index.tsx:80-83`; `draggableStyle.marginLeft: -32` inline `DashboardBuilder.tsx:713-720` (used `:946`) | FLIP + FIX P1 (rotation sign, `marginInlineStart`) |
| Horizontal filter bar | `FilterBar/Horizontal.tsx:83-95`; overflow via `DropdownContainer` (`FilterControls/FilterControls.tsx`) | P0 through DropdownContainer |
| Filter cards / popovers | `FilterControlShared.tsx:261,286,306`, `GroupByFilterCard.tsx:192,540` `placement="right"`; `Tab.tsx:479` | FIX P2 (placement swap; rc-trigger auto-adjust hides most of it) |
| Mobile filters drawer | `DashboardBuilder.tsx:1094-1096` `placement="left"` | FIX P2 |
| Builder side pane | `BuilderComponentPane/index.tsx:43-58` sticky `right:0` + negative box-shadow (both flip) | FLIP (pane moves to the left) |
| Slice adder placeholder | `AddSliceCard/AddSliceCard.tsx:166` Emotion `left: ${placeholder.offsetLeft - 2}px` | FIX P1 (measured pixel in Emotion) |
| Drag preview | inline fixed + `translate(x,y)` `dnd/AddSliceDragPreview.tsx:44,69` | safe |
| Hover menus, drag handles | `menu/HoverMenu.tsx:44-61`, `WithPopoverMenu.tsx:73-93` | FLIP |
| Header + edit toolbar | `Header/index.tsx:177-213,957` | FLIP |
| Chart header, controls menu | `SliceHeader/index.tsx:356` `leftBottom`; `SliceHeaderControls/index.tsx:809` `bottomRight`; `FiltersBadge/DetailsPanel/index.tsx:210` | FIX P2 |
| Filter config modal | dnd-kit vertical lists; `FiltersConfigForm.tsx:156` `row-reverse`; borders flip | FLIP; check `row-reverse` visually |
| Scoping trees | legacy `react-checkbox-tree` + its own CSS (`filterscope/treeIcons.tsx:20`), `FilterScopeSelector.tsx:103-367`; new antd Tree `FiltersConfigForm/FilterScope/ScopingTree.tsx:67` | antd FLIP; react-checkbox-tree CSS not mirrored -> FIX P2 |
| Embedded / standalone / report | same providers `src/embedded/EmbeddedContextProviders.tsx:70-98`; `lang`/`dir` not set there | covered by preamble switch |

### 4.3 Explore + chart controls (group C)

| Surface | Mechanism / evidence | Verdict |
|---|---|---|
| **Three panels** | two re-resizable with `enable={{ right: true }}` `src/explore/components/ExploreViewContainer/index.tsx:1150-1161,1240-1250`; borders `:144,149` | **FIX P0** (same wrong-edge handle as sidebar) |
| Collapse icons | `rotate(-90deg)` / `rotate(90deg)` `ExploreViewContainer/index.tsx:1171-1174,1228-1231` | FIX P2 |
| Chart / data split | react-split `direction="vertical"` `ExploreChartPanel/index.tsx:555-558` | safe (split.js RTL bug only affects horizontal) |
| Control popover placement | physical ratio + physical placement `controls/ControlPopover/ControlPopover.tsx:44,107` | safe, self-adapting; exclude from placement swap |
| **Popover resize grip** | `ExploreContentPopover.tsx:22-28` (`float:right`, `scaleX(-1)`, `nwse-resize`); math `width + (clientX - startX)` `MetricControl/AdhocMetricEditPopover/index.tsx:174,310`, `FilterControl/AdhocFilterEditPopover/index.tsx:200,282`, `DndColumnSelectControl/useResizeButton.tsx:97` | FIX P1: grip flips to the left, delta must be negated, cursor -> `nesw-resize` |
| DnD metric/column/filter pills | dnd-kit sortable, vertical lists (`DndSelectLabel.tsx`, `OptionWrapper.tsx`, `OptionControls/index.tsx`) | FLIP; chevron `Option.tsx:99`, `OptionControls/index.tsx:397` need mirror |
| Datasource panel | react-window + dnd-kit `DatasourcePanel/*`; `DatasourcePanelItem.tsx` physical paddings | FLIP |
| Time range popover | antd pickers; `DateFilterLabel.tsx:391`, `CustomFrame.tsx:145-257` | FLIP; needs `ar` in `useLocale.ts` |
| Annotation layer popover | viewport math `AnnotationLayerControl/AnnotationLayer.tsx:1146-1161` | verify P2 |
| Viz gallery, save modal, properties | `VizTypeControl/VizTypeGallery.tsx` (10 physical decl.), `SaveModal.tsx` | FLIP |
| `superset-ui-chart-controls` | 24 physical occurrences; `SQLPopover.tsx`, `ColumnOption.tsx`, `MetricOption.tsx` | FLIP; SQL expression tooltips ISOLATE-LTR |

### 4.4 SQL Lab + LTR isolation (group D)

| Surface | Mechanism / evidence | Verdict |
|---|---|---|
| App layout | antd Splitter `src/SqlLab/components/AppLayout/index.tsx:105-145` | FLIP (left bar moves right, handled by antd) |
| Editor / results split | antd Splitter `layout="vertical"` `SqlEditor/index.tsx:966-967` | safe |
| **Editor** | **Ace** (react-ace) through provider abstraction `src/core/editors/AceEditorProvider.tsx:37-47` -> `AsyncAceEditor`; mounted `EditorWrapper/index.tsx:366-374`. Ace self-isolates (`direction: ltr`) | ISOLATE-LTR already; add `dir="ltr"` to `.ace_tooltip` / autocomplete (`AsyncAceEditor/index.tsx:285-286,470-471` flips `margin-left`) |
| **Schema tree** | react-arborist `TableExploreTree/index.tsx:498-504`; inline `paddingLeft` passed as `style` to `TreeNodeRenderer.tsx:160-161,180,218` | FIX P1: convert to `paddingInlineStart` in the renderer |
| Tab bar | antd Tabs `TabbedSqlEditors/index.tsx:60-90` | FLIP |
| Result grid | ag-grid via GridTable; pin menu `src/components/GridTable/HeaderMenu.tsx:198-212` ("Pin Left/Right") | `enableRtl` centrally; decide pin semantics |
| SQL previews | `HighlightedSql`, `ShowSQL`, `QueryTable`, `src/pages/QueryHistoryList`, `src/features/queries/SyntaxHighlighterCopy.tsx`, `explore/components/controls/ViewQuery.tsx` all use `CodeSyntaxHighlighter` | ISOLATE-LTR at `CodeSyntaxHighlighter/index.tsx:171,192` |
| Errors with SQL / stack traces | `src/components/ErrorMessage/{ErrorAlert,InvalidSQLErrorMessage,PreformattedErrorDescription,ErrorMessageWithStackTrace}.tsx` | prose RTL, `<pre>/<code>` ISOLATE-LTR |
| Identifiers | `ColumnElement/index.tsx:40,94`, `TablePreview/index.tsx`, `src/components/TableSelector`, `DatabaseSelector` | wrap names in `<bdi>` / `dir="auto"` |
| JSON viewers | react-json-tree `src/components/JsonModal/index.tsx:21`, `MarshmallowErrorMessage.tsx`; `plugins/plugin-chart-ag-grid-table/src/renderers/JsonCellRenderer.tsx` | ISOLATE-LTR |
| URLs / copy | `src/components/CopyToClipboard/index.tsx:137`, embed code `EmbedCodeContent.tsx` | ISOLATE-LTR |

## 5. Charts: mechanisms (group E)

| Item | Evidence | Verdict |
|---|---|---|
| ECharts renderer | Canvas (`Echart.tsx:55`, `init(divRef.current, null, {locale,...})` `:215-216`); host `:475-477` | ISOLATE-LTR: an inherited `direction: rtl` on a canvas changes bidi resolution of neutral characters (`-5`, `10%`, `(1,2)`) |
| Tooltip | HTML string, `appendToBody: true` `plugins/plugin-chart-echarts/src/utils/tooltip.ts:36-37`, class `echarts-tooltip` `:40`, viewport-clamped position fn `:47-157` (physical, correct) | tooltip inherits page RTL (good); FIX inline styles in builder |
| Tooltip HTML builder | `packages/superset-ui-core/src/utils/tooltip.ts:103,106` (`margin-right`, `margin:0 5px 0 1px`), `:130-131` (`text-align: right/left`, `padding-left`) - inline strings, never flipped; used by 18 `transformProps.ts` | FIX P1: `text-align: end/start`, `padding-inline-start`, `margin-inline-end`; wrap numeric cells `dir="ltr"` |
| Legend | canvas; `utils/series.ts:1000-1075` maps user-chosen orientation to physical `left/right`; grid padding `:1116-1117` | keep physical (explicit user choice) |
| Axis/label alignment | physical `align`/`position` in 11 `transformProps.ts` (Butterfly x4, MixedTimeseries x3, ...) | keep; no mirroring by default |
| Extra controls outside canvas | `plugins/plugin-chart-echarts/src/components/ExtraControls.tsx` (antd radio) | must sit outside the isolated node or get `dir` reset to page direction |
| Locale | `Echart.tsx:190-192` uppercases `common.locale` -> `AR` bundle present | works |

### Per-family policy

| Family (viz types) | Tech | Policy | Notes / evidence |
|---|---|---|---|
| ECharts: timeseries (line/bar/area/scatter/step/smooth), mixed, pie, rose, funnel, gauge, radar, treemap, sunburst, sankey, graph, tree, heatmap, histogram, boxplot, bubble, waterfall, gantt, candlestick, butterfly, bullet, time pivot | canvas | **ISOLATE-LTR plot**, tooltip RTL | default of the central switch |
| Big Number (total, trendline, PoP) | HTML text + ECharts trendline | **inherit RTL** for chrome; numeric value in `<bdi dir="ltr">`; trendline host isolated by Echart switch | `BigNumber/BigNumberViz.tsx:520-530`, `BigNumberPeriodOverPeriod/PopKPI.tsx:75,85` |
| Table (`plugin-chart-table`) | HTML + react-table | **inherit RTL** | inline `textAlign` `'right'/'left'` `TableChart.tsx:640-645` -> `'end'/'start'` (FIX P1); cell bars `:1313-1320` Emotion `left:%` mirror consistently (FLIP); `Styles.tsx:46,118,143,161` flip; header scroll sync `DataTable/hooks/useSticky.tsx:386-391` same-direction copy, OK |
| AG Grid table | ag-grid | **inherit RTL + `enableRtl`** | `pinned: 'left'` `utils/useColDefs.ts:569` (FIX); custom pager icons `AgGridTable/components/Pagination.tsx:110-132` need mirror; bar `renderers/NumericCellRenderer.tsx:58`; gradient `styles/index.tsx:86`; popover physical inline `components/CustomPopover.tsx:55-94` (OK) |
| Pivot table v2 | HTML | **inherit RTL** | `react-pivottable/Styles.ts:31,75,85,140,148,161` flip; numbers need `dir="ltr"` per cell |
| Time-series table | HTML + visx sparkline | inherit RTL; sparkline SVG `dir="ltr"` | `src/visualizations/TimeTable/components/SparklineCell/SparklineCell.tsx:127` |
| Handlebars | user HTML | inherit RTL (author controls `dir`) | `plugins/plugin-chart-handlebars/src` |
| d3/SVG: calendar, chord, country map, world map, partition, parallel coordinates, horizon, word cloud, paired t-test | SVG/canvas, `text-anchor` | **ISOLATE-LTR** | `plugin-chart-calendar/src/vendor/cal-heatmap.ts:1166,1247`; `parallel-coordinates/src/vendor/parcoords/d3.parcoords.ts:272,764`; `word-cloud/src/chart/WordCloud.tsx:335`; under `direction: rtl` SVG `text-anchor: start` anchors at the right |
| deck.gl, point cluster map, cartodiagram | WebGL/canvas + HTML overlays | **ISOLATE-LTR map**, legend/tooltip HTML RTL | tooltip `preset-chart-deckgl/src/components/Tooltip.tsx:41-44` Emotion `left: ${left}px` (FIX P0-class, measured pixel); legend `components/Legend.tsx:43-60` |

## 6. Prioritised defect prediction (owner groups have disjoint directories)

### (A) `src/features/home`, `src/components`, `src/pages`, `src/views`, `packages/superset-ui-core`, `packages/superset-core`
| P | Defect | File(s) | Fix pattern |
|---|---|---|---|
| P0 | Overflow detection dead -> horizontal filter bar items unreachable | `packages/superset-ui-core/src/components/DropdownContainer/DropdownContainer.tsx:190-209` | compare inline-end edge: RTL `child.left < container.left - 1`; `remaining = buttonLeft - containerLeft` |
| P0 | Chart context menu (drill, cross-filter) opens at mirrored X | `src/components/Chart/ChartContextMenu/ChartContextMenu.tsx:471-481` | `style={{ left: clientX }}` instead of `css` |
| P0 | Sidebar resize handle on outer edge (dashboard filter bar, dataset layout) | `src/components/ResizableSidebar/index.tsx:69-75` | `enable={{ [isRtl ? 'left' : 'right']: enable }}` + `handleClasses` |
| P1 | Tooltip HTML alignment wrong in every ECharts tooltip | `packages/superset-ui-core/src/utils/tooltip.ts:103-131` | logical inline properties |
| P1 | Column resize/reorder zones on wrong edge | `packages/superset-ui-core/src/components/Table/utils/InteractiveTableUtils.ts:116-150` | mirror `offsetX` test and delta sign |
| P1 | Folder tree nesting drag inverted | `src/components/Datasource/FoldersEditor/hooks/useDragHandlers.ts:223` | `delta.x * (isRtl ? -1 : 1)` |
| P1 | No Arabic antd/dayjs locale (pickers, relative dates in English) | `src/hooks/useLocale.ts:23-60`; `Theme.tsx:306` | add `ar: () => import('antd/locale/ar_EG')`, `import 'dayjs/locale/ar'` |
| P2 | 65 explicit physical placements | wrappers in `packages/superset-ui-core/src/components/{Tooltip,Popover,Dropdown,Drawer}` | central swap (exclude ControlPopover) |
| P2 | Chevrons/back icons not mirrored; `»`/`→` glyphs | `Icons/BaseIcon.tsx`; `src/features/home/*Table.tsx`; `src/utils/softDeleteCopy.ts:166,203` | `mirrorInRtl`; translation strings |
| P2 | Title input scroll-to-end | `DynamicEditableTitle/index.tsx:115` | direction-aware `scrollLeft` |

### (B) `src/dashboard`
| P | Defect | File(s) | Fix pattern |
|---|---|---|---|
| P0 | Tab drag-reorder drops on the wrong side | `util/getDropPosition.ts:176-178,189-190`; `util/dnd-reorder.ts:75-117`; `gridComponents/Tabs/Tabs.tsx:90,454-455` | swap pointer-derived LEFT/RIGHT in `getDropPosition` when RTL |
| P1 | Grid component resize handle on anchored edge | `util/resizableConfig.ts:20-51`; `components/resizable/ResizableContainer.tsx:76-79,136-161,331-336`; `ResizableHandle.tsx:20-32` | RTL config with `left`/`bottomLeft` |
| P1 | Slice adder placeholder mirrored | `components/AddSliceCard/AddSliceCard.tsx:166` | inline `style` |
| P1 | Collapsed filter bar offset / collapse arrows | `DashboardBuilder/DashboardBuilder.tsx:713-720`; `nativeFilters/FilterBar/Vertical.tsx:329-332`; `FilterBar/Header/index.tsx:80-83` | `marginInlineStart`; rotation sign by direction |
| P2 | Tab bar inline padding, popup placements, mobile drawer, react-checkbox-tree CSS | `TabsRenderer.tsx:377`; `DashboardContainer.tsx:366`; `DashboardBuilder.tsx:1096`; `filterscope/*` | logical inline props; placement swap |

### (C) `src/explore`, `packages/superset-ui-chart-controls`
| P | Defect | File(s) | Fix pattern |
|---|---|---|---|
| P0 | Datasource/controls panel resize handles on wrong edge | `components/ExploreViewContainer/index.tsx:1161,1250` | `left` handle in RTL |
| P1 | Ad-hoc metric/filter popover resize inverted | `components/ExploreContentPopover.tsx:22-28`; `controls/MetricControl/AdhocMetricEditPopover/index.tsx:174`; `controls/FilterControl/AdhocFilterEditPopover/index.tsx:200`; `controls/DndColumnSelectControl/useResizeButton.tsx:97` | negate dx, swap cursor, drop `scaleX(-1)` |
| P2 | Collapse arrows, option chevrons, 14 inline physical styles | `ExploreViewContainer/index.tsx:1171-1231`; `controls/DndColumnSelectControl/Option.tsx:99` | rotation sign; `mirrorInRtl`; logical props |

### (D) `src/SqlLab`, `src/core/editors`, code components
| P | Defect | File(s) | Fix pattern |
|---|---|---|---|
| P1 | Schema tree shows no hierarchy (indent on wrong side) | `SqlLab/components/TableExploreTree/TreeNodeRenderer.tsx:160-161,180,218` | map `style.paddingLeft` -> `paddingInlineStart` |
| P1 | SQL/JSON/stack traces reordered and right-aligned | `CodeSyntaxHighlighter/index.tsx:171,192`; `src/components/JsonModal/index.tsx`; `src/components/ErrorMessage/*` | `dir="ltr"` attribute |
| P1 | Result grid stays LTR while surrounding CSS is mirrored | `ThemedAgGridReact/index.tsx:202` (owner A exposes prop, D verifies) | `enableRtl` |
| P2 | Ace tooltip/autocomplete inherit RTL | `AsyncAceEditor/index.tsx:285-286,470-471` | `dir="ltr"` on popups |
| P2 | Identifiers mixed into Arabic sentences | `ColumnElement`, `TablePreview`, `TableSelector`, `DatabaseSelector` | `<bdi>` |

### (E) `plugins/*`
| P | Defect | File(s) | Fix pattern |
|---|---|---|---|
| P0 | Canvas/SVG text corrupted without isolation (minus/percent position, `text-anchor`) | all canvas/SVG families | central `dir` on `SuperChartCore.tsx:318` + `Echart.tsx:475` |
| P0 | deck.gl tooltip mirrored | `preset-chart-deckgl/src/components/Tooltip.tsx:41-44` | inline `style` |
| P1 | Table text columns stay left-aligned | `plugin-chart-table/src/TableChart.tsx:640-645` | `'start'/'end'` |
| P1 | AG Grid table: selection column pinned left, pager icons | `plugin-chart-ag-grid-table/src/utils/useColDefs.ts:569`; `AgGridTable/components/Pagination.tsx:110-132` | `pinned: isRtl ? 'right' : 'left'`; mirror icons |
| P1 | Negative numbers / percentages in HTML charts show sign on the wrong side | BigNumber, table, pivot, time table cells | `<bdi dir="ltr">` or `dir="ltr"` on numeric cells |
| P2 | Gradients and bars with fixed direction | `plugin-chart-ag-grid-table/src/styles/index.tsx:86`; `renderers/NumericCellRenderer.tsx:58` | direction-aware gradient |

## 7. Reports, thumbnails, PDF

Playwright context is created without `locale` (`superset/utils/webdriver.py:969-976`); the session is created by `login_user` (`superset/utils/machine_auth.py:104`), so no `session["locale"]`; bootstrap locale comes from `get_locale()` (`superset/views/base.py:698-699`), i.e. `BABEL_DEFAULT_LOCALE` (`superset/config.py:586`, default `"en"`). Result: screenshots render LTR English unless the global default is `ar`, independent of owner/recipient. To localise reports either set `BABEL_DEFAULT_LOCALE = "ar"` or seed the locale in the machine-auth session. Client PDF/image export (`src/utils/downloadAsImage.tsx`, dom-to-image-more + jspdf) clones the live DOM, so it inherits `dir`; visual check required.

## 8. 25 screens/states for the automated RTL visual audit (base `http://localhost:8088`, locale `ar`)

| # | Screen / state | URL or steps |
|---|---|---|
| 1 | Login | `/login/` |
| 2 | Welcome cards + top nav | `/welcome/` |
| 3 | Settings menu + language picker open | click right-menu dropdown |
| 4 | Dashboard list, table view, filters open | `/dashboard/list/` |
| 5 | Chart list, card view + bulk select + pagination | `/chart/list/` -> card toggle -> "Bulk select" |
| 6 | Dataset list + a toast | `/tablemodelview/list/`, trigger a delete/duplicate toast |
| 7 | Dashboard view, vertical filter bar open | `/dashboard/<id>/` |
| 8 | Same, filter bar collapsed, then width-resized | collapse button; drag handle |
| 9 | Dashboard horizontal filter bar with overflow | set orientation horizontal, narrow viewport to 1024px |
| 10 | Dashboard edit mode: builder pane, hover menus, resize handle on a chart | `?edit=true` |
| 11 | Edit mode: dragging a tab between two tabs (indicator visible) | drag tab, capture mid-drag |
| 12 | Chart header menu + cross-filter badge + context menu | click `⋮`; right-click a bar |
| 13 | Filter config modal incl. scoping tree | filter bar gear -> "Add or edit filters" |
| 14 | Dashboard standalone/report mode and embedded | `/dashboard/<id>/?standalone=3`; `/embedded/<uuid>` |
| 15 | Explore, three panels, a timeseries bar chart with tooltip | `/explore/?slice_id=<id>` + hover |
| 16 | Explore, ad-hoc metric popover (Custom SQL tab) and time range popover | click a metric pill; click time range |
| 17 | Explore, table chart with cell bars + search + pagination | table chart slice |
| 18 | Explore, pivot table and big number with trendline (negative value) | two slices |
| 19 | Explore, pie with legend left/right and a deck.gl or map chart | two slices |
| 20 | Explore data pane (results/samples grid) and save modal | expand bottom pane; "Save" |
| 21 | SQL Lab: schema tree expanded, editor with autocomplete open, results grid | `/sqllab/` |
| 22 | SQL Lab: query history with SQL preview, error state with SQL | history tab; run invalid SQL |
| 23 | Database connection modal (SQLAlchemy URI step) | `/databaseview/list/` -> "+ Database" |
| 24 | Dataset editor (columns, metrics, folders tab) and alerts/reports modal | dataset "Edit"; `/alert/list/` -> "+ Alert" |
| 25 | Users / roles / RLS / themes / CSS templates lists and 404 page | `/users/`, `/roles/`, `/rowlevelsecurity/list`, `/theme/list/`, `/csstemplatemodelview/list/`, `/nonexistent` |

Each capture should be taken in both `en` and `ar` and diffed for: horizontal scrollbars on `<body>`, elements with `getBoundingClientRect().left < 0`, popups outside the viewport.

## 9. Not verified

- Nothing was executed in a browser; every defect is a prediction from source.
- Whether `/* @noflip */` survives Emotion's serializer into `stylis-plugin-rtl`.
- FAB's `get_locale()` fallback order (flask_appbuilder not installed locally).
- Negative `scrollLeft` handling in `VirtualTable.tsx` and antd virtual Table.
- dnd-kit keyboard sorting direction and react-window horizontal lists in RTL.
- Third-party CSS (react-checkbox-tree, react-js-cron, geostyler) is not processed by Emotion and will stay LTR.
- CSS templates and dashboard custom CSS written by users are injected outside Emotion and will not be mirrored.

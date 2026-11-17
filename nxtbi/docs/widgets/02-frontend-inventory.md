# 02 - Frontend inventory and completeness (apache/superset PR #44471)

Read-only inspection. Evidence = `path:line`. Checkouts: **PR** = `E:/Work_Lab/nxtbi-superset-pr44471` @ 71be990689; **FORK** = `E:/Work_Lab/nxtbi-superset` at ref `master` (f3f3d10d5c) unless "RTL-WT" (uncommitted working tree of `feature/nxtbi-arabic-rtl`, read only).
Path prefixes (all PR unless marked): `W/` = `superset-frontend/packages/superset-widgets/`, `C/` = `superset-frontend/packages/superset-core/src/`, `D/` = `superset-frontend/src/core/dashboard/`, `B/` = `superset-frontend/src/pages/DashboardBuilderV2/`, `F/` = `superset-frontend/`.
Nothing was built or run: every behavioural statement is derived from reading code; anything depending on runtime is tagged UNVERIFIED.

## 1. Package `@apache-superset/widgets` (W/, 72 files)

| Item | Fact | Evidence |
|---|---|---|
| Manifest | name `@apache-superset/widgets` 0.1.0, `main: lib/index.js`, `types: lib/index.d.ts`, **no `exports` map**, no `dependencies`/`devDependencies` | W/package.json:2-9 |
| Peer deps | `@apache-superset/core *`, `@emotion/react ^11.4.1`, `@superset-ui/core *`, `antd ^6.5.1`, `echarts ^6.1.0`, `react`/`react-dom ^18.3.0`. Not declared although imported transitively: ag-grid, `@emotion/styled`, `@emotion/cache` | W/package.json:17-25 |
| Build | `tsc --build` only, no bundler. tsconfig uses `baseUrl: "../.."` (removed on master, see section 9). README: "Status: POC, not published" (PR claims) | W/package.json:12-16, W/tsconfig.json:3-7, W/README.md:25 |
| In-repo consumption | root dep `file:packages/superset-widgets`; webpack auto-aliases every `@apache-superset/*` dep to `<pkg>/src` so deep imports (`@apache-superset/widgets/bus`) resolve to source; jest + tsconfig path maps added | F/package.json:103, F/webpack.config.js:651-662, F/jest.config.js:42-44, F/tsconfig.json:60-61,81 |
| Public API | `SupersetProvider`, `Widget`, `Chart`, `MetricTile`, `Table`, `FilterSelect`, `Markdown`, hooks `useSupersetFilter`/`useWidgetEvent`/`useWidgetValue`/`hostFilterPayload`, `createGuestTokenSource`, `createApiFetch`/`createHttpWidgetClient`, extension loader/host, `createSession` (non-React mount), bus/data-client contexts, registry, `resolveBindings`, plus MCP/Claude-artifact client (`mcp/*`, `SupersetArtifactProvider`, out of scope) | W/src/index.ts:21-148 |
| Tests (jest) | 12 files: bus, dataClient, httpClient, session, Widget, ChartWidget, extensionHost, extensionLoader, echartsStructured{Series,Chrome}, SupersetArtifactProvider, mcp/client. None for Table/Metric/FilterSelect/Markdown widgets, SupersetProvider, guestToken, hooks | `W/src/**/*.test.*` |
| Dependence on Superset packages | `@apache-superset/core` (contract types, `VALUE_CHANGED_EVENT`, theme `Theme/useTheme/styled`, `translation.t`), `@superset-ui/core` (`SupersetClient`, `buildQueryContext`, components `Flex/Loading/Typography/Select/SafeMarkdown/ThemedAgGridReact/Icons`). **No chart plugins, no SuperChart, no Redux**: ECharts is driven directly | W/src/widgets/ChartWidget.tsx:20-72,84-124 |

### 1.1 SupersetProvider (W/src/embed/SupersetProvider.tsx)

| Aspect | Code does | Line |
|---|---|---|
| Props | `supersetDomain?`, `client?`, `bus?`, `fetchGuestToken?`, `guestTokenHeaderName?`, `guestTokenFetchTimeoutMs?`, `extensionWidgets?: boolean \| loader` (default true), `themeMode?: 'default'\|'dark'\|'system'`, `themeConfig?: AnyThemeConfig`, `children`. **No `direction`, `locale`, `getPopupContainer` props** | 39-65 |
| Contexts created | `WidgetBusContext` (own `createWidgetBus()` unless `bus` given), `WidgetDataClientContext` (given client or `createHttpWidgetClient`), `ExtensionWidgetLoaderContext`. No cache context, no i18n setup (`t()` runs unconfigured), no `SupersetClient.configure` | 117-154, 167-176 |
| Auth | guest token source memoised per provider, shared by data client and extension loader; without `fetchGuestToken` the browser session cookie is used (`credentials: 'include'`) | 121-144; W/src/embed/httpClient.ts:72-80 |
| Theme mount | `Theme.fromConfig({...themeConfig, algorithm: dark ? DARK : DEFAULT})` in `useMemo([themeConfig, dark])`; then `const { SupersetThemeProvider } = theme; <SupersetThemeProvider withGlobalStyles={false}>`. Only prop passed is `withGlobalStyles`. | 156-168 |
| AG Grid | `setupAGGridModules()` once via module flag `agGridReady` | 89, 108-111 |
| Defect (remount) | every new `Theme` instance has a freshly bound `SupersetThemeProvider` (C/theme/Theme.tsx:54) = new component type, so a dark-mode toggle or a non-memoised `themeConfig` object **unmounts and remounts the whole widget subtree** (refetch; and `Widget` cleanup clears filter values, see 6.2-S7) | 157-165 |

### 1.2 Widgets, hooks, clients

| Component (type id) | What it does | Data call | Evidence |
|---|---|---|---|
| `ChartWidget` (`echarts`) | raw ECharts canvas (`echarts.init`, `setOption(option, true)`, ResizeObserver sizing); option = `resolveBindings($bind markers)` then structured series/chrome; title stripped (drawn by host header); opt-in `crossFilter` on first dimension only, click toggles `EQUALS` filter | `client.fetchData` keyed by `JSON.stringify({dataBinding, activeFilters, savedId})` | W/src/widgets/ChartWidget.tsx:204-254, 298, 307-343, 345-372, 381-413 |
| `AgGridTableWidget` (`ag-grid-table`) | `ThemedAgGridReact rowData/columnDefs`, columns derived from result unless `props.columnDefs`; no paging/sort config, no server pagination | same pattern | W/src/widgets/AgGridTableWidget.tsx:58-152 |
| `MetricTileWidget` (`metric-tile`) | first column of first row, `Intl.NumberFormat`, prefix/suffix/label/static `delta` prop | same pattern | W/src/widgets/MetricTileWidget.tsx:103-205 |
| `FilterSelectWidget` (`filter.select`) | multi `Select`; emits `{selection, resolved, targets?}`; default selection applied once; deferred apply inside a `filter.bar`; popup forced to `document.body` | `client.fetchValues` | W/src/widgets/FilterSelectWidget.tsx:36-75, 120-124, 137-175, 207 |
| `MarkdownWidget` (`markdown`) | `SafeMarkdown source={props.content}` | none | W/src/widgets/MarkdownWidget.tsx:23-29 |
| Others (builder only, not embeddable) | containers `tabs`, `collapsible`, `carousel`, `filter.bar` live in `D/widgets/*`, registered in `D/registerBuiltInWidgets.ts:98-155`; they are absent from `builtInWidgetComponents` | - | W/src/registry.ts:27-35 |
| `Widget` | inline (`type`+`props`) or saved (`id` -> `client.getSavedWidget`), error boundary, optional title, falls back to extension loader for unknown types; bus id = `instanceId ?? 'widget'+useId()` | - | W/src/embed/Widget.tsx:120-223 |
| Typed wrappers | `ChartProps/MetricTileProps/TableProps/FilterSelectProps/MarkdownProps` are hand-written TS interfaces (no runtime schema) | - | W/src/embed/Widget.tsx:243-301 |

| Client | Endpoints | Evidence |
|---|---|---|
| `createHttpWidgetClient` (embed) | `POST /api/v1/widget/data` body `{id}` or `{widget:{type,props}}` + `filters[{column,operator,value}]`; `POST /api/v1/widget/values`; `GET /api/v1/widget/<uuid>`; header `X-GuestToken`; caller `init.headers` are discarded | W/src/embed/httpClient.ts:56-59, 61-96, 103-136 |
| `sessionDataClient` (builder) | `POST /api/v1/chart/data` via `buildQueryContext` (browser builds the query); `GET /api/v1/datasource/table/<id>/column/<col>/values/`; `GET /api/v1/widget/<id>` | W/src/dataClient.ts:57-92, W/src/chartData.ts:58-103 |
| Extension loader | `GET /api/v1/extensions/<publisher>/<name>` then `<script src=remoteEntry>` | W/src/embed/extensionLoader.ts:136-179 |
| Builder-only | `GET/POST/PUT /api/v1/dashboard_v2/`, `GET /api/v1/widgets/types`, `POST /api/v1/widgets/type/<t>/control-schema`, `POST .../validate`, `POST/PUT /api/v1/widget/`, `GET /api/v1/dataset/<id>`, `GET /api/v1/theme/` | D/persistence.ts:42,64,68; B/schemaControlledWidgets.ts:49; B/SchemaControlPanel.tsx:99; B/controlValueValidation.ts:84; D/EmbedWidgetModal.tsx:64,68; D/datasetMetadata.ts:91; B/DashboardProperties.tsx:285 |

Saved vs inline schema (all in C/widgets/index.ts): `InlineWidgetRef {type, props}` :114-117, `SavedWidgetRef extends Inline {id}` :120-122, `SavedWidget {uuid, widget_type, title, props, dataset_id, changed_on}` :127-134, `WidgetDataClient` :142-154, `WidgetProps {instanceId, props, savedId?}` :157-165, `ResolvedFilter` :95-101, `HostFilter` :104-111, `FilterOperator` :87-88. `DataBindingSpec {datasetId, metrics, dimensions?, filters?, rowLimit?}` is C/dashboard/index.ts:292-299.

### 1.3 Event bus, cross-filter, host filters

- Bus contract `WidgetBus` (C/widgets/index.ts:67-78): `emit/on/getValue/getSourceIds/getScopeTargets/subscribe/getRevision`. Embed implementation `createWidgetBus()` W/src/bus.ts:25-74 (last value per `[sourceId,eventType]`, never pruned, `getScopeTargets` always `undefined`). Builder implementation is the `DashboardProvider` singleton itself (D/DashboardProvider.ts:121, 505-553).
- One vocabulary: any source emitting `VALUE_CHANGED_EVENT='valueChanged'` (C/dashboard/index.ts:255) with `FilterValueChangedPayload {selection, resolved, targets?}` (W/src/filterVocabulary.ts:66-72) is a filter. Consumers do not subscribe per source; they re-render on every bus tick (`useWidgetBusRevision`, W/src/bus.ts:89-90) and recompute `getActiveResolvedFilters(bus, datasetId, consumerId)` (W/src/activeFilters.ts:77-100): a source applies when `targets` names the consumer, else when `resolved.datasource === datasetId`; self excluded. Cross-dataset filtering by column name is not supported.
- Host-controlled filters: `useSupersetFilter(key)` emits under `host:<key>` and clears on unmount (W/src/embed/hooks.ts:51-79); `createSession().setFilter` does the same imperatively (session.tsx:213-218). `useWidgetEvent`, `useWidgetValue` hooks.ts:82-105.
- Theming hooks: only `useTheme()` from `@apache-superset/core/theme` (Chart, Metric) and `$bind {source:'theme', token}` (W/src/resolveBindings.ts:99-104). No widget-level theme override API.

## 2. `@apache-superset/core` additions (C/)

| File | Content | Evidence |
|---|---|---|
| `widgets/index.ts` (new, 171 lines) | **types and two constants only** (`DASHBOARD_WIDGETS_LOCATION='dashboard.widgets'` :52, `HOST_SOURCE_PREFIX='host:'` :59). All implementations live in `superset-widgets` | C/widgets/index.ts |
| `dashboard/index.ts` (new, 318 lines) | `declare function` API (`getRoot/getNode/addWidget/removeWidget/moveWidget/updateLayout/updateProps/emit/getValue/on/fetchQueryData/getDashboardId`), `LayoutProps`, `DashboardNode`, `WidgetSpec`; only runtime export is `VALUE_CHANGED_EVENT` | C/dashboard/index.ts:67-125, 135-316 |
| `package.json` exports | adds `./dashboard`, `./widgets` | diff of `F/packages/superset-core/package.json` |
| `theme/Theme.tsx` | `SupersetThemeProvider({children, withGlobalStyles = true})`, `{withGlobalStyles && <GlobalStyles />}` | C/theme/Theme.tsx:205-212, 231 |
| `views/index.ts` | `registerView(view, location, component: ComponentType<any>)`; host `resolveView(id, props)` passes `{nodeId}` | C/views/index.ts (diff); F/src/core/views/index.ts (diff) |
| `navigation`, `chat` | `Page` gains `'dashboard_v2'`; `chat/index.ts` +181 (client tools, AI, out of scope) | - |

Extension contribution point: an extension calls `views.registerView({id:'extensions.<publisher>.<name>.<type>'}, 'dashboard.widgets', Component)`; the component receives `{nodeId}` and talks to `dashboard.*`. In Superset the builder resolves it through `resolveWidgetView` (D/resolveWidgetView.ts:58-64) and lists every registered view in the palette (B/Palette.tsx:71-80). Outside Superset the embed host swaps in a shim core (`createExtensionCore`, W/src/embed/extensionHost.tsx:321-352) whose `views.registerView` adapts the view to a `WidgetComponent` (:229-266, 270-293). Python side: `superset-core/src/superset_core/widgets/{base,decorators,composites,enrichment}.py` (`Widget` base class, `@widget` decorator; host injection at `superset/core/api/core_api_injection.py:286-359`). Extension CLI template now emits `publicPath: "auto"`.

## 3. `src/core` (58 files) and Dashboard V2 page

| Area | Files | What it is |
|---|---|---|
| `src/core/dashboard` | 40 | the **builder runtime inside Superset**: node-tree store + bus (`DashboardProvider.ts`), persistence, GridStack canvas (`RootGrid.tsx`, `useGridStack.ts`), read-only grid (`StaticGrid.tsx`), packing math (`gridPacking.ts`, `layoutStyle.ts`), widget chrome (`WidgetView.tsx`), container widgets, built-in registration, `EmbedWidgetModal` |
| `src/core/clientTools` | 11 | AI chat client tools (out of scope); wired unconditionally in `F/src/extensions/ExtensionsStartup.tsx` (`chat.registerClientTools(getCoreClientTools(chat))`) |
| `src/core/chat` | 3 | chat provider changes (out of scope) |
| `src/core/{index,views,navigation}` | 4 | export `dashboard` namespace, `resolveView(id, props)`, page mapping |

| Topic | Fact | Evidence |
|---|---|---|
| Routes | `/dashboard/v2/new/` and `/dashboard/v2/:dashboardId/` -> lazy `src/pages/DashboardBuilderV2`; Flask shell `DashboardBuilderV2View` (`/new/`, `/<int:pk>/`); "+ Dashboard v2" in RightMenu | F/src/views/routes.tsx:83-88, 217-218; F/src/views/routePaths.ts:30-31; superset/views/dashboard/views.py:136-157; F/src/features/home/RightMenu.tsx:255 |
| Defect | `navigation` maps only `DASHBOARD_V2_NEW`; `/dashboard/v2/5/` falls through to `'/dashboard/:idOrSlug/'` (non-exact match) and reports page `'dashboard'`; `getDashboardId()` then returns stale legacy Redux `dashboardInfo.id` | F/src/core/navigation/index.ts:43-44, 60; D/index.ts:59-62 |
| Layout engine | **gridstack ^13.0.2** (new dependency), `float: true`, 24 columns, 4 corner handles, drag cancel selector by data attributes; child rects computed by own `packChildLayout` and pushed with `grid.update`; nested containers use a flow layout with pixel `rowSpan` | D/useGridStack.ts:165-209, 264-288; D/layoutStyle.ts:27; D/widgets/flowContent.tsx:135-250 |
| State management | no Redux/zustand: module singleton `provider = DashboardProvider.getInstance()` + `useSyncExternalStore(revision)`; `revision` also ticks on selection and on every bus emit | D/store.ts:37-50; D/DashboardProvider.ts:184-205, 537-548 |
| Editing | Palette (click or HTML5 drag, MIME `application/x-dashboard-widget`), Outline tree, Data panel, Inspector (schema-driven JSONForms from server control schema, raw JSON editor, generic inferred form), Dashboard properties (title, CSS, theme, tags stored in `root.props`) | B/EditorPanel.tsx, B/Palette.tsx, B/Outline.tsx, B/Inspector.tsx:411-512, B/SchemaControlPanel.tsx:98-99, B/DashboardProperties.tsx:159-217 |
| Save | manual button only: `saveDashboardV2({id, title, nodes: provider.getDocument()})` -> POST (new) or PUT (existing) of the **whole document** | B/DashboardHeader.tsx:242-262; D/persistence.ts:48-72 |
| Load | `fetchDashboardV2(dashboardId)` -> `provider.loadDocument(result.document.nodes)`; `dashboard_title`, `changed_on`, `embedded` are ignored | B/index.tsx:187-201; D/persistence.ts:38-45 |
| Autosave / undo / history / dirty guard | **none**. Undo, Redo, History, Templates, Favorite are `<Inert>` disabled placeholders; Published label hardcoded `false`; metadata hardcoded "Not saved yet"; no `beforeunload` | B/DashboardHeader.tsx:72-99, 270, 277, 283, 294-299, 318; B/InertControl.tsx:59 |
| View mode | `DashboardViewModeContext` (default `'edit'`) and `DashboardStoreContext` have **no Provider anywhere**; `StaticGrid` is unreachable; there is no read-only V2 dashboard page and no list page for V2 dashboards | D/viewMode.ts:27-28; D/store.ts:39-45; D/WidgetView.tsx:286-293 |
| Widget menu | only "Embed widget" works; 10 other items are disabled placeholders | D/WidgetView.tsx:51-68, 514-524 |
| Webpack / module federation | **no change** to `webpack.config.js`, `src/embedded/*`, `src/views/App.tsx`; MF shared scope still `react, react-dom, antd, @apache-superset/core` (widgets package is not shared) | F/webpack.config.js:170-193 |
| Embedding entry points | (a) dashboard-level: header "Embed" opens the **legacy** `DashboardEmbedModal` (`/api/v1/dashboard/<id>/embedded`), but the legacy `/embedded/<uuid>` page is untouched and nothing in the frontend calls backend `GET /api/v1/dashboard_v2/embedded/<uuid>` (superset/dashboard_v2/api.py:216) -> V2 dashboard embedding is not wired. (b) widget-level: `EmbedWidgetModal` saves the node as a saved widget and prints `<Widget id>` / inline snippets with guest-token payload hints | B/DashboardHeader.tsx:330-336; D/EmbedWidgetModal.tsx:58-89 |

## 4. Standalone React example (W/example, Vite 6, own lockfile)

- Location/build: `W/example/{package.json,vite.config.ts,server.mjs,src/*}`; scripts `dev` (vite, port 5173 strict), `build` (`tsc --noEmit && vite build`), `broker` (`node server.mjs`). Declares only vite/react-plugin/svgr/typescript; **react, antd, emotion, echarts resolve from `superset-frontend/node_modules`**, and `@apache-superset/widgets|core`, `@superset-ui/core` are aliased to monorepo source (W/example/vite.config.ts:50-74). It is not a consumer of a built package.
- Auth: default `EMBED_AUTH=session` = browser Superset cookie, needs `ENABLE_CORS` with `supports_credentials` and same-site origins; `EMBED_AUTH=guest` = `fetchGuestToken` -> Vite proxy `/api/guest-token` -> `server.mjs`, which logs in with `provider: "db"` username/password, fetches CSRF, and POSTs `/api/v1/security/guest_token/` with `resources:[{type:'widget',id}]` + `datasets:[...]` (W/example/server.mjs:52, 70, 82). The fork demo uses Keycloak OIDC, so the `db` login will not work as-is (UNVERIFIED at runtime).
- Renders: `SupersetProvider` with FilterSelect, MetricTile, bar + pie Chart cross-filtering, host filter bar (`useSupersetFilter`), event log (`useWidgetEvent`), optional extension widget, saved widgets by id, a Gallery with two providers sharing one bus (W/example/src/App.tsx:117-333, Gallery.tsx:140-188). Wrapped in `<StrictMode>` (main.tsx:29). **Hardcoded dev UUID** `<Widget id="4d9d1484-...">` renders an error tile elsewhere (App.tsx:331).
- `W/artifact/*` builds a single-file CDN bundle for Claude artifacts (out of scope; reuses the example's vite).

## 5. Tests added

| Kind | Where | Covers | How run |
|---|---|---|---|
| Jest | 12 files in W/src, 28 files in D/ and B/ (about 424 `test(` cases in total) | store, packing, RootGrid (with `spec/__mocks__/gridstackMock.ts`), WidgetView, filters, inspector, schema panel, header | `npm run test` in `superset-frontend` (jest maps added, F/jest.config.js:42-47) |
| Playwright | `F/playwright/tests/experimental/dashboard-v2/{empty-canvas,filters,layout-regressions,reposition-and-resize,split}.spec.ts` + page object `F/playwright/pages/DashboardV2Page.ts` (always starts at `dashboard/v2/new/`, :64-67) | palette drag preview/drop, filter -> chart query payload, scroll ownership, drag/resize persist in store, split drop. One `test.skip` (explicit `scope.targets`, filters.spec.ts:221). **No save/reload, no embed, no widgets-package e2e** | PR: `INCLUDE_EXPERIMENTAL=true npm run playwright:test` (PR playwright.config.ts:29-34). FORK master has no `tests/experimental` folder and no such env switch |

## 6. State and data flow, with defects found by tracing

Document: `{version: 1, nodes: Record<id, {type, layout?, children?, props?, style?}>}` (D/persistence.ts:22-27; D/DashboardProvider.ts:40). Flat map, parent -> `children: string[]` only, **no parent pointer** (`findParentId` scans all nodes and returns the first match, :239-246). Root id `'root'`, type `'grid'` (:42, 54). Ids `node_<n>` from a module counter, bumped past loaded ids (:89-101). Stored server-side inside legacy `dashboards.json_metadata` (superset/dashboard_v2/document.py:55-68, 104-113).

### 6.1 Cycles and malformed trees

| # | Finding | Evidence |
|---|---|---|
| T1 | `loadDocument` checks only that `root` exists; no check for cycles, multi-parent nodes, orphans, `root` listed as a child | D/DashboardProvider.ts:486-497 |
| T2 | Server `normalize_document` checks only node shape and that children ids exist; a document with `a.children=[a]` or `root -> a -> root` is accepted (API or MCP writers) | superset/dashboard_v2/document.py:70-101 |
| T3 | Unbounded recursion on a cycle: `isNodeOrDescendant` (:230-237), `removeSubtree` (deletes after recursing, :335-338), render recursion `WidgetView` -> containers -> `WidgetView`, `Outline` `Row` (B/Outline.tsx:209-256) -> stack overflow / frozen tab | as listed |
| T4 | Only `moveWidget` guards cycles in-app (:365-369); `addWidget` always creates a fresh id, so the client cannot create a cycle by itself, only load one | D/DashboardProvider.ts:287-326, 353-425 |
| T5 | Id collisions across writers: two tabs/users both mint `node_<max+1>` for different widgets; with last-writer-wins a filter's `scope.targets` or `embedWidgetId` can silently point at a different widget | D/DashboardProvider.ts:89-93 |

### 6.2 Save/load races and stale overwrites

| # | Path | Evidence |
|---|---|---|
| S1 | **No concurrency control**: PUT sends the full document, response `changed_on` unused, backend has no version/etag check -> silent last-writer-wins between tabs, users, API/MCP writers | D/persistence.ts:57-70; B/DashboardHeader.tsx:250-257 |
| S2 | Store is a process-wide singleton and the load effect returns early without `dashboardId`: opening `/dashboard/v2/new/` after another V2 dashboard shows the previous tree; Save then POSTs a copy | D/store.ts:37; B/index.tsx:187-188 |
| S3 | Switching A -> B: until B's GET resolves the header already carries `dashboardId=B` while the store holds A; Save in that window PUTs A's document into B | B/index.tsx:190-192, 306-308; B/DashboardHeader.tsx:245-249 |
| S4 | Load failure only toasts; store keeps the previous/blank tree and Save stays enabled -> overwrites the dashboard that failed to load | B/index.tsx:194-197 |
| S5 | Edits made before the GET resolves are discarded by `loadDocument` with no warning | B/index.tsx:192 |
| S6 | First save does `history.push('/dashboard/v2/<id>/')`; the param change re-runs the load effect, which replaces the tree with the server copy and clears bus values (contradicts the code comment "the tree is kept"); edits made between click and GET are lost | B/DashboardHeader.tsx:251-256; D/DashboardProvider.ts:493-496 |
| S7 | `commitWidgetProps`: snapshot props -> await server validation -> `updateProps(nodeId, normalized)` with the full pre-await object: any concurrent prop write (another control, `embedWidgetId`) is reverted; throws if the node was deleted meanwhile; removed keys never disappear because `updateProps` merges | B/controlValueValidation.ts:110-128; D/DashboardProvider.ts:470-480 |
| S8 | `SchemaControlPanel` is not keyed by node (`<SchemaControlPanel nodeId>`), and its debounced schema refetch is cancelled only on unmount -> a schema fetched for widget A can land in the panel showing widget B | B/Inspector.tsx:460; B/SchemaControlPanel.tsx:289 |
| S9 | Title has two sources: `root.props.title` (edited) and `dashboard_title` (sent on save, ignored on load) | B/DashboardHeader.tsx:243-247; B/index.tsx:192 |
| S10 | `EmbedWidgetModal` creates the saved widget, then writes `embedWidgetId` into node props, but the dashboard is not saved: leaving without Save orphans the widget row and the next click creates a duplicate. Saved widgets are **snapshots**; later node edits do not propagate until "Update saved widget" | D/EmbedWidgetModal.tsx:58-79 |
| S11 | `Number(dashboardId)` for the PUT id while GET accepts any ref -> `NaN` for slug/uuid URLs | B/index.tsx:306-308 |
| S12 | `/api/v1/widgets/types` failure is cached as an empty set for the session: every widget silently falls back to the generic form | B/schemaControlledWidgets.ts:49-58 |

### 6.3 Shared or mutated widget context objects

| # | Object | Problem | Evidence |
|---|---|---|---|
| X1 | `active` (module variable) in extension host | set during **render** of the last extension widget; `dashboard.fetchQueryData` uses it, so with 2+ extension widgets an async fetch runs with another instance's id, bus and data client (wrong filters, possibly wrong Superset/token) | W/src/embed/extensionHost.tsx:125, 171-183, 250 |
| X2 | `instances` Map keyed by `instanceId` only | global across providers, roots and Superset domains; default ids come from `useId()`, which repeats across React roots -> props/overrides/bus cross-talk, and one unmount deletes the other's entry | W/src/embed/extensionHost.tsx:111, 241-260; W/src/embed/Widget.tsx:130-131 |
| X3 | Shared `bus` prop + `useId()` ids | two roots sharing one bus generate identical bus ids; values overwrite each other and self-exclusion hides one widget's filter from the other. `createSession` avoids it with a module counter | W/src/embed/SupersetProvider.tsx:47-48; W/src/embed/session.tsx:109, 164-165 |
| X4 | `registered` component Map keyed by type only | an extension type loaded from Superset A is reused for Superset B (registry is consulted before the loader, whose cache is keyed `base\|id`) | W/src/registry.ts:37-53; W/src/embed/Widget.tsx:176-179; extensionLoader.ts:111, 185 |
| X5 | `window.superset ??= core` | first embedded extension's core (and `extensions.getContext()`) wins for every later one | W/src/embed/extensionLoader.ts:164 |
| X6 | `Widget` unmount cleanup + Theme remount | cleanup emits a cleared value; `FilterSelect` re-applies its default only when the value is `undefined`. After a remount (dark toggle 1.1, StrictMode dev double effect) the control still displays the default while the bus holds `resolved: null`, and user selections are dropped | W/src/embed/Widget.tsx:160-172; W/src/widgets/FilterSelectWidget.tsx:137-150, 191-195 |
| X7 | `DashboardProvider` singleton as bus | bus values survive route changes unless `loadDocument` runs (S2); every selection click re-renders every widget; `placement.ts` always mutates the singleton even under a `DashboardStoreContext` | D/DashboardProvider.ts:156, 184-191; D/placement.ts:33 |
| X8 | Coarse caches | dataset metadata cached by `datasetId` for the session, never invalidated; `EMPTY_PROPS` and `CLEARED` are shared frozen-by-convention objects (safe today, nothing freezes them) | D/datasetMetadata.ts:77-118; D/nodeWidgets.tsx:29; W/src/embed/hooks.ts:26 |
| X9 | Fetch key | `bindingKey` omits `client` and `instanceId`; changing provider credentials does not refetch | W/src/widgets/ChartWidget.tsx:298, 372 |

## 7. Compatibility with FORK master

`git merge-tree --write-tree master upstream/pr-44471` reports textual conflicts in only 5 frontend files; master has no `packages/superset-widgets`, `src/core/dashboard`, `packages/superset-core/src/{dashboard,widgets}`, `src/pages/DashboardBuilderV2` (all additive).

| PR-touched existing file | master drift since 6856d0fc67 | Port |
|---|---|---|
| `F/package.json` | +179/-208; **TypeScript 7.0.2** (PR 5.4.5), antd ^6.6.8 (PR ^6.5.1), ag-grid 36.3.0 (PR 36.0.1), immer, jest, webpack bumps | CONFLICT: re-add 2 lines (`@apache-superset/widgets`, `gridstack ^13.0.2`) |
| `F/package-lock.json` | +9078/-11451 | CONFLICT: regenerate with master's npm; `gridstack` is absent from master's lock |
| `F/tsconfig.json` | +24/-16; `baseUrl` removed, `moduleResolution: bundler`, per-package `paths` | CONFLICT: re-add widgets paths, reference, example exclude |
| `F/src/views/routes.tsx` | +100/-51; `lazy` -> `lazyWithRetry`, route objects gain `mobileSupported` | CONFLICT: re-add 2 routes with `lazyWithRetry` before `DASHBOARD` (master :250) |
| `F/playwright/tests/experimental/README.md` | deleted on master | CONFLICT: drop hunk, move specs to `playwright/tests/dashboard-v2/`, add a project or reuse `chromium` |
| `F/packages/superset-core/src/theme/Theme.tsx` | +105/-24: `mergeConfig`, `setConfig(config, baseTheme)`, listener Set + `useLayoutEffect` replace the single `updateProviders` callback; signature still `({ children })` at master :253, `<GlobalStyles />` :305 | merges textually; collides with RTL-WT (section 8) |
| `F/jest.config.js` | +43/-13, now ESM `export default`, `testRegex` includes `playwright/**.test` | clean; verify the 3 mapper lines landed |
| `F/packages/superset-core/package.json` | +26/-29 (TS 7, deps) | clean; verify `./dashboard`, `./widgets` exports present |
| `F/src/features/home/RightMenu.tsx` | +184/-39 | clean textually; UNVERIFIED that the menu item shape still matches |
| `F/src/features/semanticLayers/jsonFormsHelpers.tsx` | +222/-71 | clean textually; all 7 helpers the builder imports still exported on master (:36, 226, 523, 566, 590, 632, 655); PR adds `x-hidden` / `x-dependsOn` handling inside `buildUiSchema`, check it survived the rewrite |
| `F/src/dashboard/.../DatasetSelect.tsx` | +13/-35 | clean textually; PR only exports 3 helpers, confirm they still exist |
| `F/scripts/check-custom-rules.js`, `AntdEnhanced.tsx`, `translation/types/index.ts`, `routePaths.ts`, docs | small | clean |
| `F/src/extensions/*`, `F/src/core/{chat,views,navigation,index}`, `C/{index,views,navigation,chat}` | **unchanged on master** | clean |
| `W/tsconfig.json` (new file) | uses `baseUrl: "../.."` | must be rewritten like master `packages/superset-core/tsconfig.json` (explicit `paths`, add `@apache-superset/widgets`) |

Symbols verified present on master: `setupAGGridModules`, `ThemedAgGridReact`, `SafeMarkdown`, `Loading` (`inline-centered`), `Select.ariaLabel`, `PublishedLabel`, `ActionButton`, `EmptyState`, `MetadataType.Editor`, `KebabMenuButton`, `ErrorBoundary`, `createEventEmitter`, `DashboardEmbedModal(dashboardId)`, `ThunderboltOutlined`; `HolderOutlined/UndoOutlined/RedoOutlined` are added by the PR. Dependencies: `@jsonforms/*` and `@great-expectations/jsonforms-antd-renderers` already on master; `echarts ^6.1.0`, `react ^18.3`, `react-router-dom ^5.3.4`, `react-redux ^7.2.9` identical; no zustand. Type-checking the PR code under TS 7 and antd 6.6.8: UNVERIFIED (not compiled). Master Docker build copies every `package.json`/`package-lock.json` (Dockerfile:50-54), so the new workspace is picked up automatically but the root lock must be in sync.

## 8. Theme and direction reconciliation (RTL branch vs PR)

| Point | PR | RTL-WT (uncommitted) | Reconcile |
|---|---|---|---|
| Provider signature | `SupersetThemeProvider({children, withGlobalStyles = true})` | `SupersetThemeProvider({children, direction})`, direction = prop ?? parent `theme.direction` ?? `getDocumentDirection()` | one signature `{children, direction?, withGlobalStyles = true}`; same lines conflict (master Theme.tsx:253, 305) |
| Emotion cache | new `createCache({key:'superset'})` per provider instance | page-wide `getEmotionCache(direction)` (`superset` / `superset-rtl` with `@mui/stylis-plugin-rtl`) | keep RTL-WT; N embedded providers then share one cache |
| antd | `<ConfigProvider theme>` only | adds `direction={direction}` | keep RTL-WT |
| Embed host direction | not handled | falls back to the **host page** `<html dir>` | add `direction?: 'ltr'\|'rtl'` to `SupersetProviderProps` and pass it through (SupersetProvider.tsx:168) |
| Charts | `ChartWidget` draws ECharts directly, bypassing `SuperChartCore` where RTL-WT decides chart direction (`resolveChartDirection`, `DirectionProvider`) | - | wrap the canvas in `LtrIsolate`/`DirectionProvider direction="ltr"`; title/legend strings still need bidi review |
| Table | via `ThemedAgGridReact` | RTL-WT adds `useIsRtl()` -> `enableRtl` | inherited automatically |
| Popups | `FilterSelect` forces `getPopupContainer={() => document.body}` | - | fine for antd (context direction), but body-level popups sit outside any `LtrIsolate` wrapper |
| Layout | GridStack initialised without `rtl` option | - | pass `rtl: direction === 'rtl'` (or `'auto'`) in `GridStack.init` (D/useGridStack.ts:165) and audit `cellAtPoint`/`pixelRectForCell` which assume left origin (D/layoutStyle.ts:89-117) |
| In-app builder | uses the app's own provider (`F/src/theme/ThemeProvider.tsx:186` on master), not `SupersetProvider` | - | only the embed provider needs code changes |

## 9. Completeness matrix

| Capability | Status | Evidence / gap |
|---|---|---|
| Provider | partially | works by reading; remount-on-theme-change defect, no direction/locale, no tests (1.1) |
| Chart widget | works (limited) | ECharts only, bar/line/scatter structured + raw option; no SuperChart plugins, no legacy charts |
| Table widget | partially | plain AG Grid, no pagination/formatting/search, no tests |
| Metric | works | no comparison/trend query (static `delta` prop only), no tests |
| Filter | partially | only `filter.select`; `filter.range`/`filter.time` named in comments only (W/src/filterVocabulary.ts:22-23); X6 default-selection defect |
| Markdown | works | 7-line component |
| Saved widgets | partially | embed side works (`<Widget id>`); builder never renders by id (`NodeWidget` passes no `savedId`, D/nodeWidgets.tsx:56-59), cannot insert an existing saved widget, no list/management UI, snapshot semantics (S10) |
| Inline widgets | works | `{widget:{type,props}}` validated server-side |
| Cross-filtering | partially | chart click only, first dimension, single value, same dataset or explicit targets |
| Event bus | works | two implementations of one contract; no pruning |
| Host-controlled filters | works | `useSupersetFilter`, `session.setFilter` |
| Builder create/edit | works | palette, outline, inspector, schema forms |
| Builder save/restore | partially | manual save/load only; S1-S6 data-loss paths; undo/redo/history/autosave are stubs; no V2 list or viewer page |
| Layouts and resizing | works (LTR) | GridStack + flow containers; Playwright covers drag/resize/split; RTL untested |
| Widget-level embedding in an external React app | partially | example runs from monorepo source only; package not publishable (no exports map, no bundled build, undeclared deps); session mode needs same-site + CORS |
| Dashboard-level V2 embedding | missing | backend endpoint exists, no frontend consumer (section 3) |
| Extension-provided widgets | partially | in-app path is simple and plausible; embed path has X1-X5 singletons and needs `EMBEDDED_EXTENSION_ASSETS_PUBLIC`; UNVERIFIED end to end |
| Theming | partially | light/dark/system + `themeConfig`; no RTL, no global styles (by design), fonts not loaded by provider |

## 10. Ordered frontend work to run on master

1. Create the port branch from master; bring in the additive trees unchanged (`packages/superset-widgets`, `packages/superset-core/src/{dashboard,widgets}`, `src/core/dashboard`, `src/pages/DashboardBuilderV2`, `spec/__mocks__/gridstackMock.ts`, playwright page object). Decide explicitly whether to leave out the AI pieces (`src/core/clientTools`, chat hunks, `W/src/mcp`, `SupersetArtifactProvider`, `W/artifact`); `ExtensionsStartup` and `W/src/index.ts`/`session.tsx` import them, so removal needs small edits.
2. Resolve the 5 conflicts (section 7): `package.json` (+widgets, +gridstack), regenerate `package-lock.json`, `tsconfig.json`, `routes.tsx` (`lazyWithRetry`), playwright README/spec location.
3. Rewrite `W/tsconfig.json` for TS 7 (no `baseUrl`, explicit `paths` incl. `@apache-superset/widgets`), then run `npm run type` and fix TS 7 / antd 6.6 / ag-grid 36.3 type drift across W/, D/, B/.
4. Merge `Theme.tsx` with the RTL branch: single signature `{children, direction?, withGlobalStyles}`; add `direction` to `SupersetProvider`; LTR-isolate the ECharts canvas; GridStack `rtl`.
5. Fix `SupersetProvider` theme remount (keep one `Theme` instance, call `setConfig`/`toggleDarkMode` on change) and the `Widget` cleanup vs default-selection interplay (X6).
6. Harden the store: validate on `loadDocument` (single parent, reachable from root, acyclic, root not a child), add visited sets to recursive walkers, switch node ids to UUIDs; mirror the validation server-side.
7. Fix save/load: reset the store when the route has no id or the id changes, block Save until load succeeded, send and check `changed_on` (409 on mismatch), stop reloading after first save, take the title from one source, make `commitWidgetProps` merge a delta against current props.
8. Fix navigation mapping for `/dashboard/v2/:id/` and `getDashboardId`.
9. Add a read-only V2 route (provide `DashboardViewModeContext='view'`, per-page store via `DashboardStoreContext`) and wire `/api/v1/dashboard_v2/embedded/<uuid>` or hide the dashboard "Embed" button.
10. Extension host: key instances by `(bus, instanceId)`, pass the calling instance instead of module `active`, scope the registry per loader/domain; give `Widget` root-independent default ids.
11. Make the package consumable: `exports` map, declared deps, a real bundle step; update the example (remove hardcoded UUID, guest-token broker that works with the fork's OIDC login, or session mode against the demo stack with CORS).
12. Tests: jest for provider, table, metric, filter, guestToken, hooks; Playwright for save -> reload -> restore, widget embed via the example or `playwright/embedded-app`, RTL smoke; un-skip the `scope.targets` spec.

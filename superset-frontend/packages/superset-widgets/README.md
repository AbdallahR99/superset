<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# @apache-superset/widgets

Superset widgets (charts, metric tiles, tables, filters, markdown) as plain
React components. The Dashboard v2 builder renders its widgets from this
package, and any React app can render the same widgets in its own tree. The
package is consumed from source and is not published.

## Usage

```tsx
import {
  SupersetProvider,
  Widget,
  Chart,
  MetricTile,
  Table,
  FilterSelect,
  Markdown,
} from '@apache-superset/widgets';

<SupersetProvider
  supersetDomain="https://superset.example.com"
  fetchGuestToken={() =>
    fetch('/api/superset-token', { method: 'POST' }).then(r => r.text())
  }
  filters={{
    tenant: {
      datasetId: 17,
      column: 'tenant',
      operator: 'EQUALS',
      value: 'acme',
    },
  }}
  onError={(error, info) => report(error, info)}
  direction="rtl" // or locale="ar"; omit to follow the page
  themeMode="default" // 'default' | 'dark' | 'system'
>
  {/* inline: defined in the host, validated and executed by Superset */}
  <Chart
    dataBinding={{
      datasetId: 17,
      metrics: ['sum__num'],
      dimensions: ['state'],
      rowLimit: 10,
    }}
    chartType="bar"
    crossFilter
    echartsOptions={{
      xAxis: {
        type: 'category',
        data: { $bind: { source: 'dimension', alias: 'state' } },
      },
      yAxis: { type: 'value' },
    }}
  />
  <Table
    dataBinding={{
      datasetId: 17,
      metrics: ['sum__num'],
      dimensions: ['state'],
    }}
  />
  <MetricTile
    dataBinding={{ datasetId: 17, metrics: ['sum__num'] }}
    label="Births"
  />
  <FilterSelect datasetId={17} column="gender" />
  <Markdown content="**Notes** for this page" />

  {/* generic form of the same thing */}
  <Widget
    type="metric-tile"
    props={{ dataBinding: { datasetId: 17, metrics: ['sum__num'] } }}
  />

  {/* saved in Superset (GET /api/v1/widget/) */}
  <Widget id="cedf0501-fa36-4e19-9f84-e9da6d657dcc" />
</SupersetProvider>;
```

- Widgets fill their container; give the parent a size.
- Every built-in type (`echarts`, `ag-grid-table`, `metric-tile`,
  `filter.select`, `markdown`) renders from an inline definition (`type` +
  `props`, or the typed component) and from a saved widget (`id`). A saved
  widget's query is always run from the definition Superset stores.
- Common props on every widget: `instanceId`, `className`, `style`,
  `fallback`, `renderError`, `showTitle`.
- The typed components' props mirror the widget's control schema
  (`GET /api/v1/widgets/type/<type>/control-schema`).

## `SupersetProvider`

| Prop                                               | Purpose                                                                                                                                                                                          |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `supersetDomain`                                   | Origin (and optional path prefix) of the deployment.                                                                                                                                             |
| `fetchGuestToken`                                  | Returns a guest token from the host's backend. Called again when the token nears expiry or Superset answers 401, so it is also the refresh callback. Omit to use the browser's Superset session. |
| `guestTokenKey`                                    | Who the token is for. Change it when the user or tenant changes: the cached token is dropped and every widget fetches again.                                                                     |
| `guestTokenHeaderName`, `guestTokenFetchTimeoutMs` | Header name (default `X-GuestToken`) and broker timeout (default 30 s).                                                                                                                          |
| `csrf`                                             | Session mode only: send Superset's CSRF token with posts. Default `true`.                                                                                                                        |
| `client`                                           | A `WidgetDataClient` of your own; replaces `supersetDomain` and the token options.                                                                                                               |
| `bus`                                              | A `WidgetBus` shared with another provider or React root, so their widgets cross-filter.                                                                                                         |
| `filters`                                          | Host-controlled filters, by key: `{ datasetId, column, operator, value, targets? }`, or `null`.                                                                                                  |
| `widgets`                                          | Widget types of the host's own (`{ [type]: Component }`), for this provider only.                                                                                                                |
| `extensionWidgets`                                 | `false` turns loading of extension widgets off; a loader of your own replaces the default.                                                                                                       |
| `onError`                                          | `(error, info) => void` for every failure a widget shows.                                                                                                                                        |
| `direction`, `locale`                              | Text direction (`'ltr'`/`'rtl'`), or a locale to derive it from.                                                                                                                                 |
| `themeMode`, `themeConfig`                         | `'default'`, `'dark'` or `'system'`, and a Superset theme config.                                                                                                                                |

### Providers are independent

A provider owns its event bus, data client, guest token, CSRF token, host
filters, theme and extension widgets. None of that is kept at module level, so
two providers on one page — different deployments, tokens for different users,
different filters — do not see each other's requests, events or filters. They
share only what the host passes to both (`bus`, `client`, a custom extension
loader), and the code of an extension both render (see
[Extension widgets](#extension-widgets)). Changing `supersetDomain`, `guestTokenKey` or `client` makes every
widget under the provider fetch again with the new one; answers still in flight
for the old one are discarded.

### Authentication

| Mode                            | Request                                                                                                                                                     | Deployment needs                                                                                            |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Guest token (`fetchGuestToken`) | `X-GuestToken` header, `credentials: 'omit'` — the viewer's own Superset cookies are never sent                                                             | CORS for the host origin with `Content-Type` and `X-GuestToken` allowed                                     |
| Session (no `fetchGuestToken`)  | `credentials: 'include'`; posts carry `X-CSRFToken`, fetched once per provider from `/api/v1/security/csrf_token/` and fetched again if Superset rejects it | Same site, or CORS with `supports_credentials`, `X-CSRFToken` allowed and session cookies usable cross-site |

A guest token Superset answers 401 to is dropped, a new one is requested from
`fetchGuestToken`, and the request is retried once.

### Errors

Nothing is thrown while rendering. A failure is shown in the widget's own box
(or through its `renderError`) and passed to `onError`:

```ts
onError(error: Error, info: {
  phase: 'config' | 'definition' | 'data' | 'values' | 'extension' | 'render';
  instanceId?: string;
  widgetType?: string;
  savedId?: string;
});
```

Failed calls to Superset are `WidgetApiError`s with a `status` and a `kind`:

| `kind`               | When                                                                                          |
| -------------------- | --------------------------------------------------------------------------------------------- |
| `unauthorized` (401) | The guest token was refused after one refresh, or the viewer has no Superset session.         |
| `forbidden` (403)    | The token has no `widget` / `dataset` resource for this, or the account lacks access.         |
| `not_found` (404)    | The saved widget (or what it refers to) no longer exists.                                     |
| `conflict` (409)     | Superset reported a conflicting state.                                                        |
| `invalid` (400, 422) | Props the widget type rejects, an unknown filter column, a SQL metric or filter from a guest. |
| `network`            | Superset could not be reached, or CORS refused the call.                                      |
| `config`             | The provider has neither `supersetDomain` nor `client`.                                       |

### Filters, events and cancellation

- `filters` on the provider is the declarative form: the widgets follow the
  prop. The first request of every widget already carries the filters the
  provider was mounted with; a later change makes the affected widgets fetch
  again; `null`, a dropped key or unmounting lifts the filter.
- `useSupersetFilter(key)` is the imperative form: it returns a stable setter
  that takes a filter or `null`, and clears the filter when the calling
  component unmounts.
- `useWidgetEvent('valueChanged', e => …)` receives filter and cross-filter
  selections (`e.payload.resolved`) from this provider's widgets, and
  unsubscribes on unmount. `useWidgetValue(instanceId)` reads a widget's
  current selection.
- A widget that unmounts is forgotten by the bus, so it stops filtering the
  ones that stay.
- Every request carries an `AbortSignal`. When a widget's binding, filters,
  saved id or client change, or it unmounts, the request in flight is aborted
  and whatever still arrives for it is ignored: a slow earlier answer never
  replaces a newer one.

### Right-to-left

`direction` (or `locale`) is handed to Superset's theme provider; without
either, the widgets follow an enclosing Superset theme or `<html dir>`. In a
right-to-left provider the widgets, controls and the AG Grid table are
mirrored, while chart canvases stay left to right as they do in Superset.

## Content is treated as data

A widget definition is written by one person and rendered in another's page.

- Markdown is always sanitised: scripts, event handlers, frames and
  script-capable links in the source do not reach the DOM.
- Table `columnDefs` go through an allowlist of declarative settings: `field`,
  `colId`, `headerName`, `headerTooltip`, widths and `flex`, `hide`,
  `sortable`, `resizable`, `filter` (boolean), text wrapping, and — with
  built-in values only — `type`, `cellDataType`, `sort`, `pinned`. Everything
  else is dropped, including whatever AG Grid would evaluate, call or hand the
  DOM to (`valueGetter`, `valueFormatter`, `cellRenderer`, `cellClassRules`,
  `headerComponent`, `tooltipComponent`, column groups, …). `sanitizeColumnDefs`
  is the function.
- `echartsOptions` goes through an allowlist as well (`sanitizeEchartsOption`),
  after `$bind` markers are resolved:
  - only top-level keys known to draw on the canvas are passed on (`series`,
    axes, `grid`, `legend`, `dataset`, `dataZoom`, `visualMap`, colours and
    animation settings, …); `graphic`, `baseOption`, `media`, `options`,
    `timeline` and unknown keys are dropped;
  - `graphic`, `dataView`, `renderItem`, `extraCssText`, `className`,
    `appendTo`, `appendToBody` and DOM event handlers (`onclick`, …) are
    dropped at any depth;
  - a `tooltip`, wherever it sits (option, series, data item, axis, legend), is
    rebuilt from known settings. A string `formatter` is HTML-escaped whole:
    no tag survives, `<b>` and `<br/>` included. `content` and colours that
    are not plain CSS values are dropped;
  - the `toolbox` keeps `saveAsImage`, `restore`, `dataZoom` and `magicType`
    without titles, icons or tooltips, and `magicType` without its per-type
    `option` fragments. `dataView` and custom `my*` tools are dropped;
  - `link` / `sublink` must be `http(s):`, `mailto:` or relative.

  A function is kept where a setting takes one (a tooltip `formatter` or a
  custom series' `renderItem` passed by host code): JSON, and so a stored
  widget, cannot carry one.

These run in the browser, on every render, and drop what they do not accept
without saying so. The rules of record are the server's: it validates the props
of a saved widget, of a Dashboard V2 document and of every inline widget it is
asked to query, and refuses (422, with the path of the offending setting in
`errors`) instead of dropping. The lists above are the server's lists, so
nothing drawn here is something the server would have refused to store; the
server additionally refuses any authored string that holds markup (`<b>` in a
label, say), which the renderer does not second-guess because by then `$bind`
has put query results, which may well contain a `<`, where the markers were.
Write tooltips as plain templates (`{b}: {c}`), and expect a refusal rather
than a silently different chart when a definition uses something from the
lists of dropped settings.

## Extension widgets

A widget type contributed by a Superset extension embeds like any other — the
type names the extension that draws it, so the provider fetches that extension
and loads its frontend the first time one of its widgets renders:

```tsx
<Widget type="extensions.acme.widgets.funnel" props={{ dataBinding }} />
<Widget id="<uuid of a saved widget of that type>" />
```

The extension's module runs in the host page with the host's React, and works
against a `@apache-superset/core` whose `views` and `dashboard` namespaces are
backed by a provider: `dashboard.getNode(nodeId)` returns the props the host
passed, `emit`/`on`/`getValue` are that provider's bus (so it cross-filters
with the built-in widgets), and `fetchQueryData(binding, { nodeId, signal })`
runs through the widget data API under that provider's credentials.
Contributions to anything other than `dashboard.widgets`, and calls the
embedded host cannot answer (placing nodes, opening editors), are no-ops or
throw rather than being silently wrong.

**Who is asking.** `fetchQueryData` needs to know which widget the query is
for, so that widget is not narrowed by its own selection. `nodeId` is optional
where the host can tell: a call made while a widget renders, or from an effect
of that widget (or of a component it renders), is attributed to it. A call
made later — an event handler, a timer, after an `await` — carries no such
context; pass `{ nodeId }` there, or the query is attributed to the
provider's only extension widget if there is exactly one and to no widget
otherwise.

**One copy of the code, one core per provider.** An extension's bundle is
fetched and evaluated once per page, however many providers render its
widgets: a second evaluation of a Module Federation remote entry is not
guaranteed to produce an independent copy. Each provider has an
`ExtensionHost` of its own (registrations, rendered nodes, listeners, bus,
client), and an extension reaches it in one of two ways:

- **By argument (recommended).** Export `activate(core)` from the entry
  module. It is called once per provider with that provider's core; register
  the widgets on it and use it for every later call. Nothing is read from a
  global, so two providers are isolated exactly.

  ```ts
  export function activate(core: typeof import('@apache-superset/core')) {
    core.views.registerView(
      { id: 'funnel', name: 'Funnel' },
      'dashboard.widgets',
      ({ nodeId }) => <Funnel nodeId={nodeId} dashboard={core.dashboard} />,
    );
  }
  ```

- **By import, or by the `superset` global (compatibility).** An extension
  that registers as a side effect of being imported and calls what it imported
  from `@apache-superset/core` — or, when built with
  `externals: {'@apache-superset/core': 'superset'}`, what it reads from
  `window.superset` — talks to one stable, page-wide facade. Its
  registrations are recorded once and replayed into every provider, and each
  later call is routed to a provider: the one whose widget is rendering or
  having its effects run; else the only one that has the named node on
  screen; else the only one with any widget on screen.

  **Limitation.** A call that names no node (or an id two providers both
  use), made from an event handler, a timer or after an `await`, while two
  providers have widgets on screen, cannot be routed. It throws
  (`… cannot tell which SupersetProvider it is for`) instead of reaching the
  wrong provider. A listener such an extension registers at module level
  hears the events of every provider that renders it. Ids the package
  generates are unique on the page; explicit `instanceId`s should be too if
  such an extension is used under two providers. `window.superset` is left
  in place after the first load; a page that already had a `superset` global
  gets its own back.

- `extensionWidgets={false}` turns loading off; a
  `createExtensionWidgetLoader({ supersetDomain, getGuestToken })` of your own
  replaces it. Give a loader to one provider only, unless the providers also
  share a `bus` and a `client`.
- The deployment needs `EMBEDDED_EXTENSION_ASSETS_PUBLIC = True` for guest
  tokens: extension chunks load as plain `<script>` tags, which cannot carry
  the token. With the browser's Superset session (same-site) it is not needed.
- Extensions built before the CLI's `publicPath: "auto"` default can only be
  embedded same-origin; their chunk URLs are pinned to the page's own origin.

## Embedding, step by step

### 1. Configure Superset

```python
FEATURE_FLAGS = {
    "DASHBOARD_V2": True,       # the widget APIs answer 404 without it
    "EMBEDDED_SUPERSET": True,  # guest tokens
}
GUEST_ROLE_NAME = "WidgetGuest"  # see step 2
ENABLE_CORS = True
CORS_OPTIONS = {
    "origins": ["https://app.example.com"],  # the host page's origin, exactly
    "resources": [r"/api/*"],
    "allow_headers": ["Content-Type", "X-GuestToken"],
}
```

- **Session mode across origins** (no guest token; the viewer's Superset
  login): add `"X-CSRFToken"` to `allow_headers` and
  `"supports_credentials": True`; `/api/v1/security/csrf_token/` must be
  reachable from the host origin and the session cookie usable cross-site.
  Same-site hosts need none of this.
- **Extension widgets with guest tokens:** `EMBEDDED_EXTENSION_ASSETS_PUBLIC =
  True` (and `ENABLE_EXTENSIONS`), because extension chunks load as plain
  `<script>` tags.
- **Embedding a whole Dashboard v2 document cross-origin** additionally needs
  `ETag` in `expose_headers`, `If-Match` in `allow_headers`, and `can read on
  Dashboard` on the guest role. Embedding widgets does not.

### 2. Give the guest role exactly what a widget needs

Every guest token acts with the role named by `GUEST_ROLE_NAME`. For widgets
that role needs **`can read on Chart`** and nothing else; in particular no
dataset or database permission — what a guest may read comes from the token.
Use a dedicated role rather than `Gamma` or `Public`, so nothing granted to
those for other reasons reaches guests.

Row-level security rules that apply to the guest role are enforced for
guests. Rules that apply to the widget author's own roles are **not**: a
guest is not the author.

### 3. Create the service account that mints tokens

Your backend signs in to Superset as an account that:

- has `can grant guest token on SecurityRestApi`;
- can itself read every dataset it grants. Superset checks each grant against
  this account's own dataset access when the token is minted, so an account
  that can mint tokens but not read a dataset cannot hand that dataset to a
  guest.

### 4. Mint tokens on your backend

`POST /api/v1/security/guest_token/`, after authenticating your own user.
Never from the browser, and never with Superset credentials in a `VITE_*` /
`NEXT_PUBLIC_*` variable. Grant exactly what the page renders:

| You render                                    | `resources` entry                             | What it grants                                                                                                                                                                                                 |
| --------------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<Widget id="<uuid>">`                        | `{ "type": "widget", "id": "<uuid>" }`        | That saved widget and the dataset it is bound to when the token is minted. If the widget is later pointed at another dataset, the token stops working for it: mint a new one.                                  |
| inline widgets (`<Chart>`, `<Widget type>` …) | `{ "type": "dataset", "id": "<dataset id>" }` | SQL-free inline definitions against that one dataset. This is the only thing that grants them: a `widget` or `dashboard` resource does not, and neither does the `datasets` claim, which only narrows a token. |

```ts
body: JSON.stringify({
  user: { username: user.id },
  resources: [
    { type: 'widget', id: SAVED_WIDGET_UUID },
    { type: 'dataset', id: String(DATASET_ID) },
  ],
  rls: [
    { dataset: DATASET_ID, clause: `tenant_id = ${Number(user.tenantId)}` },
  ],
});
```

- **`rls`.** Rows a guest sees are bounded by the token's `rls` rules plus the
  rules that apply to the guest role. Without either, the widget sees every
  row the dataset returns. For a dataset that carries RLS rules in Superset,
  a `widget` or `dataset` grant is refused (400) unless a token rule covers
  that dataset (one naming it, or one with no `dataset`) with a non-empty
  clause. The account that mints the token must be an admin or have no RLS
  rule applying to it on that dataset: a minter cannot hand out rows it
  cannot see itself. A deployment whose `GUEST_TOKEN_VALIDATOR_HOOK` enforces
  an equivalent policy can switch the built-in check off with
  `GUEST_TOKEN_WIDGET_RLS_GUARD = False`.
- **No SQL from guests.** An inline definition may use saved metric names and
  simple aggregates (`AVG`, `COUNT`, `COUNT_DISTINCT`, `MAX`, `MIN`, `SUM`) on
  existing columns. A `sqlExpression` anywhere is a 400. SQL stored in a saved
  widget is its author's, who needed SQL Lab access or editorship of the
  dataset to save it.
- Do not send `datasets` unless you mean to narrow a dashboard token: listing
  datasets there that leave out a saved widget's dataset denies that widget.
- Host `filters` are ANDed onto the widget's query. They narrow what is shown;
  they are not access control.

[`example/server.mjs`](example/server.mjs) is a minimal broker that does
this.

### 5. Render

Wrap the widgets in one `SupersetProvider` per deployment and token identity
(see [Usage](#usage)), with `fetchGuestToken` calling your backend and
`guestTokenKey` set to whoever the token is for.

### When it does not work

| Symptom                                    | Cause                                                                                                                                                                   |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 404 on `/api/v1/widget/*`                  | `DASHBOARD_V2` is off.                                                                                                                                                  |
| `network` error, CORS message in console   | The host origin, or the `X-GuestToken` header, is missing from `CORS_OPTIONS`.                                                                                          |
| 401 (`unauthorized`)                       | The token expired or was refused and a fresh one was refused too; or, in session mode, the viewer is not logged in to Superset.                                         |
| 403 (`forbidden`) on a saved widget        | The token has no `widget` resource for that uuid, the widget was re-pointed at another dataset after the token was minted, or the guest role lacks `can read on Chart`. |
| 403 (`forbidden`) on an inline widget      | The token has no `dataset` resource for that dataset id.                                                                                                                |
| 400 (`invalid`)                            | Props the widget type rejects, an unknown column in a filter, or SQL in a guest's inline definition.                                                                    |
| 400 / 403 when minting                     | The service account cannot read a granted dataset or widget, lacks `can grant guest token`, or the dataset is RLS-protected and no token rule covers it.                |
| An extension widget never loads as a guest | `EMBEDDED_EXTENSION_ASSETS_PUBLIC` is off.                                                                                                                              |

## Public API

| Area                                           | Exports                                                                                                                                                                                                                                                                  |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Embedding                                      | `SupersetProvider`, `Widget`, `Chart`, `Table`, `MetricTile`, `FilterSelect`, `Markdown`                                                                                                                                                                                 |
| Hooks                                          | `useSupersetFilter`, `useWidgetEvent`, `useWidgetValue`, `useWidgetData`, `useWidgetBus`, `useWidgetBusRevision`, `useWidgetDataClient`, `useWidgetApplySource`, `useWidgetErrorReporter`, `useExtensionWidget`                                                          |
| Clients and tokens                             | `createHttpWidgetClient`, `createApiFetch`, `createGuestTokenSource`, `guestTokenExpiry`, `sessionDataClient`, `widgetRef`, `fetchQueryData`, `describeFetchError`                                                                                                       |
| Errors                                         | `WidgetApiError`, `isAbortError`, types `WidgetErrorInfo`, `WidgetErrorKind`, `WidgetErrorPhase`                                                                                                                                                                         |
| Bus and filters                                | `createWidgetBus`, `hostFilterPayload`, `getActiveResolvedFilters`, `getActiveAdhocFilters`, `toAdhocFilters`, `FILTER_BAR_APPLY_EVENT`                                                                                                                                  |
| Contexts (for a host that is its own provider) | `WidgetBusContext`, `WidgetDataClientContext`, `WidgetErrorContext`, `WidgetComponentsContext`, `WidgetApplySourceContext`, `ExtensionWidgetLoaderContext`                                                                                                               |
| Widget types                                   | `builtInWidgetComponents`, `getWidgetComponent`, `registerWidgetComponent`, `unregisterWidgetComponent` (page-wide; use the provider's `widgets` for one provider)                                                                                                       |
| Extensions                                     | `createExtensionWidgetLoader`, `createExtensionHost`, `isExtensionWidgetType`, `parseExtensionWidgetType`                                                                                                                                                                |
| Content safety                                 | `resolveBindings`, `sanitizeEchartsOption`, `sanitizeColumnDefs`                                                                                                                                                                                                         |
| Layout documents                               | `walkTree`, `validateTree`, `sanitizeTree`, `collectSubtreeIds`, `isNodeOrDescendant`, `findParentId`, `getAncestorIds`, `subtreeDepth`                                                                                                                                  |
| Types                                          | `WidgetProps`, `WidgetComponent`, `WidgetBus`, `WidgetDataClient`, `WidgetDataRequest`, `WidgetValuesRequest`, `WidgetRequestOptions`, `WidgetRef`, `SavedWidget`, `HostFilter`, `ResolvedFilter`, `FilterOperator`, `DataBindingSpec`, `QueryDataResult`, `WidgetEvent` |

### Layout document utilities

A layout document is a flat map of nodes that name their children by id.
Nothing in that shape prevents a cycle, a node with two parents or a missing
child, and a document can arrive that way from storage. The tree helpers walk
iteratively with a visited set, a depth cap (64) and a node cap (10 000), and
report what they had to skip:

```ts
import { validateTree, sanitizeTree, walkTree } from '@apache-superset/widgets';

const issues = validateTree(document.nodes, 'root');
// [{ kind: 'cycle' | 'multiple-parents' | 'missing-child' | 'max-depth'
//          | 'max-nodes' | 'unreachable' | 'missing-root', id, parentId? }]
const { nodes } = sanitizeTree(document.nodes, 'root'); // a tree, always
walkTree(nodes, 'root', ({ id, node, depth }) => {
  /* each node once */
});
```

## Consuming from source

A host bundler must compile the package and its Superset dependencies from
`src`:

- alias `@apache-superset/widgets`, `@apache-superset/core(/*)` and
  `@superset-ui/core(/*)` to `packages/<name>/src`;
- React automatic JSX runtime with `importSource: '@emotion/react'` and
  `@emotion/babel-plugin`;
- SVG imports as React components (svgr);
- define `process.env.NODE_ENV`, `process.env.WEBPACK_MODE`, `global`;
- dedupe `react`, `react-dom`, `@emotion/react`, `antd`.

[`example/vite.config.ts`](example/vite.config.ts) does all of this.

## Trust boundary

Widgets run in the host page's JavaScript context: the host trusts this code,
and an XSS in the host can read the guest token and any rows it grants. Keep
tokens short-lived and narrowly scoped. For third-party or untrusted hosts use
the iframe embed (`@superset-ui/embedded-sdk`).

## Design notes

- The widget, not the dashboard, is the unit of embedding. The builder
  implements the same `WidgetBus` / `WidgetDataClient` contracts as
  `SupersetProvider`, so there is one implementation of each widget.
- Those contracts live in `@apache-superset/core/widgets`, not here: what a
  widget is, and what it may ask of whoever renders it, is platform API that
  the builder, a host app and any extension writing a widget must agree on.
  This package implements them (and re-exports the types, so a host app needs
  one import), which keeps a charting runtime out of the module federation
  singleton every extension shares.
- Data always runs on the server through the widget registry, either from the
  stored definition (`{id}`) or from a validated inline spec
  (`{widget: {type, props}}`), via `POST /api/v1/widget/data` and `/values`.
- An extension's widget is loaded by the page that renders it, not bundled: the
  type (`extensions.<publisher>.<name>.<type>`) names the extension, and the
  same `views.registerView` call it makes in Superset registers it with the
  provider's extension host.
- Extension code runs in the host page's context, on the host's trust; it is
  not sandboxed.

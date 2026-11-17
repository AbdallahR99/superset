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
filters, theme and extension widgets. Nothing is kept at module level, so two
providers on one page — different deployments, tokens for different users,
different filters — do not see each other's requests, events or filters. They
share only what the host passes to both (`bus`, `client`, a custom extension
loader). Changing `supersetDomain`, `guestTokenKey` or `client` makes every
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
| `forbidden` (403)    | The token does not name this saved widget or dataset, or the account lacks access.            |
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
- Table `columnDefs` keep declarative settings only (`field`, `headerName`,
  widths, `pinned`, `hide`, `sort`, …). Anything AG Grid would evaluate or call
  (`valueGetter`, `valueFormatter`, `cellRenderer`, `cellClassRules`, …) is
  dropped.
- In `echartsOptions`, a tooltip's HTML `formatter` template is sanitised and
  `link`/`sublink` values that could run script are removed. The option is
  walked with a depth limit and cycle detection.

## Extension widgets

A widget type contributed by a Superset extension embeds like any other — the
type names the extension that draws it, so the provider fetches that extension
and loads its frontend the first time one of its widgets renders:

```tsx
<Widget type="extensions.acme.widgets.funnel" props={{ dataBinding }} />
<Widget id="<uuid of a saved widget of that type>" />
```

The extension's module runs in the host page with the host's React, and gets a
`@apache-superset/core` whose `views` and `dashboard` namespaces are backed by
the provider that loaded it: `dashboard.getNode(nodeId)` returns the props the
host passed, `emit`/`on`/`getValue` are that provider's bus (so it
cross-filters with the built-in widgets), and
`fetchQueryData(binding, { nodeId, signal })` runs through the widget data API
under that provider's credentials. Pass `nodeId`: it tells the host which
widget is asking, so that widget is not narrowed by its own selection. Without
it the query is attributed to no widget in particular. Contributions to
anything other than `dashboard.widgets`, and calls the embedded host cannot
answer (placing nodes, opening editors), are no-ops or throw rather than being
silently wrong.

- Each provider loads and evaluates an extension for itself, into an
  `ExtensionHost` of its own, so the same extension under two providers is two
  independent copies.
- `extensionWidgets={false}` turns loading off; a
  `createExtensionWidgetLoader({ supersetDomain, getGuestToken })` of your own
  replaces it. Give a loader to one provider only, unless the providers also
  share a `bus` and a `client`.
- The deployment needs `EMBEDDED_EXTENSION_ASSETS_PUBLIC = True` for guest
  tokens: extension chunks load as plain `<script>` tags, which cannot carry
  the token. With the browser's Superset session (same-site) it is not needed.
- Extensions built before the CLI's `publicPath: "auto"` default can only be
  embedded same-origin; their chunk URLs are pinned to the page's own origin.

## Tokens

Mint guest tokens on your backend (`POST /api/v1/security/guest_token/`) after
authenticating your own user. Never mint them in the browser.

| You render     | The token needs                                                     |
| -------------- | ------------------------------------------------------------------- |
| `<Widget id>`  | `resources: [{ "type": "widget", "id": "<uuid>" }]`                 |
| inline widgets | `datasets: [<dataset id>, …]` (inline specs are refused without it) |

Add `rls` rules scoped to your user; without them the widget sees every row the
dataset returns. For guests, inline specs may only use saved metrics or simple
aggregates on existing columns: SQL metrics and SQL filters are rejected.
Filters from the host are always ANDed onto the widget's query; they narrow
what is shown and are not an access control.

## Superset configuration

```python
FEATURE_FLAGS = {"EMBEDDED_SUPERSET": True}
GUEST_ROLE_NAME = "Gamma"   # a role with can_read on Chart
ENABLE_CORS = True
CORS_OPTIONS = {
    "origins": ["https://app.example.com"],
    "resources": [r"/api/*"],
    "allow_headers": ["Content-Type", "X-GuestToken"],
}
```

For session mode across origins add `"X-CSRFToken"` to `allow_headers` and
`"supports_credentials": True`.

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

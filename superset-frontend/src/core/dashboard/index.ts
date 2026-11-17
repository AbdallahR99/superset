/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

/**
 * @fileoverview Host implementation of the `dashboard` contribution type
 * (prototype). Extensions/the AI agent call the public `dashboard.*` API
 * (`@apache-superset/core`) to place/move/resize/remove nodes; the host owns
 * the single in-memory node tree backing the "Dashboard v2" prototype page.
 *
 * The public namespace (`dashboard`) is exposed to extensions on
 * `window.superset`. `useDashboardRevision` is host-internal and NOT part of
 * the public `@apache-superset/core` API — it's how the prototype's own
 * canvas renderer knows to re-render, then walks the tree via the same
 * `getRoot`/`getNode` accessors extensions use.
 */

// Not `import type`: `dashboardApi.VALUE_CHANGED_EVENT` below needs the real
// runtime value the `@apache-superset/core` package compiles for that one
// `const` export (unlike the ambient `declare function`s alongside it, which
// this object exists to implement and have no JS output of their own).
import { dashboard as dashboardApi } from '@apache-superset/core';
import { store } from 'src/views/store';
import { provider, useDashboardRevision } from './store';
import { fetchQueryData as fetchUnfilteredQueryData } from '@apache-superset/widgets/chartData';
import { getActiveAdhocFilters } from '@apache-superset/widgets/activeFilters';
import { navigation } from '../navigation';

// This module is part of the application's main bundle: `src/core` re-exports
// it, and the extension bridge hands `dashboard` to extensions from there.
// It therefore imports the store and the query path and nothing that draws:
// the built-in widget views are registered by the Dashboard v2 page's own
// chunk (see `registerBuiltInWidgets` and `src/pages/DashboardBuilderV2`),
// which is only ever loaded where the feature is turned on. Importing them
// from here would put the grid engine and every widget renderer in front of
// every page of the application, flag or no flag.

export { useDashboardRevision };

// The classic dashboard's id lives in the ordinary Redux store (populated
// when its own page mounts), not in `provider` — that class only ever knows
// about the separate, unpersisted "Dashboard v2" canvas tree. `dashboardInfo`
// itself is never reset on navigation (only ever merged/hydrated), so without
// the page check below, navigating away from a dashboard within the SPA
// (no full reload) would leave this returning the *previous* dashboard's id
// instead of "no dashboard active."
function getDashboardId(): number | undefined {
  // A Dashboard v2 page is its own page (`dashboard_v2`), saved or not, so
  // the classic dashboard's id in Redux (whichever classic dashboard was
  // open before it) is never reported for one.
  if (navigation.getPage() !== 'dashboard') return undefined;
  // The page is derived from the router's location, which trails the
  // address bar by a render; the address itself is the last word.
  if (window.location.pathname.includes('/dashboard/v2/')) return undefined;
  return store.getState().dashboardInfo?.id;
}

/**
 * `dashboard.fetchQueryData` for the builder's own tree.
 *
 * With `options.nodeId` the query is the one that widget would be shown:
 * narrowed by every filter on the dashboard that applies to it, and never by
 * the widget's own selection (a chart that cross-filters is not filtered by
 * the slice it was clicked on). That is what the same call does for an
 * extension widget under `SupersetProvider`, so a widget behaves alike in
 * the builder and embedded.
 *
 * Without a node id nobody is asking in particular, and the query is run as
 * given: what a caller checking a binding before placing a widget wants.
 *
 * `options.signal` cancels the request either way.
 */
const fetchQueryData: typeof dashboardApi.fetchQueryData = (
  binding,
  options = {},
) => {
  const { nodeId, signal } = options;
  if (nodeId === undefined) {
    return fetchUnfilteredQueryData(binding, { signal });
  }
  return fetchUnfilteredQueryData(
    {
      ...binding,
      filters: [
        ...(binding.filters ?? []),
        ...getActiveAdhocFilters(provider, binding.datasetId, nodeId),
      ],
    },
    { signal },
  );
};

export const dashboard: typeof dashboardApi = {
  getDashboardId,
  getRoot: provider.getRoot,
  getNode: provider.getNode,
  addWidget: provider.addWidget.bind(provider),
  removeWidget: provider.removeWidget.bind(provider),
  moveWidget: provider.moveWidget.bind(provider),
  updateLayout: provider.updateLayout.bind(provider),
  updateProps: provider.updateProps.bind(provider),
  onDidLayoutChange: provider.onDidLayoutChange,
  VALUE_CHANGED_EVENT: dashboardApi.VALUE_CHANGED_EVENT,
  emit: provider.emit,
  getValue: provider.getValue,
  on: provider.on,
  fetchQueryData,
};

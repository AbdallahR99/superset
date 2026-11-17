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
import { fetchQueryData } from '@apache-superset/widgets/chartData';
import { views } from 'src/core/views';
import { notifyLocationChanged } from 'src/core/navigation';
import { store as reduxStore } from 'src/views/store';
import { dashboardInfoChanged } from 'src/dashboard/actions/dashboardInfo';
import { dashboard } from '.';
import { isContainerType } from './DashboardProvider';
import { DASHBOARD_WIDGETS_LOCATION } from './resolveWidgetView';
import { provider } from './store';

jest.mock('@apache-superset/widgets/chartData', () => ({
  fetchQueryData: jest.fn().mockResolvedValue({ columns: [], rows: [] }),
}));

const query = fetchQueryData as jest.MockedFunction<typeof fetchQueryData>;

const BINDING = { datasetId: 7, metrics: ['count'] };

/** A filter widget's published selection, as the built-in filter emits it. */
const selection = (column: string, value: string, datasource = 7) => ({
  resolved: { datasource, column, operator: 'IN', value: [value] },
});

const adhoc = (column: string, value: string) => ({
  expressionType: 'SIMPLE',
  subject: column,
  clause: 'WHERE',
  operator: 'IN',
  comparator: [value],
});

beforeEach(() => {
  provider.reset();
  query.mockClear();
});

test('importing the dashboard API registers no widget view and no container type', () => {
  // The API is in the application's main bundle; what draws a dashboard is
  // in the Dashboard v2 page's own chunk and registers itself from there.
  expect(views.getViews(DASHBOARD_WIDGETS_LOCATION) ?? []).toEqual([]);
  expect(isContainerType('tabs')).toBe(false);
  expect(isContainerType('filter.bar')).toBe(false);
  // The root's own type is not something that is registered.
  expect(isContainerType('grid')).toBe(true);
});

test('fetchQueryData without a node id runs the binding as given and passes the signal on', async () => {
  const filter = provider.addWidget('root', 0, { type: 'filter.select' });
  provider.emit(
    filter,
    dashboard.VALUE_CHANGED_EVENT,
    selection('gender', 'boy'),
  );
  const { signal } = new AbortController();

  await dashboard.fetchQueryData(BINDING, { signal });

  expect(query).toHaveBeenCalledWith(BINDING, { signal });
});

test('fetchQueryData for a node applies the filters on the dashboard that apply to it', async () => {
  const filter = provider.addWidget('root', 0, { type: 'filter.select' });
  const chart = provider.addWidget('root', 1, { type: 'echarts' });
  provider.emit(
    filter,
    dashboard.VALUE_CHANGED_EVENT,
    selection('gender', 'boy'),
  );
  // A filter on another dataset is not this widget's business.
  const other = provider.addWidget('root', 2, { type: 'filter.select' });
  provider.emit(
    other,
    dashboard.VALUE_CHANGED_EVENT,
    selection('platform', 'Wii', 99),
  );
  const { signal } = new AbortController();

  await dashboard.fetchQueryData(
    { ...BINDING, filters: [{ clause: 'WHERE', authored: true }] },
    { nodeId: chart, signal },
  );

  expect(query).toHaveBeenCalledWith(
    {
      ...BINDING,
      filters: [{ clause: 'WHERE', authored: true }, adhoc('gender', 'boy')],
    },
    { signal },
  );
});

test('fetchQueryData for a node never narrows the node by its own selection', async () => {
  const chart = provider.addWidget('root', 0, { type: 'echarts' });
  const sibling = provider.addWidget('root', 1, { type: 'echarts' });
  // A cross-filtering chart publishes the slice that was clicked.
  provider.emit(chart, dashboard.VALUE_CHANGED_EVENT, selection('name', 'Amy'));

  await dashboard.fetchQueryData(BINDING, { nodeId: chart });
  expect(query).toHaveBeenLastCalledWith(
    { ...BINDING, filters: [] },
    { signal: undefined },
  );

  // The chart beside it is narrowed by that same selection.
  await dashboard.fetchQueryData(BINDING, { nodeId: sibling });
  expect(query).toHaveBeenLastCalledWith(
    { ...BINDING, filters: [adhoc('name', 'Amy')] },
    { signal: undefined },
  );
});

test('a source that was forgotten no longer narrows anyone', async () => {
  const chart = provider.addWidget('root', 0, { type: 'echarts' });
  const extensionWidget = provider.createSourceId();
  provider.emit(
    extensionWidget,
    dashboard.VALUE_CHANGED_EVENT,
    selection('gender', 'girl'),
  );

  await dashboard.fetchQueryData(BINDING, { nodeId: chart });
  expect(query).toHaveBeenLastCalledWith(
    { ...BINDING, filters: [adhoc('gender', 'girl')] },
    { signal: undefined },
  );

  provider.forget(extensionWidget);

  await dashboard.fetchQueryData(BINDING, { nodeId: chart });
  expect(query).toHaveBeenLastCalledWith(
    { ...BINDING, filters: [] },
    { signal: undefined },
  );
});

test('a saved Dashboard v2 does not report the classic dashboard that was open before it', () => {
  notifyLocationChanged('/dashboard/42/');
  reduxStore.dispatch(dashboardInfoChanged({ id: 42 }));
  expect(dashboard.getDashboardId()).toBe(42);

  notifyLocationChanged('/dashboard/v2/7/');

  expect(dashboard.getDashboardId()).toBeUndefined();
});

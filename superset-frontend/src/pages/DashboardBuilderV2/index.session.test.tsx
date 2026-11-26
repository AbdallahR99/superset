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
import fetchMock from 'fetch-mock';
import { MemoryRouter, Route, Switch, useHistory } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { act, render, screen, waitFor } from 'spec/helpers/testing-library';
import DashboardProvider from 'src/core/dashboard/DashboardProvider';
import type { DocumentNode } from 'src/core/dashboard/DashboardProvider';
import { dashboardSession } from 'src/core/dashboard/session';
import { registerBuiltInWidgets } from 'src/core/dashboard/registerBuiltInWidgets';
import DashboardBuilderV2 from '.';

// The page registers the built-in widgets itself, but only where the
// feature flag is on (see its own module), and no flag is set here.
registerBuiltInWidgets();

const provider = DashboardProvider.getInstance();
const originalLanguage = document.documentElement.lang;

const NEW = '/dashboard/v2/new/';
const pathOf = (id: number | string): string => `/dashboard/v2/${id}/`;

const documentOf = (...markdown: string[]): Record<string, DocumentNode> => ({
  root: { type: 'grid', children: markdown },
  ...Object.fromEntries(
    markdown.map(id => [id, { type: 'markdown', props: { content: id } }]),
  ),
});

const row = (
  id: number,
  revision: number,
  nodes: Record<string, DocumentNode> = documentOf(),
) => ({
  id,
  uuid: `uuid-${id}`,
  dashboard_title: `Dashboard ${id}`,
  revision,
  document: { version: 1, nodes },
  embedded: null,
});

/**
 * The answer to a create that made the row: `201`, as the API gives it. A
 * `200` to a create means something else (a repeat of one the server already
 * has), so the status is part of what is being answered here.
 */
const created = (id: number) => ({
  status: 201,
  body: { id, result: row(id, 1) },
});

type RouterHistory = ReturnType<typeof useHistory>;

/**
 * The page under the same routing it has in the app: a `Switch` of keyed
 * routes, where the unsaved route and the saved one are two different
 * routes. Moving between those two therefore unmounts the page and mounts
 * it again, which is the part of the first-save transition that is easy to
 * get wrong and impossible to see with a single route.
 *
 * `MemoryRouter` rather than a history made here, so the history is the
 * router's own kind, the one `history.block` behaves on as it does in the
 * app.
 */
const renderAt = (path: string, direction?: 'ltr' | 'rtl'): RouterHistory => {
  const captured: { history?: RouterHistory } = {};
  const Capture = () => {
    captured.history = useHistory();
    return null;
  };
  render(
    <MemoryRouter initialEntries={[path]}>
      <Capture />
      <Switch>
        <Route path={NEW} key={NEW}>
          <DashboardBuilderV2 />
        </Route>
        <Route path="/dashboard/v2/:dashboardId/" key="saved">
          <DashboardBuilderV2 />
        </Route>
        <Route path="/elsewhere/" key="elsewhere">
          <div data-test="elsewhere" />
        </Route>
      </Switch>
    </MemoryRouter>,
    { useRedux: true, direction },
  );
  if (!captured.history) throw new Error('the router did not render');
  return captured.history;
};

const requestsTo = (method: string): number =>
  fetchMock.callHistory
    .calls()
    .filter(
      call =>
        String(call.options.method).toUpperCase() === method.toUpperCase(),
    ).length;

beforeEach(() => {
  provider.reset();
  dashboardSession.reset();
  fetchMock.clearHistory().removeRoutes();
  // The editor panel's own lookups; none of them is what is under test.
  fetchMock.get('glob:*/api/v1/widgets/types*', { result: [] });
  fetchMock.get('glob:*/api/v1/theme/*', { result: [] });
});

afterEach(() => {
  fetchMock.clearHistory().removeRoutes();
  document.documentElement.lang = originalLanguage;
});

test('a localized dashboard shows translated names in view and canonical names in edit', async () => {
  document.documentElement.lang = 'ar-SA';
  const nodes: Record<string, DocumentNode> = {
    root: {
      type: 'grid',
      children: ['widget_1'],
      props: {
        nxtbiLocalization: {
          sourceLocale: 'en',
          title: { source: 'Dashboard 5', translations: { ar: 'المبيعات' } },
          widgets: {
            widget_1: {
              source: 'Net  revenue',
              translations: { ar: 'صافي الإيرادات' },
            },
          },
        },
      },
    },
    widget_1: { type: 'ag-grid-table', props: { label: 'Net  revenue' } },
  };
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', {
    result: { ...row(5, 2, nodes), can_edit: true },
  });

  renderAt(pathOf(5), 'rtl');

  expect(await screen.findByTestId('static-grid')).toBeInTheDocument();
  expect(screen.getByTestId('canvas').closest('[dir]')).toHaveAttribute(
    'dir',
    'rtl',
  );
  expect(screen.getByTestId('header-title')).toHaveTextContent('المبيعات');
  expect(screen.getByText('صافي الإيرادات')).toBeInTheDocument();
  expect(screen.queryByTestId('editor-panel')).not.toBeInTheDocument();
  expect(provider.getNode('widget_1')?.props?.label).toBe('Net  revenue');

  await userEvent.click(screen.getByTestId('header-toggle-edit'));

  expect(screen.getByTestId('editor-panel')).toBeInTheDocument();
  expect(screen.getByTestId('header-title')).toHaveValue('Dashboard 5');
  expect(screen.getByText('Net revenue')).toBeInTheDocument();
  act(() => {
    provider.updateProps('widget_1', { label: 'Net revenue' });
    provider.updateProps('root', { title: 'Executive dashboard' });
  });

  await userEvent.click(screen.getByTestId('header-toggle-edit'));

  expect(screen.getByText('Net revenue')).toBeInTheDocument();
  expect(screen.getByTestId('header-title')).toHaveTextContent(
    'Executive dashboard',
  );
  expect(screen.queryByText('صافي الإيرادات')).not.toBeInTheDocument();
  expect(requestsTo('PUT')).toBe(0);
});

test('a saved dashboard shows a spinner, not an editable canvas, until it has loaded', async () => {
  let respond: (value: unknown) => void = () => {};
  fetchMock.get(
    'glob:*/api/v1/dashboard_v2/5',
    new Promise(resolve => {
      respond = resolve;
    }),
  );

  renderAt(pathOf(5));

  expect(screen.getByTestId('dashboard-loading')).toBeInTheDocument();
  expect(screen.queryByTestId('canvas')).not.toBeInTheDocument();
  expect(screen.queryByTestId('editor-panel')).not.toBeInTheDocument();
  expect(screen.getByTestId('header-save')).toBeDisabled();

  await act(async () => {
    respond({ result: row(5, 2, documentOf('a')) });
  });

  expect(await screen.findByTestId('canvas')).toBeInTheDocument();
  expect(provider.getRoot().children).toEqual(['a']);
  expect(screen.getByTestId('header-save')).toBeEnabled();
  expect(screen.getByTestId('header-title')).toHaveValue('Dashboard 5');
});

test('a dashboard that fails to load says why, offers a retry, and cannot be saved over', async () => {
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', 404, { name: 'missing' });

  renderAt(pathOf(5));

  expect(await screen.findByTestId('dashboard-load-error')).toHaveTextContent(
    'This dashboard does not exist.',
  );
  expect(screen.queryByTestId('canvas')).not.toBeInTheDocument();
  expect(screen.getByTestId('header-save')).toBeDisabled();

  fetchMock.removeRoute('missing');
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', {
    result: row(5, 1, documentOf('a')),
  });
  await userEvent.click(screen.getByTestId('dashboard-load-retry'));

  expect(await screen.findByTestId('canvas')).toBeInTheDocument();
  expect(provider.getRoot().children).toEqual(['a']);
});

test('opening the new-dashboard route after another dashboard starts blank', async () => {
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', {
    result: row(5, 1, documentOf('a')),
  });
  const history = renderAt(pathOf(5));
  await screen.findByTestId('canvas');
  expect(provider.getRoot().children).toEqual(['a']);

  act(() => history.push(NEW));

  await waitFor(() => expect(provider.getRoot().children).toEqual([]));
  expect(dashboardSession.getState().dashboardId).toBeUndefined();
});

test('going from one saved dashboard to another never shows or saves the first under the second', async () => {
  let respond: (value: unknown) => void = () => {};
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', {
    result: row(5, 1, documentOf('five')),
  });
  fetchMock.get(
    'glob:*/api/v1/dashboard_v2/6',
    new Promise(resolve => {
      respond = resolve;
    }),
  );
  const history = renderAt(pathOf(5));
  await screen.findByTestId('canvas');

  act(() => history.push(pathOf(6)));

  // Until 6 answers there is no tree of 5 left to be looked at or saved.
  expect(await screen.findByTestId('dashboard-loading')).toBeInTheDocument();
  expect(provider.getNode('five')).toBeUndefined();
  expect(screen.getByTestId('header-save')).toBeDisabled();

  await act(async () => {
    respond({ result: row(6, 4, documentOf('six')) });
  });

  await waitFor(() => expect(provider.getRoot().children).toEqual(['six']));
  expect(dashboardSession.getState()).toMatchObject({
    dashboardId: 6,
    baseRevision: 4,
  });
});

test('the first save creates once, moves to the new id, and keeps the tree instead of reloading it', async () => {
  fetchMock.post('glob:*/api/v1/dashboard_v2/', created(7));
  const history = renderAt(NEW);
  await userEvent.click(await screen.findByTestId('palette-markdown'));
  const [placed] = provider.getRoot().children ?? [];
  expect(screen.getByTestId('header-unsaved')).toBeInTheDocument();

  await userEvent.click(screen.getByTestId('header-save'));

  await waitFor(() => expect(history.location.pathname).toBe(pathOf(7)));
  // Replaced, so Back does not return to a second blank dashboard.
  expect(history.length).toBe(1);
  expect(requestsTo('POST')).toBe(1);
  // No read of the dashboard just written: the tree on screen is that one.
  expect(requestsTo('GET')).toBe(
    fetchMock.callHistory.calls('glob:*/api/v1/widgets/types*').length +
      fetchMock.callHistory.calls('glob:*/api/v1/theme/*').length,
  );
  expect(provider.getRoot().children).toEqual([placed]);
  expect(provider.getSelection()).toBe(placed);
  expect(screen.queryByTestId('header-unsaved')).not.toBeInTheDocument();
  expect(dashboardSession.getState()).toMatchObject({
    dashboardId: 7,
    baseRevision: 1,
  });
});

test('the save after the first one is an update based on the revision the create returned', async () => {
  fetchMock.post('glob:*/api/v1/dashboard_v2/', created(7));
  fetchMock.put('glob:*/api/v1/dashboard_v2/7', { id: 7, result: row(7, 2) });
  const history = renderAt(NEW);
  await userEvent.click(await screen.findByTestId('palette-markdown'));
  await userEvent.click(screen.getByTestId('header-save'));
  await waitFor(() => expect(history.location.pathname).toBe(pathOf(7)));

  act(() => {
    provider.addWidget('root', 0, { type: 'markdown' });
  });
  await userEvent.click(screen.getByTestId('header-save'));

  await waitFor(() => expect(requestsTo('PUT')).toBe(1));
  const put = fetchMock.callHistory.lastCall('glob:*/api/v1/dashboard_v2/7');
  expect(JSON.parse(put?.options.body as string)).toMatchObject({
    base_revision: 1,
  });
  expect(requestsTo('POST')).toBe(1);
  await waitFor(() => expect(dashboardSession.getState().baseRevision).toBe(2));
});

test('a refused save opens the conflict dialog and overwrites only when asked to', async () => {
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', {
    result: row(5, 3, documentOf('a')),
  });
  fetchMock.put(
    'glob:*/api/v1/dashboard_v2/5',
    { status: 409, body: { message: 'changed', current_revision: 4 } },
    { name: 'refuse' },
  );
  renderAt(pathOf(5));
  await screen.findByTestId('canvas');
  act(() => {
    provider.addWidget('root', 0, { type: 'markdown' });
  });

  await userEvent.click(screen.getByTestId('header-save'));

  expect(await screen.findByTestId('conflict-dialog')).toBeInTheDocument();
  expect(requestsTo('PUT')).toBe(1);

  fetchMock.removeRoute('refuse');
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', { id: 5, result: row(5, 5) });
  await userEvent.click(screen.getByTestId('conflict-overwrite'));

  await waitFor(() => expect(requestsTo('PUT')).toBe(2));
  const put = fetchMock.callHistory.lastCall('glob:*/api/v1/dashboard_v2/5');
  // Deliberately on top of what the server said it holds.
  expect(JSON.parse(put?.options.body as string)).toMatchObject({
    base_revision: 4,
  });
  await waitFor(() =>
    expect(screen.queryByTestId('conflict-dialog')).not.toBeInTheDocument(),
  );
  expect(dashboardSession.getState().baseRevision).toBe(5);
});

test('choosing to reload after a conflict replaces the tree with the saved one', async () => {
  fetchMock.get(
    'glob:*/api/v1/dashboard_v2/5',
    { result: row(5, 3, documentOf('a')) },
    { name: 'first-read' },
  );
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', {
    status: 409,
    body: { message: 'changed', current_revision: 4 },
  });
  renderAt(pathOf(5));
  await screen.findByTestId('canvas');
  act(() => {
    provider.addWidget('root', 0, { type: 'markdown' });
  });
  await userEvent.click(screen.getByTestId('header-save'));
  await screen.findByTestId('conflict-dialog');

  fetchMock.removeRoute('first-read');
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', {
    result: row(5, 4, documentOf('theirs')),
  });
  await userEvent.click(screen.getByTestId('conflict-reload'));

  await waitFor(() => expect(provider.getRoot().children).toEqual(['theirs']));
  expect(requestsTo('PUT')).toBe(1);
  expect(dashboardSession.getState().baseRevision).toBe(4);
});

test('keeping on editing after a conflict closes the dialog and writes nothing', async () => {
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', {
    result: row(5, 3, documentOf('a')),
  });
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', {
    status: 409,
    body: { message: 'changed', current_revision: 4 },
  });
  renderAt(pathOf(5));
  await screen.findByTestId('canvas');
  let mine = '';
  act(() => {
    mine = provider.addWidget('root', 0, { type: 'markdown' });
  });
  await userEvent.click(screen.getByTestId('header-save'));
  await screen.findByTestId('conflict-dialog');

  await userEvent.click(screen.getByTestId('conflict-keep-editing'));

  await waitFor(() =>
    expect(screen.queryByTestId('conflict-dialog')).not.toBeInTheDocument(),
  );
  expect(requestsTo('PUT')).toBe(1);
  expect(provider.getRoot().children).toContain(mine);
  expect(screen.getByTestId('header-unsaved')).toBeInTheDocument();
});

test('leaving with unsaved changes asks first, and discarding lets the navigation through', async () => {
  const history = renderAt(NEW);
  await userEvent.click(await screen.findByTestId('palette-markdown'));

  act(() => history.push('/elsewhere/'));

  expect(
    await screen.findByText('Save changes to this dashboard?'),
  ).toBeInTheDocument();
  expect(history.location.pathname).toBe(NEW);

  await userEvent.click(screen.getByRole('button', { name: 'Discard' }));

  expect(await screen.findByTestId('elsewhere')).toBeInTheDocument();
});

test('leaving with nothing changed does not ask', async () => {
  const history = renderAt(NEW);
  await screen.findByTestId('canvas');

  act(() => history.push('/elsewhere/'));

  expect(await screen.findByTestId('elsewhere')).toBeInTheDocument();
});

test('closing the tab with unsaved changes is interrupted by the browser prompt', async () => {
  renderAt(NEW);
  await userEvent.click(await screen.findByTestId('palette-markdown'));

  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);

  expect(event.defaultPrevented).toBe(true);
});

test('a load answered after the page was left changes nothing', async () => {
  let respond: (value: unknown) => void = () => {};
  fetchMock.get(
    'glob:*/api/v1/dashboard_v2/5',
    new Promise(resolve => {
      respond = resolve;
    }),
  );
  const history = renderAt(pathOf(5));
  await screen.findByTestId('dashboard-loading');
  const errors = jest.spyOn(console, 'error').mockImplementation(() => {});

  act(() => history.push('/elsewhere/'));
  await screen.findByTestId('elsewhere');
  await act(async () => {
    respond({ result: row(5, 2, documentOf('a')) });
  });

  expect(provider.getRoot().children).toEqual([]);
  expect(dashboardSession.getState().status).toBe('loading');
  expect(errors).not.toHaveBeenCalled();
  errors.mockRestore();
});

test('a save refused for one widget selects that widget and keeps the edits', async () => {
  renderAt(NEW);
  await userEvent.click(await screen.findByTestId('palette-markdown'));
  const [first] = provider.getRoot().children ?? [];
  let second = '';
  act(() => {
    second = provider.addWidget('root', 1, { type: 'markdown' });
    provider.setSelection(first);
  });
  fetchMock.post('glob:*/api/v1/dashboard_v2/', {
    status: 422,
    body: {
      message: 'Widget props failed validation.',
      errors: { [second]: [{ loc: ['content'], message: 'Required' }] },
    },
  });

  await userEvent.click(screen.getByTestId('header-save'));

  await waitFor(() => expect(provider.getSelection()).toBe(second));
  expect(dashboardSession.getState().dashboardId).toBeUndefined();
  expect(screen.getByTestId('header-unsaved')).toBeInTheDocument();
  await waitFor(() => expect(screen.getByTestId('header-save')).toBeEnabled());
  // The reason is on the widget it is about, and on no other.
  expect(
    await screen.findByTestId(`widget-save-error-${second}`),
  ).toHaveTextContent('content: Required');
  expect(
    screen.queryByTestId(`widget-save-error-${first}`),
  ).not.toBeInTheDocument();
});

test('an ECharts option or column definition refused on save is said on its widget, and goes once that widget is edited or removed', async () => {
  renderAt(NEW);
  await screen.findByTestId('palette-markdown');
  let chart = '';
  let table = '';
  act(() => {
    chart = provider.addWidget('root', 0, {
      type: 'echarts',
      props: { echartsOptions: { graphic: { elements: [] } } },
    });
    table = provider.addWidget('root', 1, {
      type: 'ag-grid-table',
      props: { columnDefs: [{ field: 'a', cellRenderer: 'x' }] },
    });
  });
  fetchMock.post('glob:*/api/v1/dashboard_v2/', {
    status: 422,
    body: {
      message: 'Widget props failed validation.',
      errors: {
        [chart]: [
          {
            loc: ['echartsOptions'],
            message:
              'Value error, echartsOptions.graphic is not an allowed ECharts option component',
          },
        ],
        [table]: [
          {
            loc: ['columnDefs'],
            message:
              'Value error, columnDefs[0].cellRenderer is not an allowed column setting',
          },
        ],
      },
    },
  });

  await userEvent.click(screen.getByTestId('header-save'));

  expect(
    await screen.findByTestId(`widget-save-error-${chart}`),
  ).toHaveTextContent(
    'Not saved: echartsOptions: Value error, echartsOptions.graphic is not an allowed ECharts option component',
  );
  expect(screen.getByTestId(`widget-save-error-${table}`)).toHaveTextContent(
    'Not saved: columnDefs: Value error, columnDefs[0].cellRenderer is not an allowed column setting',
  );
  // The first refused widget is selected, which is where it is fixed.
  await waitFor(() => expect(provider.getSelection()).toBe(chart));

  // Fixing one widget takes its own note away and leaves the other's.
  act(() => {
    provider.updateProps(chart, { echartsOptions: {} });
  });
  await waitFor(() =>
    expect(
      screen.queryByTestId(`widget-save-error-${chart}`),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getByTestId(`widget-save-error-${table}`)).toBeInTheDocument();

  act(() => {
    provider.removeWidget(table);
  });
  expect(dashboardSession.getState().nodeErrors).toEqual({});
});

test('a first save that went through is moved to its route even when the save that follows it is refused', async () => {
  let answerCreate: (value: unknown) => void = () => {};
  fetchMock.post(
    'glob:*/api/v1/dashboard_v2/',
    new Promise(resolve => {
      answerCreate = resolve;
    }),
  );
  fetchMock.put('glob:*/api/v1/dashboard_v2/7', {
    status: 422,
    body: { message: 'Widget props failed validation.' },
  });
  const history = renderAt(NEW);
  await userEvent.click(await screen.findByTestId('palette-markdown'));

  // Save, edit while the create is away, and save again: the second click
  // is folded into the first save as a follow-up update.
  await userEvent.click(screen.getByTestId('header-save'));
  act(() => {
    provider.addWidget('root', 1, { type: 'markdown' });
  });
  act(() => {
    dashboardSession.save();
  });
  await act(async () => {
    answerCreate(created(7));
  });

  // The update was refused, but the dashboard exists: the page is at its
  // address, not at the one a refresh would open a blank dashboard from.
  await waitFor(() => expect(history.location.pathname).toBe(pathOf(7)));
  expect(requestsTo('POST')).toBe(1);
  expect(requestsTo('PUT')).toBe(1);
  expect(dashboardSession.getState()).toMatchObject({
    dashboardId: 7,
    baseRevision: 1,
  });
  expect(screen.getByTestId('header-unsaved')).toBeInTheDocument();
});

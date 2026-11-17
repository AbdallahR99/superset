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
import { StrictMode, useEffect, useState, type ReactNode } from 'react';
import { dashboard as dashboardApi } from '@apache-superset/core';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from 'spec/helpers/testing-library';
import { WidgetBusContext, createWidgetBus } from '../bus';
import { WidgetDataClientContext } from '../dataClient';
import type {
  QueryDataResult,
  WidgetBus,
  WidgetDataClient,
  WidgetEvent,
} from '../types';
import { createExtensionHost, type ExtensionHost } from './extensionHost';
import {
  ExtensionWidgetLoaderContext,
  type ExtensionWidgetLoader,
} from './extensionLoader';
import { Widget } from './Widget';

const TYPE = 'extensions.acme.widgets.chart';
const EXTENSION = { id: 'acme.widgets', name: 'widgets' };
const FILTER_CA = {
  selection: ['CA'],
  resolved: { column: 'state', operator: 'IN', value: ['CA'], datasource: 7 },
};

type Core = ReturnType<ExtensionHost['createCore']>;

/**
 * Stands in for an extension's module evaluated against `core`: all it sees
 * is `@apache-superset/core`. `passNodeId` is the widget saying who asks.
 */
function registerChart(core: Core, passNodeId = true) {
  const heard: WidgetEvent[] = [];

  function ExtensionChart({ nodeId }: { nodeId: string }) {
    const node = core.dashboard.getNode(nodeId);
    const label = String(node?.props?.label ?? '');
    const [rows, setRows] = useState<number | string>();

    useEffect(() => {
      const subscription = core.dashboard.on(
        dashboardApi.VALUE_CHANGED_EVENT,
        event => heard.push(event),
      );
      core.dashboard
        .fetchQueryData(
          { datasetId: 7, metrics: ['count'] },
          passNodeId ? { nodeId } : undefined,
        )
        .then(
          (result: QueryDataResult) => setRows(result.rows.length),
          (error: Error) => setRows(error.message),
        );
      return () => subscription.dispose();
    }, [nodeId]);

    return (
      <button
        type="button"
        data-test={`ext-${nodeId}`}
        onClick={() =>
          core.dashboard.emit(
            nodeId,
            dashboardApi.VALUE_CHANGED_EVENT,
            FILTER_CA,
          )
        }
      >
        {label}:{rows ?? '-'}
      </button>
    );
  }

  core.views.registerView(
    { id: TYPE, name: 'Chart', description: '' },
    'dashboard.widgets',
    ExtensionChart,
  );
  return heard;
}

interface Page {
  host: ExtensionHost;
  core: Core;
  heard: WidgetEvent[];
  bus: WidgetBus;
  client: WidgetDataClient;
  fetchData: jest.Mock;
  loader: ExtensionWidgetLoader;
}

/** Everything one provider owns, as `SupersetProvider` would wire it. */
function createPage(rows: number, passNodeId = true): Page {
  const host = createExtensionHost();
  const core = host.createCore(EXTENSION);
  const heard = registerChart(core, passNodeId);
  const fetchData = jest.fn(async () => ({
    columns: ['count'],
    rows: Array.from({ length: rows }, (_unused, index) => ({ count: index })),
  }));
  return {
    host,
    core,
    heard,
    bus: createWidgetBus(),
    client: { fetchData, fetchValues: jest.fn() },
    fetchData,
    loader: async type => {
      const component = host.getComponent(type);
      if (!component) throw new Error(`no ${type}`);
      return component;
    },
  };
}

function PageProviders({
  page,
  children,
}: {
  page: Page;
  children: ReactNode;
}) {
  return (
    <WidgetBusContext.Provider value={page.bus}>
      <WidgetDataClientContext.Provider value={page.client}>
        <ExtensionWidgetLoaderContext.Provider value={page.loader}>
          {children}
        </ExtensionWidgetLoaderContext.Provider>
      </WidgetDataClientContext.Provider>
    </WidgetBusContext.Provider>
  );
}

test('an extension widget reads its props from the node the host rendered', async () => {
  const page = createPage(2);
  render(
    <PageProviders page={page}>
      <Widget type={TYPE} props={{ label: 'Sales' }} instanceId="w1" />
    </PageProviders>,
  );

  expect(await screen.findByText('Sales:2')).toBeInTheDocument();
  expect(page.core.dashboard.getRoot().children).toEqual(['w1']);
});

test('its query runs through the embedded data client, as an inline widget', async () => {
  const page = createPage(2);
  render(
    <PageProviders page={page}>
      <Widget type={TYPE} props={{ label: 'Sales' }} instanceId="w1" />
    </PageProviders>,
  );

  await screen.findByText('Sales:2');
  expect(page.fetchData).toHaveBeenCalledWith({
    instanceId: 'w1',
    widget: {
      type: 'echarts',
      props: { dataBinding: { datasetId: 7, metrics: ['count'] } },
    },
    filters: [],
    signal: undefined,
  });
});

test('a filter on the page narrows its query', async () => {
  const page = createPage(2);
  page.bus.emit('host:state', dashboardApi.VALUE_CHANGED_EVENT, FILTER_CA);

  render(
    <PageProviders page={page}>
      <Widget type={TYPE} props={{ label: 'Sales' }} instanceId="w1" />
    </PageProviders>,
  );

  await screen.findByText('Sales:2');
  expect(page.fetchData).toHaveBeenCalledWith(
    expect.objectContaining({ filters: [FILTER_CA.resolved] }),
  );
});

test('what it emits reaches the page bus under its own instance id', async () => {
  const page = createPage(2);
  render(
    <PageProviders page={page}>
      <Widget type={TYPE} props={{ label: 'Sales' }} instanceId="w1" />
    </PageProviders>,
  );

  fireEvent.click(await screen.findByTestId('ext-w1'));

  expect(page.bus.getValue('w1', dashboardApi.VALUE_CHANGED_EVENT)).toEqual(
    FILTER_CA,
  );
  expect(page.core.dashboard.getValue('w1', 'valueChanged')).toEqual(FILTER_CA);
});

test('each of several extension widgets queries as itself, not as whichever rendered last', async () => {
  const page = createPage(1);
  // The first widget cross-filters; only the other one must be narrowed by it.
  page.bus.emit('w1', dashboardApi.VALUE_CHANGED_EVENT, FILTER_CA);

  render(
    <PageProviders page={page}>
      <Widget type={TYPE} props={{ label: 'One' }} instanceId="w1" />
      <Widget type={TYPE} props={{ label: 'Two' }} instanceId="w2" />
    </PageProviders>,
  );

  await screen.findByText('One:1');
  await screen.findByText('Two:1');
  const requests = page.fetchData.mock.calls.map(([request]) => [
    request.instanceId,
    request.filters,
  ]);
  expect(requests).toEqual(
    expect.arrayContaining([
      ['w1', []],
      ['w2', [FILTER_CA.resolved]],
    ]),
  );
  expect(requests).toHaveLength(2);
});

test('without a node id the host never guesses who is asking', async () => {
  const page = createPage(1, false);
  page.bus.emit('w1', dashboardApi.VALUE_CHANGED_EVENT, FILTER_CA);

  render(
    <PageProviders page={page}>
      <Widget type={TYPE} props={{ label: 'One' }} instanceId="w1" />
      <Widget type={TYPE} props={{ label: 'Two' }} instanceId="w2" />
    </PageProviders>,
  );

  await screen.findByText('One:1');
  await screen.findByText('Two:1');
  // Both queries are attributed to no widget: the same filters for both,
  // rather than one of them silently treated as the other.
  page.fetchData.mock.calls.forEach(([request]) => {
    expect(request.instanceId).toBe('');
    expect(request.filters).toEqual([FILTER_CA.resolved]);
  });
});

test('two providers give one extension two worlds that cannot reach each other', async () => {
  const left = createPage(3);
  const right = createPage(5);
  left.bus.emit('host:state', dashboardApi.VALUE_CHANGED_EVENT, FILTER_CA);

  render(
    <>
      <PageProviders page={left}>
        <Widget type={TYPE} props={{ label: 'Left' }} instanceId="same-id" />
      </PageProviders>
      <PageProviders page={right}>
        <Widget type={TYPE} props={{ label: 'Right' }} instanceId="same-id" />
      </PageProviders>
    </>,
  );

  // Data: each ran once, with its own provider's client and filters, although
  // both widgets carry the same instance id.
  expect(await screen.findByText('Left:3')).toBeInTheDocument();
  expect(await screen.findByText('Right:5')).toBeInTheDocument();
  expect(left.fetchData).toHaveBeenCalledTimes(1);
  expect(right.fetchData).toHaveBeenCalledTimes(1);
  expect(left.fetchData.mock.calls[0][0].filters).toEqual([FILTER_CA.resolved]);
  expect(right.fetchData.mock.calls[0][0].filters).toEqual([]);

  // Props: the same node id resolves to a different node in each host.
  expect(left.core.dashboard.getNode('same-id')?.props).toEqual({
    label: 'Left',
  });
  expect(right.core.dashboard.getNode('same-id')?.props).toEqual({
    label: 'Right',
  });

  // Events: an emit on the right is heard on the right only.
  left.heard.length = 0;
  right.heard.length = 0;
  fireEvent.click(screen.getByText('Right:5'));
  expect(right.heard).toHaveLength(1);
  expect(left.heard).toHaveLength(0);
  expect(
    left.bus.getValue('same-id', dashboardApi.VALUE_CHANGED_EVENT),
  ).toBeUndefined();

  // Overrides written through one host stay in it.
  act(() => right.core.dashboard.updateProps('same-id', { label: 'Renamed' }));
  expect(await screen.findByText('Renamed:5')).toBeInTheDocument();
  expect(screen.getByText('Left:3')).toBeInTheDocument();
});

test('a widget type registered with one host is unknown to another', async () => {
  const withExtension = createPage(1);
  const without = createPage(1);
  without.host.dispose();

  render(
    <PageProviders page={without}>
      <Widget type={TYPE} props={{}} instanceId="w1" />
    </PageProviders>,
  );

  expect(await screen.findByText(`no ${TYPE}`)).toBeInTheDocument();
  expect(withExtension.host.getComponent(TYPE)).toBeDefined();
});

test('unmounting removes the node and the listeners it held on the bus', async () => {
  const page = createPage(2);
  const { unmount } = render(
    <PageProviders page={page}>
      <Widget type={TYPE} props={{ label: 'Sales' }} instanceId="w1" />
    </PageProviders>,
  );
  await screen.findByText('Sales:2');
  page.heard.length = 0;

  unmount();

  expect(page.core.dashboard.getNode('w1')).toBeUndefined();
  expect(page.core.dashboard.getRoot().children).toEqual([]);
  page.bus.emit('other', dashboardApi.VALUE_CHANGED_EVENT, FILTER_CA);
  expect(page.heard).toHaveLength(0);
  await expect(
    page.core.dashboard.fetchQueryData({ datasetId: 7, metrics: [] }),
  ).rejects.toThrow('only available to a rendered widget');
});

test('a module-level listener follows the bus while a widget is mounted, and lets go after', async () => {
  const page = createPage(1);
  const moduleHeard: string[] = [];
  page.core.dashboard.on(dashboardApi.VALUE_CHANGED_EVENT, event =>
    moduleHeard.push(event.nodeId),
  );
  // Registered before anything rendered: nothing to listen to yet.
  page.bus.emit('early', dashboardApi.VALUE_CHANGED_EVENT, FILTER_CA);
  expect(moduleHeard).toEqual([]);

  const { unmount } = render(
    <PageProviders page={page}>
      <Widget type={TYPE} props={{ label: 'Sales' }} instanceId="w1" />
    </PageProviders>,
  );
  await screen.findByText('Sales:1');
  act(() =>
    page.bus.emit('during', dashboardApi.VALUE_CHANGED_EVENT, FILTER_CA),
  );
  unmount();
  page.bus.emit('after', dashboardApi.VALUE_CHANGED_EVENT, FILTER_CA);

  expect(moduleHeard).toEqual(['during']);
});

test('the node is there for the view under strict mode, which replays effects', async () => {
  const page = createPage(4);
  render(
    <StrictMode>
      <PageProviders page={page}>
        <Widget type={TYPE} props={{ label: 'Strict' }} instanceId="w1" />
      </PageProviders>
    </StrictMode>,
  );

  expect(await screen.findByText('Strict:4')).toBeInTheDocument();
  await waitFor(() =>
    expect(page.core.dashboard.getNode('w1')?.props).toEqual({
      label: 'Strict',
    }),
  );
});

test('what an embedded page cannot do says so, and other contributions are tolerated', () => {
  const { core } = createPage(1);

  expect(() =>
    core.dashboard.addWidget('root', 0, { type: 'markdown' }),
  ).toThrow('dashboard.addWidget is not available to an embedded widget.');
  expect(
    core.views.registerView(
      { id: 'acme.panel', name: 'Panel', description: '' },
      'sqllab.panels',
      () => null,
    ),
  ).toHaveProperty('dispose');
  expect(core.views.getViews('dashboard.widgets')).toHaveLength(1);
  expect(core.extensions.getExtension('acme.widgets')).toEqual(EXTENSION);
  expect(core.extensions.getExtension('other')).toBeUndefined();
});

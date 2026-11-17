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
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from 'spec/helpers/testing-library';
import DashboardProvider from './DashboardProvider';
import EmbedWidgetModal, { EMBED_WIDGET_ID_PROP } from './EmbedWidgetModal';

const provider = DashboardProvider.getInstance();

const WIDGET_API = 'glob:*/api/v1/widget/';

const STORED = {
  root: { type: 'grid', children: ['node_1'] },
  node_1: { type: 'metric-tile', props: { label: 'Revenue' } },
};

/** A request to save the widget that answers only when the test says so. */
const pendingSave = () => {
  let answer: (value: unknown) => void = () => {};
  fetchMock.post(
    WIDGET_API,
    new Promise(resolve => {
      answer = resolve;
    }),
  );
  return (uuid: string) =>
    answer({ status: 201, body: { result: { uuid, widget_type: 'x' } } });
};

const mount = (nodeId = 'node_1') =>
  render(<EmbedWidgetModal nodeId={nodeId} show onHide={jest.fn()} />, {
    useRedux: true,
  });

const saveButton = () => screen.getByRole('button', { name: 'Save widget' });

const posts = (): number =>
  fetchMock.callHistory
    .calls()
    .filter(call => String(call.options.method).toUpperCase() === 'POST')
    .length;

beforeEach(() => {
  provider.reset();
  provider.loadDocument(STORED);
  fetchMock.clearHistory().removeRoutes();
});

afterEach(() => {
  fetchMock.clearHistory().removeRoutes();
});

test('saving writes the saved widget’s id onto the node it was saved from', async () => {
  const answer = pendingSave();
  mount();

  fireEvent.click(saveButton());
  await act(async () => {
    answer('uuid-1');
  });

  await waitFor(() =>
    expect(provider.getNode('node_1')?.props?.[EMBED_WIDGET_ID_PROP]).toBe(
      'uuid-1',
    ),
  );
});

test('two clicks before the first save answers create one saved widget, not two', async () => {
  const answer = pendingSave();
  mount();

  // Both in one tick: the second sees the same render the first did, where
  // nothing says a save is running yet.
  act(() => {
    const button = saveButton();
    fireEvent.click(button);
    fireEvent.click(button);
  });
  await waitFor(() => expect(posts()).toBeGreaterThan(0));
  await act(async () => {
    answer('uuid-1');
  });

  await waitFor(() =>
    expect(provider.getNode('node_1')?.props?.[EMBED_WIDGET_ID_PROP]).toBe(
      'uuid-1',
    ),
  );
  expect(posts()).toBe(1);
});

test('a save that answers after the dashboard was reloaded does not write into the reloaded copy', async () => {
  const answer = pendingSave();
  mount();

  fireEvent.click(saveButton());
  await waitFor(() => expect(posts()).toBe(1));
  // The same dashboard, loaded again: the same node id, a different tree.
  act(() => {
    provider.loadDocument(STORED);
  });
  const versionAfterReload = provider.getDocumentVersion();
  await act(async () => {
    answer('uuid-1');
  });
  await act(async () => {
    await Promise.resolve();
  });

  expect(provider.getNode('node_1')?.props).toEqual({ label: 'Revenue' });
  expect(provider.getDocumentVersion()).toBe(versionAfterReload);
});

test('a save that answers after another dashboard was opened does not write into its node of the same id', async () => {
  const answer = pendingSave();
  mount();

  fireEvent.click(saveButton());
  await waitFor(() => expect(posts()).toBe(1));
  act(() => {
    provider.loadDocument({
      root: { type: 'grid', children: ['node_1'] },
      node_1: { type: 'markdown', props: { content: 'Another dashboard' } },
    });
  });
  await act(async () => {
    answer('uuid-1');
  });
  await act(async () => {
    await Promise.resolve();
  });

  expect(provider.getNode('node_1')?.props).toEqual({
    content: 'Another dashboard',
  });
});

test('a refused save says why beside the widget, and can be tried again', async () => {
  fetchMock.post(WIDGET_API, {
    status: 403,
    body: { message: 'Custom SQL needs SQL Lab access.' },
  });
  mount();

  fireEvent.click(saveButton());

  expect(
    await screen.findByTestId('embed-widget-save-error'),
  ).toHaveTextContent('Custom SQL needs SQL Lab access.');
  expect(provider.getNode('node_1')?.props).toEqual({ label: 'Revenue' });

  // The refusal did not leave the guard set: another attempt is sent.
  fetchMock.removeRoutes();
  fetchMock.post(WIDGET_API, {
    status: 201,
    body: { result: { uuid: 'uuid-2', widget_type: 'metric-tile' } },
  });
  await waitFor(() => expect(saveButton()).toBeEnabled());
  fireEvent.click(saveButton());

  await waitFor(() =>
    expect(provider.getNode('node_1')?.props?.[EMBED_WIDGET_ID_PROP]).toBe(
      'uuid-2',
    ),
  );
  expect(
    screen.queryByTestId('embed-widget-save-error'),
  ).not.toBeInTheDocument();
});

test('an invalid widget is refused with the server’s own words', async () => {
  fetchMock.post(WIDGET_API, {
    status: 422,
    body: { message: 'rowLimit must be a positive integer.' },
  });
  mount();

  fireEvent.click(saveButton());

  expect(
    await screen.findByTestId('embed-widget-save-error'),
  ).toHaveTextContent('rowLimit must be a positive integer.');
});

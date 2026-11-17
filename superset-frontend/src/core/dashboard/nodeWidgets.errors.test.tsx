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
 * A data request the server refuses is said on the widget that made it, in
 * the server's own words, and on no other widget. Driven through the real
 * request path (`SupersetClient` over a mocked `fetch`), so what is checked
 * is what the author sees for a 403 or a 422, not what a mocked data
 * function was told to say.
 */
import fetchMock from 'fetch-mock';
import { render, screen, within } from 'spec/helpers/testing-library';
import DashboardProvider from './DashboardProvider';
import { registerBuiltInWidgets } from './registerBuiltInWidgets';
import WidgetView from './WidgetView';
import { __resetGridStackMock } from '../../../spec/__mocks__/gridstackMock';

jest.mock('echarts/core', () => ({
  __esModule: true,
  use: jest.fn(),
  init: jest.fn(() => ({
    setOption: jest.fn(),
    resize: jest.fn(),
    dispose: jest.fn(),
    on: jest.fn(),
  })),
}));

const provider = DashboardProvider.getInstance();

const DATA_API = 'glob:*/api/v1/chart/data*';

beforeAll(() => {
  registerBuiltInWidgets();
});

beforeEach(() => {
  provider.reset();
  __resetGridStackMock();
  fetchMock.clearHistory().removeRoutes();
});

afterEach(() => {
  fetchMock.clearHistory().removeRoutes();
});

const addChart = (datasetId: number): string =>
  provider.addWidget('root', 0, {
    type: 'echarts',
    props: {
      dataBinding: { datasetId, metrics: ['count'] },
      echartsOptions: { series: [{ type: 'bar' }] },
    },
  });

const contentOf = (id: string): HTMLElement =>
  screen.getByTestId(`widget-content-${id}`);

test('a query the author may not run is refused on the widget, with the server’s reason', async () => {
  fetchMock.post(DATA_API, {
    status: 403,
    body: { message: 'Custom SQL needs SQL Lab access.' },
  });
  const chart = addChart(7);
  const note = provider.addWidget('root', 1, {
    type: 'markdown',
    props: { content: 'A note' },
  });

  render(<WidgetView nodeId="root" />, { useRedux: true });

  expect(
    await within(contentOf(chart)).findByText(
      /Custom SQL needs SQL Lab access\./,
    ),
  ).toBeInTheDocument();
  expect(contentOf(note)).not.toHaveTextContent('Custom SQL');
});

test('an invalid query is refused on the widget, with what was wrong with it', async () => {
  fetchMock.post(DATA_API, {
    status: 422,
    body: { errors: [{ message: 'Column "revnue" does not exist.' }] },
  });
  const chart = addChart(7);

  render(<WidgetView nodeId="root" />, { useRedux: true });

  expect(
    await within(contentOf(chart)).findByText(
      /Column "revnue" does not exist\./,
    ),
  ).toBeInTheDocument();
});

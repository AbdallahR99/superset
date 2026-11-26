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
import { dashboard as dashboardApi } from '@apache-superset/core';
import {
  act,
  render,
  userEvent,
  waitFor,
  within,
} from 'spec/helpers/testing-library';
import {
  setupAGGridModules,
  type AgGridContainerElement,
} from '@superset-ui/core/components/ThemedAgGridReact';
import { WidgetBusContext, createWidgetBus } from '../bus';
import { WidgetDataClientContext } from '../dataClient';
import type { WidgetDataClient } from '../types';
import AgGridTableWidget from './AgGridTableWidget';

setupAGGridModules();

const props = {
  dataBinding: {
    datasetId: 2,
    dimensions: ['center'],
    metrics: ['rate'],
  },
  columnDefs: [
    { field: 'center', headerName: 'Service center', filter: true },
    { field: 'private_note', hide: true },
    {
      field: 'rate',
      headerName: 'Return rate',
      valueFormat: 'percent',
      valueFormatPrecision: 1,
    },
  ],
};

const response = {
  columns: ['center', 'rate', 'private_note'],
  rows: [
    { center: 'West Market', rate: 0.37, private_note: 'Hidden' },
    { center: 'North Market', rate: 0.18, private_note: 'Hidden' },
  ],
};

function renderTable(
  preferNativeTable: boolean,
  savedId?: string,
  fetchData: WidgetDataClient['fetchData'] = async () => response,
) {
  const client = { fetchData, fetchValues: jest.fn() };
  const bus = createWidgetBus();
  const widgetProps = {
    instanceId: 'table_1',
    props,
    savedId,
    preferNativeTable,
    accessibleTitle: 'Service center detail',
  };
  const rendered = render(
    <WidgetBusContext.Provider value={bus}>
      <WidgetDataClientContext.Provider value={client}>
        <AgGridTableWidget {...widgetProps} />
      </WidgetDataClientContext.Provider>
    </WidgetBusContext.Provider>,
  );
  return { ...rendered, bus };
}

test('presents a named native data table with headers and formatted values by default', async () => {
  const { findByRole, queryByRole } = renderTable(true);
  const table = await findByRole('table', { name: 'Service center detail' });

  expect(
    within(table).getByRole('columnheader', { name: 'Return rate' }),
  ).toHaveAttribute('scope', 'col');
  expect(
    within(table).getByRole('rowheader', { name: 'West Market' }),
  ).toHaveAttribute('scope', 'row');
  expect(
    within(table).getByRole('cell', { name: '37.0%' }),
  ).toBeInTheDocument();
  expect(within(table).queryByText('Hidden')).not.toBeInTheDocument();
  expect(queryByRole('grid')).not.toBeInTheDocument();
});

test('keeps grid sort and filter state when switching between views', async () => {
  const { container, findByRole, queryByRole } = renderTable(true);
  await userEvent.click(
    await findByRole('button', { name: 'Interactive grid' }),
  );

  expect(await findByRole('grid')).toBeInTheDocument();
  expect(queryByRole('table')).not.toBeInTheDocument();
  const gridHost = container.querySelector<AgGridContainerElement>(
    '[data-themed-ag-grid]',
  );
  const api = gridHost?._agGridApi;
  if (!api) throw new Error('The AG Grid API did not initialize');
  act(() => {
    api.applyColumnState({ state: [{ colId: 'rate', sort: 'asc' }] });
  });

  await userEvent.click(await findByRole('button', { name: 'View as table' }));
  const table = await findByRole('table');
  expect(
    within(table)
      .getAllByRole('rowheader')
      .map(header => header.textContent),
  ).toEqual(['North Market', 'West Market']);
  expect(queryByRole('grid')).not.toBeInTheDocument();

  await userEvent.click(
    await findByRole('button', { name: 'Interactive grid' }),
  );
  expect(gridHost).toBeVisible();
  act(() => {
    api.setFilterModel({
      center: { filterType: 'text', type: 'equals', filter: 'West Market' },
    });
  });
  await waitFor(() => expect(api.getDisplayedRowCount()).toBe(1));
  await userEvent.click(await findByRole('button', { name: 'View as table' }));
  const filtered = await findByRole('table');
  expect(
    within(filtered).getByRole('rowheader', { name: 'West Market' }),
  ).toBeInTheDocument();
  expect(
    within(filtered).queryByRole('rowheader', { name: 'North Market' }),
  ).not.toBeInTheDocument();
});

test.each([
  [false, undefined],
  [true, 'saved-table'],
])(
  'retains the existing grid for unsupported hosts or saved widgets (%s, %s)',
  async (preferNativeTable, savedId) => {
    const { findByRole, queryByRole } = renderTable(preferNativeTable, savedId);
    expect(await findByRole('grid')).toBeInTheDocument();
    expect(
      queryByRole('button', { name: 'View as table' }),
    ).not.toBeInTheDocument();
    expect(queryByRole('table')).not.toBeInTheDocument();
  },
);

test('updates the native data when dashboard filters change', async () => {
  const fetchData = jest
    .fn<
      ReturnType<WidgetDataClient['fetchData']>,
      Parameters<WidgetDataClient['fetchData']>
    >()
    .mockResolvedValueOnce(response)
    .mockResolvedValueOnce({ ...response, rows: response.rows.slice(1) });
  const { bus, findByRole } = renderTable(true, undefined, fetchData);
  expect(
    await findByRole('rowheader', { name: 'West Market' }),
  ).toBeInTheDocument();

  const resolved = {
    column: 'center',
    operator: 'IN',
    value: ['North Market'],
    datasource: 2,
  };
  act(() => {
    bus.emit('host:center', dashboardApi.VALUE_CHANGED_EVENT, { resolved });
  });

  const table = await findByRole('table');
  expect(fetchData.mock.calls[1][0].filters).toEqual([resolved]);
  expect(
    within(table).getByRole('rowheader', { name: 'North Market' }),
  ).toBeInTheDocument();
  expect(
    within(table).queryByRole('rowheader', { name: 'West Market' }),
  ).not.toBeInTheDocument();
});

test('pages through all rows without putting the entire result into the table', async () => {
  const rows = Array.from({ length: 51 }, (_, index) => ({
    center: `Center ${index + 1}`,
    rate: 0,
  }));
  const { findByRole, getByRole } = renderTable(true, undefined, async () => ({
    ...response,
    rows,
  }));
  const table = await findByRole('table');
  expect(within(table).getAllByRole('rowheader')).toHaveLength(50);
  expect(getByRole('status')).toHaveTextContent('Rows 1–50 of 51');
  await userEvent.click(getByRole('button', { name: 'Next' }));
  expect(within(table).getAllByRole('rowheader')).toHaveLength(1);
  expect(
    within(table).getByRole('rowheader', { name: 'Center 51' }),
  ).toBeInTheDocument();
  expect(getByRole('status')).toHaveTextContent('Rows 51–51 of 51');
  expect(getByRole('button', { name: 'Next' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
});

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
import { render, waitFor } from 'spec/helpers/testing-library';
import { supersetTheme } from '@apache-superset/core/theme';
import {
  setupAGGridModules,
  type AgGridContainerElement,
} from '@superset-ui/core/components/ThemedAgGridReact';
import { GridTable } from '.';
import { PIVOT_COL_ID } from './constants';

// Jest renders the `css` prop as a plain attribute, so record the styles
// GridTable builds instead of reading them from the DOM.
jest.mock('@apache-superset/core/theme', () => {
  const actual = jest.requireActual('@apache-superset/core/theme');
  return { ...actual, css: jest.fn(actual.css) };
});

const mockedProps = {
  queryId: 'abc',
  columns: ['a', 'b', 'c'].map(key => ({
    key,
    label: key,
    headerName: key,
    render: ({ value }: { value: any }) => value,
  })),
  data: [
    { a: 'a1', b: 'b1', c: 'c1', d: 0 },
    { a: 'a2', b: 'b2', c: 'c2', d: 100 },
    { a: null, b: 'b3', c: 'c3', d: 50 },
  ],
  height: 500,
};

beforeAll(() => {
  setupAGGridModules();
});

test('renders a grid with 3 Table rows', () => {
  const { queryByText } = render(<GridTable {...mockedProps} />);
  mockedProps.data.forEach(({ b: columnBContent }) => {
    expect(queryByText(columnBContent)).toBeInTheDocument();
  });
});

test('sets an opaque grid background so rows do not show through the sticky header', async () => {
  const { container } = render(<GridTable {...mockedProps} />);
  const gridContainer = container.querySelector<AgGridContainerElement>(
    '[data-themed-ag-grid]',
  );
  await waitFor(() => expect(gridContainer?._agGridApi).toBeDefined());

  // ag-grid paints its sticky header container with the data background,
  // which derives from the backgroundColor param.
  const theme = gridContainer!._agGridApi!.getGridOption(
    'theme',
  ) as unknown as { _getParamsCss: () => string };
  expect(theme._getParamsCss()).toContain(
    `--ag-background-color: var(--ag-inherited-background-color, ${supersetTheme.colorBgContainer});`,
  );
});

test('sorts strings correctly', () => {
  const stringProps = {
    ...mockedProps,
    columns: ['columnA'].map(key => ({
      key,
      label: key,
      headerName: key,
      render: ({ value }: { value: any }) => value,
    })),
    data: [{ columnA: 'Bravo' }, { columnA: 'Alpha' }, { columnA: 'Charlie' }],
    height: 500,
  };
  const { container } = render(<GridTable {...stringProps} />);

  // Original order
  expect(container).toHaveTextContent(['Bravo', 'Alpha', 'Charlie'].join(''));
});

test('clips multi-line cell values at the cell so they do not overlap the rows below', () => {
  const { css } = jest.requireMock('@apache-superset/core/theme');
  css.mockClear();
  render(<GridTable {...mockedProps} />);

  const gridStyles = css.mock.results
    .map(({ value }: { value: { styles: string } }) => value.styles)
    .find((styles: string) => styles.includes('.ag-cell-value'));

  // The cell has the fixed row height; the inner value span grows to fit its
  // lines, so the clip has to be on the cell itself.
  expect(gridStyles).toMatch(/\.ag-cell\s*\{\s*overflow:\s*hidden;/);
});

const getPinnedSide = async (container: HTMLElement) => {
  const gridContainer = container.querySelector<AgGridContainerElement>(
    '[data-themed-ag-grid]',
  );
  await waitFor(() => expect(gridContainer?._agGridApi).toBeDefined());
  const api = gridContainer!._agGridApi!;
  return {
    api,
    pinned: api.getColumn(PIVOT_COL_ID)?.getPinned(),
  };
};

test('pins the row-number column to the left in a left-to-right interface', async () => {
  const { container } = render(<GridTable {...mockedProps} showRowNumber />);
  const { api, pinned } = await getPinnedSide(container);

  expect(api.getGridOption('enableRtl')).toBeFalsy();
  expect(pinned).toBe('left');
  expect(api.getAllDisplayedColumns().map(column => column.getColId())).toEqual(
    [PIVOT_COL_ID, 'a', 'b', 'c'],
  );
});

test('pins the row-number column to the right so it leads in a right-to-left interface', async () => {
  const { container } = render(<GridTable {...mockedProps} showRowNumber />, {
    direction: 'rtl',
  });
  const { api, pinned } = await getPinnedSide(container);

  expect(api.getGridOption('enableRtl')).toBe(true);
  // ag-grid keeps pinned sides physical when mirrored: the right side is where
  // a right-to-left row starts.
  expect(pinned).toBe('right');
  // Displayed columns come back in reading order, which is also the order
  // copy-to-clipboard and the CSV export use.
  expect(api.getAllDisplayedColumns().map(column => column.getColId())).toEqual(
    [PIVOT_COL_ID, 'a', 'b', 'c'],
  );
});

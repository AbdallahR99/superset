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
import '@testing-library/jest-dom';
import { renderHook } from '@testing-library/react';
import { render, screen } from '@superset-ui/core/spec';
import { GenericDataType } from '@apache-superset/core/common';
import { themeObject } from '@apache-superset/core/theme';
import { ReactNode } from 'react';
import AgGridTableChartPlugin from '../src';
import Pagination from '../src/AgGridTable/components/Pagination';
import { JsonCellRenderer } from '../src/renderers/JsonCellRenderer';
import { NumericCellRenderer } from '../src/renderers/NumericCellRenderer';
import { ROW_NUMBER_COL_ID } from '../src/consts';
import { InputColumn } from '../src/types';
import { getPopoverLeft, toLogicalTextAlign } from '../src/utils/direction';
import { useColDefs } from '../src/utils/useColDefs';

const { SupersetThemeProvider } = themeObject;

const LtrWrapper = ({ children }: { children?: ReactNode }) => (
  <SupersetThemeProvider direction="ltr">{children}</SupersetThemeProvider>
);

const RtlWrapper = ({ children }: { children?: ReactNode }) => (
  <SupersetThemeProvider direction="rtl">{children}</SupersetThemeProvider>
);

const column: InputColumn = {
  key: 'a',
  label: 'A',
  dataType: GenericDataType.Numeric,
  isNumeric: true,
  isMetric: false,
  isPercentMetric: false,
  config: {},
};

const colDefsProps = {
  columns: [column],
  data: [{ a: 1 }, { a: 2 }],
  serverPagination: false,
  serverPaginationData: {},
  serverPageLength: 0,
  showNumberedColumn: true,
  isRawRecords: true,
  defaultAlignPN: false,
  showCellBars: false,
  colorPositiveNegative: false,
  totals: undefined,
  columnColorFormatters: [],
  allowRearrangeColumns: false,
  basicColorFormatters: [],
  isUsingTimeComparison: false,
  emitCrossFilters: false,
  alignPositiveNegative: false,
  slice_id: 1,
};

const numericCellParams = (overrides: Record<string, unknown> = {}) =>
  ({
    value: -12.5,
    valueFormatted: '-12.5%',
    node: { rowPinned: undefined, rowIndex: 0 },
    hasBasicColorFormatters: false,
    basicColorFormatters: [],
    col: { isNumeric: true, config: {} },
    valueRange: undefined,
    alignPositiveNegative: false,
    colorPositiveNegative: false,
    ...overrides,
  }) as unknown as Parameters<typeof NumericCellRenderer>[0];

const paginationProps = {
  currentPage: 1,
  pageSize: 10,
  totalRows: 50,
  pageSizeOptions: [10, 20],
  onServerPaginationChange: jest.fn(),
  onServerPageSizeChange: jest.fn(),
  sliceId: 1,
};

// Arrow icons of the pager buttons, in DOM order (the page size select has
// an icon of its own, which is not an arrow).
const pagerIcons = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('.anticon'))
    .map(icon =>
      Array.from(icon.classList).find(
        name =>
          name.startsWith('anticon-') &&
          (name.includes('left') || name.includes('right')),
      ),
    )
    .filter(Boolean);

test('the AG Grid table follows the interface direction', () => {
  expect(new AgGridTableChartPlugin().metadata.direction).toBe('inherit');
});

test('toLogicalTextAlign maps physical sides to logical ones', () => {
  expect(toLogicalTextAlign('left')).toBe('start');
  expect(toLogicalTextAlign('right')).toBe('end');
  expect(toLogicalTextAlign('center')).toBe('center');
});

test('pins the row number column to the left in a left-to-right grid', () => {
  const { result } = renderHook(() => useColDefs(colDefsProps), {
    wrapper: LtrWrapper,
  });
  expect(result.current[0].field).toBe(ROW_NUMBER_COL_ID);
  expect(result.current[0].pinned).toBe('left');
});

test('pins the row number column to the right in a right-to-left grid', () => {
  const { result } = renderHook(() => useColDefs(colDefsProps), {
    wrapper: RtlWrapper,
  });
  expect(result.current[0].field).toBe(ROW_NUMBER_COL_ID);
  expect(result.current[0].pinned).toBe('right');
});

test('aligns numeric cells to the inline end whatever the direction', () => {
  const { result } = renderHook(() => useColDefs(colDefsProps), {
    wrapper: RtlWrapper,
  });
  const { cellStyle } = result.current[1];
  expect(typeof cellStyle).toBe('function');
  const style = (cellStyle as unknown as (params: unknown) => unknown)({
    value: 1,
    colDef: { field: 'a' },
    rowIndex: 0,
    node: {},
  });
  expect(style).toMatchObject({ textAlign: 'end' });
});

test('isolates numeric cell values left-to-right in a right-to-left grid', () => {
  const { container } = render(
    <NumericCellRenderer {...numericCellParams()} />,
    { direction: 'rtl' },
  );
  const isolated = container.querySelector('bdi');
  expect(isolated).toHaveAttribute('dir', 'ltr');
  expect(isolated).toHaveTextContent('-12.5%');
});

test('isolates the total row and cell bar values in a right-to-left grid', () => {
  const total = render(
    <NumericCellRenderer
      {...numericCellParams({ node: { rowPinned: 'bottom', rowIndex: 0 } })}
    />,
    { direction: 'rtl' },
  );
  expect(total.container.querySelector('bdi')).toHaveAttribute('dir', 'ltr');
  total.unmount();

  const bar = render(
    <NumericCellRenderer {...numericCellParams({ valueRange: [-20, 20] })} />,
    { direction: 'rtl' },
  );
  expect(bar.container.querySelector('bdi')).toHaveAttribute('dir', 'ltr');
});

test('keeps numeric cell markup unchanged in a left-to-right grid', () => {
  const { container } = render(
    <NumericCellRenderer {...numericCellParams()} />,
  );
  expect(container.querySelector('bdi')).toBeNull();
  expect(container).toHaveTextContent('-12.5%');
});

test('pager arrows point outwards in a left-to-right pager', () => {
  const { container } = render(<Pagination {...paginationProps} />);
  expect(pagerIcons(container)).toEqual([
    'anticon-vertical-right',
    'anticon-left',
    'anticon-right',
    'anticon-vertical-left',
  ]);
});

test('pager arrows are mirrored in a right-to-left pager', () => {
  const { container } = render(<Pagination {...paginationProps} />, {
    direction: 'rtl',
  });
  // Same DOM order (first, previous, next, last); the row itself is laid out
  // from right to left, so each arrow points the other way.
  expect(pagerIcons(container)).toEqual([
    'anticon-vertical-left',
    'anticon-right',
    'anticon-left',
    'anticon-vertical-right',
  ]);
});

test('getPopoverLeft keeps the original left-to-right placement', () => {
  const rect = { left: 300, right: 320 };
  // Fits: ends 170px after the trigger's right edge.
  expect(
    getPopoverLeft({
      rect,
      popoverWidth: 200,
      windowWidth: 1000,
      isRtl: false,
    }),
  ).toBe(320 - 200 + 170);
  // Would spill out of the window: ends at the trigger's right edge.
  expect(
    getPopoverLeft({ rect, popoverWidth: 200, windowWidth: 600, isRtl: false }),
  ).toBe(320 - 200);
  // Never leaves the viewport on the left.
  expect(
    getPopoverLeft({
      rect: { left: 10, right: 30 },
      popoverWidth: 200,
      windowWidth: 300,
      isRtl: false,
    }),
  ).toBe(0);
});

test('getPopoverLeft mirrors the placement in a right-to-left grid', () => {
  const rect = { left: 700, right: 720 };
  // Fits: starts 170px before the trigger's left edge.
  expect(
    getPopoverLeft({ rect, popoverWidth: 200, windowWidth: 1000, isRtl: true }),
  ).toBe(700 - 170);
  // Would spill out on the left: starts at the trigger's left edge.
  expect(
    getPopoverLeft({
      rect: { left: 100, right: 120 },
      popoverWidth: 200,
      windowWidth: 1000,
      isRtl: true,
    }),
  ).toBe(100);
  // Never leaves the viewport on the right.
  expect(
    getPopoverLeft({
      rect: { left: 900, right: 920 },
      popoverWidth: 200,
      windowWidth: 1000,
      isRtl: true,
    }),
  ).toBe(730);
  expect(
    getPopoverLeft({
      rect: { left: 250, right: 270 },
      popoverWidth: 200,
      windowWidth: 300,
      isRtl: true,
    }),
  ).toBe(100);
});

test('keeps JSON cells left-to-right in a right-to-left grid', () => {
  render(
    <JsonCellRenderer value={{ a: 1 }} colId="json" autoHeight={false} />,
    { direction: 'rtl' },
  );
  expect(screen.getByTestId('json-cell')).toHaveAttribute('dir', 'ltr');
});

test('does not add a dir attribute to JSON cells in a left-to-right grid', () => {
  render(<JsonCellRenderer value={{ a: 1 }} colId="json" autoHeight={false} />);
  expect(screen.getByTestId('json-cell')).not.toHaveAttribute('dir');
});

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
import type { NodeApi } from 'react-arborist';
import { Theme, type Direction } from '@apache-superset/core/theme';
import { render, screen } from 'spec/helpers/testing-library';
import TreeNodeRenderer, {
  type TreeNodeRendererProps,
} from './TreeNodeRenderer';
import type { TreeNodeData } from './types';

const theme = Theme.fromConfig();

const createNode = (data: TreeNodeData): NodeApi<TreeNodeData> =>
  ({
    data,
    isOpen: false,
    isLeaf: false,
    isSelected: false,
    select: jest.fn(),
    toggle: jest.fn(),
  }) as unknown as NodeApi<TreeNodeData>;

const setup = (data: TreeNodeData, direction: Direction, paddingLeft = 32) => {
  const props = {
    node: createNode(data),
    // react-arborist hands the indentation over as a physical padding.
    style: { paddingLeft },
    manuallyOpenedNodes: {},
    loadingNodes: {},
    searchTerm: '',
    catalog: null,
    pinnedTableKeys: new Set<string>(),
    pinnedSchemas: new Set<string>(),
    selectStarMap: {},
    handleRefreshTables: jest.fn(),
    handlePinTable: jest.fn(),
    handleUnpinTable: jest.fn(),
    handlePinSchema: jest.fn(),
    handleUnpinSchema: jest.fn(),
    refreshTableSchema: jest.fn(),
    sortedTables: {},
    toggleSortColumns: jest.fn(),
  } as unknown as TreeNodeRendererProps;
  return render(
    <theme.SupersetThemeProvider direction={direction}>
      <TreeNodeRenderer {...props} />
    </theme.SupersetThemeProvider>,
  );
};

const tableNode = {
  id: 'table:1:public:_orders',
  name: '_orders',
  type: 'table',
} as TreeNodeData;

const getRow = (container: HTMLElement) =>
  container.querySelector('.tree-node') as HTMLElement;

test('indents on the inline-start side instead of the physical left', () => {
  const { container } = setup(tableNode, 'rtl');
  const row = getRow(container);

  expect(row.style.paddingInlineStart).toBe('32px');
  expect(row.style.paddingLeft).toBe('');
  // The list viewport of react-arborist is always left-to-right, so the row
  // itself carries the interface direction.
  expect(row).toHaveAttribute('dir', 'rtl');
});

test('keeps the left-to-right markup free of a direction attribute', () => {
  const { container } = setup(tableNode, 'ltr');
  const row = getRow(container);

  expect(row.style.paddingInlineStart).toBe('32px');
  expect(row).not.toHaveAttribute('dir');
});

test('isolates the object name so leading punctuation is not reordered', () => {
  setup(tableNode, 'rtl');

  expect(screen.getByText('_orders').closest('bdi')).toBeInTheDocument();
});

test('applies the same indentation to column and empty rows', () => {
  const column = setup(
    {
      id: 'column:1:public:_orders:amount',
      name: 'amount',
      type: 'column',
      columnData: { name: 'amount', type: 'NUMERIC(10, 2)' },
    } as TreeNodeData,
    'rtl',
    48,
  );
  expect(getRow(column.container).style.paddingInlineStart).toBe('48px');
  expect(getRow(column.container)).toHaveAttribute('dir', 'rtl');
  expect(screen.getByText('NUMERIC(10, 2)')).toHaveAttribute('dir', 'ltr');
  column.unmount();

  const empty = setup(
    { id: 'empty:1:public', name: 'No tables', type: 'empty' } as TreeNodeData,
    'rtl',
    16,
  );
  expect(getRow(empty.container).style.paddingInlineStart).toBe('16px');
  expect(getRow(empty.container)).toHaveAttribute('dir', 'rtl');
});

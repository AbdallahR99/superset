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
import { render } from '@superset-ui/core/spec';
import { PivotTableChartPlugin } from '../src';
import PivotTableChart from '../src/PivotTableChart';
import transformProps from '../src/plugin/transformProps';
import testData from './testData';

const chartProps = {
  ...transformProps(testData.withColTotals),
  margin: 32,
  legacy_order_by: null,
  order_desc: false,
};

const VALUE_CELLS = 'td.pvtVal, td.pvtTotal, td.pvtGrandTotal';

test('the pivot table follows the interface direction', () => {
  expect(new PivotTableChartPlugin().metadata.direction).toBe('inherit');
});

test('isolates aggregated values left-to-right in a right-to-left table', () => {
  const { container } = render(<PivotTableChart {...chartProps} />, {
    direction: 'rtl',
  });

  const valueCells = Array.from(container.querySelectorAll(VALUE_CELLS));
  expect(valueCells.length).toBeGreaterThan(0);
  valueCells.forEach(cell => expect(cell).toHaveAttribute('dir', 'ltr'));
  // Row and column totals are isolated as well as the regular values.
  expect(container.querySelector('td.pvtVal')).toHaveAttribute('dir', 'ltr');
  expect(container.querySelector('td.pvtRowTotal')).toHaveAttribute(
    'dir',
    'ltr',
  );
  expect(container.querySelector('td.pvtGrandTotal')).toHaveAttribute(
    'dir',
    'ltr',
  );
  // Labels keep the direction of the table.
  container
    .querySelectorAll('th')
    .forEach(header => expect(header).not.toHaveAttribute('dir'));
});

test('keeps value cell markup unchanged in a left-to-right table', () => {
  const { container } = render(<PivotTableChart {...chartProps} />);

  const valueCells = Array.from(container.querySelectorAll(VALUE_CELLS));
  expect(valueCells.length).toBeGreaterThan(0);
  valueCells.forEach(cell => expect(cell).not.toHaveAttribute('dir'));
});

test('mirrors the frozen row labels and the value alignment in right-to-left', () => {
  const { container } = render(<PivotTableChart {...chartProps} />, {
    direction: 'rtl',
  });

  // Written as `left: 0` / `text-align: right`, mirrored by the theme: the
  // row labels freeze at the right edge and the values align to the left,
  // which are the inline start and the inline end of a right-to-left table.
  const rowLabelStyle = getComputedStyle(
    container.querySelector('tbody th.pvtRowLabel') as Element,
  );
  expect(rowLabelStyle.position).toBe('sticky');
  expect(rowLabelStyle.right).toBe('0px');
  expect(rowLabelStyle.left).toBe('');
  const valueStyle = getComputedStyle(
    container.querySelector('td.pvtVal') as Element,
  );
  expect(valueStyle.textAlign).toBe('left');
});

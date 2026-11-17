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
import { GenericDataType } from '@apache-superset/core/common';
import TableChartPlugin from '../src';
import TableChart from '../src/TableChart';
import transformProps from '../src/transformProps';
import { isolateCellText, toLogicalTextAlign } from '../src/utils/direction';
import testData from './testData';

const getHeader = (container: HTMLElement, label: string) =>
  Array.from(container.querySelectorAll<HTMLElement>('thead th')).find(
    th => th.textContent === label,
  );

const getCell = (container: HTMLElement, text: string) =>
  Array.from(container.querySelectorAll<HTMLElement>('tbody td')).find(
    td => td.textContent === text,
  );

test('the table chart follows the interface direction', () => {
  expect(new TableChartPlugin().metadata.direction).toBe('inherit');
});

test('toLogicalTextAlign maps physical sides to logical ones', () => {
  expect(toLogicalTextAlign('left')).toBe('start');
  expect(toLogicalTextAlign('right')).toBe('end');
  expect(toLogicalTextAlign('center')).toBe('center');
});

test('isolateCellText leaves left-to-right tables untouched', () => {
  expect(
    isolateCellText(
      '-12.5%',
      { dataType: GenericDataType.Numeric, isNumeric: true },
      false,
    ),
  ).toBe('-12.5%');
});

test('isolateCellText only isolates numeric and temporal values', () => {
  const { container } = render(
    <>
      <p data-test="numeric">
        {isolateCellText(
          '-12.5%',
          { dataType: GenericDataType.Numeric, isNumeric: true },
          true,
        )}
      </p>
      <p data-test="metric">
        {isolateCellText(
          '$ 4.54B',
          { dataType: GenericDataType.String, isMetric: true },
          true,
        )}
      </p>
      <p data-test="temporal">
        {isolateCellText(
          '2024-01-31 10:00:00',
          { dataType: GenericDataType.Temporal },
          true,
        )}
      </p>
      <p data-test="text">
        {isolateCellText('الصحة', { dataType: GenericDataType.String }, true)}
      </p>
    </>,
  );
  const numeric = container.querySelector('[data-test="numeric"] bdi');
  expect(numeric).toHaveAttribute('dir', 'ltr');
  expect(numeric).toHaveTextContent('-12.5%');
  expect(container.querySelector('[data-test="metric"] bdi')).toHaveAttribute(
    'dir',
    'ltr',
  );
  // Temporal values take the direction of their own content.
  const temporal = container.querySelector('[data-test="temporal"] bdi');
  expect(temporal).toBeInTheDocument();
  expect(temporal).not.toHaveAttribute('dir');
  expect(container.querySelector('[data-test="text"] bdi')).toBeNull();
});

test('aligns columns with logical values so they follow the table direction', () => {
  const { container } = render(
    <TableChart {...transformProps(testData.basic)} sticky={false} />,
    { direction: 'rtl' },
  );

  // Text columns sit at the inline start, numeric ones at the inline end.
  expect(getHeader(container, 'name')).toHaveStyle({ textAlign: 'start' });
  expect(getHeader(container, 'sum__num')).toHaveStyle({ textAlign: 'end' });
  expect(getCell(container, 'Michael')).toHaveStyleRule('text-align', 'start');
  expect(getCell(container, '2467063')).toHaveStyleRule('text-align', 'end');
});

test('keeps the same logical alignment in a left-to-right table', () => {
  const { container } = render(
    <TableChart {...transformProps(testData.basic)} sticky={false} />,
  );

  expect(getHeader(container, 'name')).toHaveStyle({ textAlign: 'start' });
  expect(getHeader(container, 'sum__num')).toHaveStyle({ textAlign: 'end' });
});

test('isolates numeric cells left-to-right in a right-to-left table', () => {
  const { container } = render(
    <TableChart {...transformProps(testData.basic)} sticky={false} />,
    { direction: 'rtl' },
  );

  const numericCell = getCell(container, '2467063');
  expect(numericCell?.querySelector('bdi')).toHaveAttribute('dir', 'ltr');
  // Plain text keeps the direction of the table.
  expect(getCell(container, 'Michael')?.querySelector('bdi')).toBeNull();
});

test('does not add isolation markup to a left-to-right table', () => {
  const { container } = render(
    <TableChart {...transformProps(testData.basic)} sticky={false} />,
  );

  expect(container.querySelector('bdi')).toBeNull();
});

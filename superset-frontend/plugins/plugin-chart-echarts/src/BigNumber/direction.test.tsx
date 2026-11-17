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
import { ComponentProps } from 'react';
import { getNumberFormatter } from '@superset-ui/core';
import { render, screen } from '../../../../spec/helpers/testing-library';
import {
  BigNumberChartPlugin,
  BigNumberPeriodOverPeriodChartPlugin,
  BigNumberTotalChartPlugin,
} from '.';
import BigNumberVis from './BigNumberViz';
import PopKPI from './BigNumberPeriodOverPeriod/PopKPI';
import { PopKPIProps } from './BigNumberPeriodOverPeriod/types';

jest.mock('../components/Echart', () => ({
  __esModule: true,
  default: jest.fn(() => null),
}));

type VizProps = ComponentProps<typeof BigNumberVis>;

const vizProps: VizProps = {
  width: 200,
  height: 100,
  bigNumber: -0.125,
  headerFormatter: getNumberFormatter('.1%'),
  headerFontSize: 0.3,
  subheaderFontSize: 0.125,
  subtitleFontSize: 0.125,
  subheader: '-12.5% WoW',
  subtitle: 'الصحة',
  refs: {},
};

const popKpiProps: PopKPIProps = {
  height: 200,
  width: 400,
  data: [],
  metrics: [],
  metricName: 'Sales',
  showMetricName: true,
  headerText: '',
  boldText: true,
  bigNumber: '$ 4.54B',
  prevNumber: '100',
  valueDifference: '-20',
  percentDifferenceFormattedString: '-20%',
  compType: 'r',
  percentDifferenceNumber: -0.2,
  subtitleFontSize: 0.15,
  shift: '',
  headerFontSize: 'l',
  subheaderFontSize: 'm',
  comparisonColorEnabled: true,
};

test.each([
  ['Big Number', BigNumberTotalChartPlugin],
  ['Big Number with Trendline', BigNumberChartPlugin],
  [
    'Big Number with Time Period Comparison',
    BigNumberPeriodOverPeriodChartPlugin,
  ],
])('%s follows the interface direction', (_, Plugin) => {
  expect(new Plugin().metadata.direction).toBe('inherit');
});

test('isolates the big number left-to-right in a right-to-left interface', () => {
  const { container } = render(<BigNumberVis {...vizProps} />, {
    direction: 'rtl',
  });

  const number = container.querySelector('.header-line bdi');
  expect(number).toHaveAttribute('dir', 'ltr');
  expect(number).toHaveTextContent('-12.5%');
});

test('lets the other lines take the direction of their own text', () => {
  const { container } = render(<BigNumberVis {...vizProps} />, {
    direction: 'rtl',
  });

  const subheader = container.querySelector(
    '.subheader-line:not(.subtitle-line) bdi',
  );
  expect(subheader).toHaveTextContent('-12.5% WoW');
  expect(subheader).not.toHaveAttribute('dir');
  const subtitle = container.querySelector('.subtitle-line bdi');
  expect(subtitle).toHaveTextContent('الصحة');
  expect(subtitle).not.toHaveAttribute('dir');
});

test('does not force a direction on a big number that is not a number', () => {
  const { container } = render(
    <BigNumberVis {...vizProps} bigNumber="الصحة" />,
    { direction: 'rtl' },
  );

  const text = container.querySelector('.header-line bdi');
  expect(text).toHaveTextContent('الصحة');
  expect(text).not.toHaveAttribute('dir');
});

test('aligns the text lines with logical values', () => {
  const { container, rerender } = render(<BigNumberVis {...vizProps} />, {
    direction: 'rtl',
  });
  // "left" is the default: the start of the line, on the same side as the
  // flex-start aligned number.
  expect(container.querySelector('.subheader-line')).toHaveStyle({
    textAlign: 'start',
  });
  expect(container.querySelector('.header-line')).toHaveStyle({
    justifyContent: 'flex-start',
  });

  rerender(<BigNumberVis {...vizProps} headerAlignment="right" />);
  expect(container.querySelector('.subheader-line')).toHaveStyle({
    textAlign: 'end',
  });
  expect(container.querySelector('.header-line')).toHaveStyle({
    justifyContent: 'flex-end',
  });
});

test('keeps the big number markup unchanged in a left-to-right interface', () => {
  const { container } = render(<BigNumberVis {...vizProps} />);

  expect(container.querySelector('bdi')).toBeNull();
  expect(container.querySelector('.header-line')).toHaveTextContent('-12.5%');
});

test('isolates the KPI numbers left-to-right in a right-to-left interface', () => {
  render(<PopKPI {...popKpiProps} />, { direction: 'rtl' });

  ['$ 4.54B', '100', '-20', '-20%'].forEach(text => {
    const number = screen.getByText(text);
    expect(number.tagName).toBe('BDI');
    expect(number).toHaveAttribute('dir', 'ltr');
  });
});

test('keeps the KPI markup unchanged in a left-to-right interface', () => {
  const { container } = render(<PopKPI {...popKpiProps} />);

  expect(container.querySelector('bdi')).toBeNull();
  expect(screen.getByText('-20%')).toBeInTheDocument();
});

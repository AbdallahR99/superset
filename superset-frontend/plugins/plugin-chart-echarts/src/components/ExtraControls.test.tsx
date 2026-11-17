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
import { LtrIsolate, useDirection } from '@apache-superset/core/theme';
import { render, screen } from '../../../../spec/helpers/testing-library';
import { ExtraControls } from './ExtraControls';

const mockDirectionProbe = jest.fn();

// The shared control is replaced by a probe that reports the direction it is
// rendered in, which is what the wrapper is responsible for.
jest.mock('@superset-ui/chart-controls', () => ({
  ...jest.requireActual('@superset-ui/chart-controls'),
  sharedControlComponents: {
    RadioButtonControl: () => {
      mockDirectionProbe();
      return <span data-test="radio-control" />;
    },
  },
}));

const DirectionProbe = () => (
  <span data-test="chart-direction">{useDirection()}</span>
);

const formData = { stack: null, area: true, showExtraControls: true };

// Mirrors what the chart container does: the plot is isolated left-to-right.
const renderInChartContainer = (direction?: 'rtl') =>
  render(
    <LtrIsolate data-test="chart-container">
      <DirectionProbe />
      <ExtraControls formData={formData} />
    </LtrIsolate>,
    { direction },
  );

test('gives the controls the page direction back inside the left-to-right chart', () => {
  renderInChartContainer('rtl');

  // The chart itself is isolated left-to-right ...
  expect(screen.getByTestId('chart-container')).toHaveAttribute('dir', 'ltr');
  expect(screen.getByTestId('chart-direction')).toHaveTextContent('ltr');
  // ... while the controls next to the canvas are interface again.
  const wrapper = screen.getByTestId('radio-control').parentElement;
  expect(wrapper).toHaveAttribute('dir', 'rtl');
  expect(mockDirectionProbe).toHaveBeenCalled();
});

test('keeps the controls markup unchanged on a left-to-right page', () => {
  renderInChartContainer();

  const wrapper = screen.getByTestId('radio-control').parentElement;
  expect(wrapper).not.toHaveAttribute('dir');
});

test('renders nothing when the extra controls are turned off', () => {
  render(
    <ExtraControls formData={{ ...formData, showExtraControls: false }} />,
  );

  expect(screen.queryByTestId('radio-control')).not.toBeInTheDocument();
});

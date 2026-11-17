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
import {
  render,
  screen,
  userEvent,
  waitFor,
} from 'spec/helpers/testing-library';
import BoundsControl from 'src/explore/components/controls/BoundsControl';

const defaultProps = {
  name: 'y_axis_bounds',
  label: 'Bounds of the y axis',
  onChange: jest.fn(),
};

test('renders two inputs', () => {
  render(<BoundsControl {...defaultProps} />);
  expect(screen.getAllByRole('spinbutton')).toHaveLength(2);
});

test('receives null on non-numeric', async () => {
  render(<BoundsControl {...defaultProps} />);
  const minInput = screen.getAllByRole('spinbutton')[0];
  await userEvent.type(minInput, '1');
  await userEvent.clear(minInput);
  await waitFor(() =>
    expect(defaultProps.onChange).toHaveBeenCalledWith([null, null]),
  );
});

test('calls onChange with correct values', async () => {
  render(<BoundsControl {...defaultProps} />);
  const minInput = screen.getAllByRole('spinbutton')[0];
  const maxInput = screen.getAllByRole('spinbutton')[1];
  await userEvent.type(minInput, '1');
  await userEvent.type(maxInput, '2');
  await waitFor(() =>
    expect(defaultProps.onChange).toHaveBeenLastCalledWith([1, 2]),
  );
});

test('receives 0 value', async () => {
  render(<BoundsControl {...defaultProps} />);
  const minInput = screen.getAllByRole('spinbutton')[0];
  await userEvent.type(minInput, '0');
  await waitFor(() =>
    expect(defaultProps.onChange).toHaveBeenLastCalledWith([0, null]),
  );
});

test('lets a bound resolve its own direction in right-to-left layouts', () => {
  // A negative bound is displayed as "5-" when laid out right-to-left.
  render(<BoundsControl {...defaultProps} value={[-5, null]} />, {
    direction: 'rtl',
  });

  const [minInput, maxInput] = screen.getAllByRole('spinbutton');
  expect(minInput).toHaveAttribute('dir', 'auto');
  // An empty bound keeps its placeholder on the side of the interface.
  expect(maxInput).not.toHaveAttribute('dir');
});

test('adds no direction attribute to the bounds in left-to-right layouts', () => {
  render(<BoundsControl {...defaultProps} value={[-5, 5]} />);

  screen
    .getAllByRole('spinbutton')
    .forEach(input => expect(input).not.toHaveAttribute('dir'));
});

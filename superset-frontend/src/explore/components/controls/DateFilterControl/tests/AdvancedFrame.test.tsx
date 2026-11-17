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
import { render, screen, userEvent } from 'spec/helpers/testing-library';
import { AdvancedFrame } from '../components';

test('renders with default props', () => {
  render(<AdvancedFrame onChange={jest.fn()} value="Last week" />);
  expect(screen.getByText('Configure Advanced Time Range')).toBeInTheDocument();
});

test('render with empty value', () => {
  render(<AdvancedFrame onChange={jest.fn()} value="" />);
  expect(screen.getByText('Configure Advanced Time Range')).toBeInTheDocument();
});

test('triggers since onChange', async () => {
  const onChange = jest.fn();
  render(<AdvancedFrame onChange={onChange} value="Next week" />);
  await userEvent.type(screen.getAllByRole('textbox')[0], 'Last week');
  expect(onChange).toHaveBeenCalled();
});

test('triggers until onChange', async () => {
  const onChange = jest.fn();
  render(<AdvancedFrame onChange={onChange} value="today : tomorrow" />);
  await userEvent.type(screen.getAllByRole('textbox')[1], 'dayAfterTomorrow');
  expect(onChange).toHaveBeenCalled();
});

test('keeps the date expressions left-to-right in right-to-left layouts', () => {
  render(<AdvancedFrame onChange={jest.fn()} value="Last week : today" />, {
    direction: 'rtl',
  });

  const [since, until] = screen.getAllByRole('textbox');
  // `DATEADD(DATETIME("today"), -7, day)` must not be reordered
  expect(since).toHaveAttribute('dir', 'ltr');
  expect(until).toHaveAttribute('dir', 'ltr');
  // Ant Design pins `direction: rtl` with this class, overriding the attribute
  expect(since).not.toHaveClass('ant-input-rtl');
  expect(until).not.toHaveClass('ant-input-rtl');
});

test('adds no direction attribute in left-to-right layouts', () => {
  render(<AdvancedFrame onChange={jest.fn()} value="Last week : today" />);

  screen
    .getAllByRole('textbox')
    .forEach(input => expect(input).not.toHaveAttribute('dir'));
});

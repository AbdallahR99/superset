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
import { render, screen, userEvent } from '@superset-ui/core/spec';
import { Button, Icons, Tooltip } from '..';

test('starts hidden with default props', () => {
  render(
    <Tooltip title="Simple tooltip">
      <Button>Hover me</Button>
    </Tooltip>,
  );
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
});

test('renders on hover', async () => {
  render(
    <Tooltip title="Simple tooltip">
      <Button>Hover me</Button>
    </Tooltip>,
  );
  await userEvent.hover(screen.getByRole('button'));
  expect(await screen.findByRole('tooltip')).toBeInTheDocument();
});

test('renders with icon child', async () => {
  render(
    <Tooltip title="Simple tooltip">
      <Icons.WarningOutlined>Hover me</Icons.WarningOutlined>
    </Tooltip>,
  );
  await userEvent.hover(screen.getByRole('img'));
  expect(await screen.findByRole('tooltip')).toBeInTheDocument();
});

const placementClass = () =>
  // eslint-disable-next-line testing-library/no-node-access
  Array.from(document.querySelector('.ant-tooltip')?.classList ?? []).find(
    name => name.startsWith('ant-tooltip-placement-'),
  );

test('keeps an explicit placement in a left-to-right layout', () => {
  render(
    <Tooltip title="Simple tooltip" placement="topLeft" open>
      <Button>Hover me</Button>
    </Tooltip>,
  );
  expect(placementClass()).toBe('ant-tooltip-placement-topLeft');
});

test('mirrors an explicit placement in a right-to-left layout', () => {
  render(
    <Tooltip title="Simple tooltip" placement="topLeft" open>
      <Button>Hover me</Button>
    </Tooltip>,
    { direction: 'rtl' },
  );
  expect(placementClass()).toBe('ant-tooltip-placement-topRight');
});

test('keeps a physical placement when mirrorPlacement is false', () => {
  render(
    <Tooltip
      title="Simple tooltip"
      placement="left"
      mirrorPlacement={false}
      open
    >
      <Button>Hover me</Button>
    </Tooltip>,
    { direction: 'rtl' },
  );
  expect(placementClass()).toBe('ant-tooltip-placement-left');
});

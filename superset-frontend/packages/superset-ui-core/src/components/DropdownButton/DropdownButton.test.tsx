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
import { fireEvent, render, waitFor } from '@superset-ui/core/spec';
import { DropdownButton } from '.';

const menuProps = { items: [{ key: '1', label: 'Item 1' }] };

test('renders without crashing when no styleConfig is provided', () => {
  const { container } = render(
    <DropdownButton menu={menuProps}>Click</DropdownButton>,
  );
  expect(container.querySelector('.ant-btn')).toBeInTheDocument();
});

test('renders without crashing with full styleConfig', () => {
  const { container } = render(
    <DropdownButton
      menu={menuProps}
      styleConfig={{
        controlHeight: 40,
        fontSize: 16,
        fontWeight: 700,
        boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
      }}
    >
      Click
    </DropdownButton>,
  );
  expect(container.querySelector('.ant-btn')).toBeInTheDocument();
});

test('renders tooltip when tooltip prop is provided', async () => {
  const { getByText } = render(
    <DropdownButton menu={menuProps} tooltip="My Tooltip">
      Click
    </DropdownButton>,
  );
  fireEvent.mouseEnter(getByText('Click'));
  await waitFor(() => {
    expect(document.querySelector('[role="tooltip"]')).toHaveTextContent(
      'My Tooltip',
    );
  });
});

test('does not render tooltip wrapper when tooltip is not provided', () => {
  const { container } = render(
    <DropdownButton menu={menuProps}>Click</DropdownButton>,
  );
  expect(container.querySelector('[id$="-tooltip"]')).not.toBeInTheDocument();
});

test('passes button type to underlying Dropdown.Button', () => {
  const { container } = render(
    <DropdownButton menu={menuProps} type="primary">
      Click
    </DropdownButton>,
  );
  expect(container.querySelector('.ant-btn-primary')).toBeInTheDocument();
});

test('opens the popupRender content without crashing on click trigger', async () => {
  const { getAllByRole, findByText } = render(
    <DropdownButton
      popupRender={() => <div>Custom Menu</div>}
      trigger={['click']}
    >
      Click
    </DropdownButton>,
  );
  const buttons = getAllByRole('button');
  fireEvent.click(buttons[buttons.length - 1]);
  expect(await findByText('Custom Menu')).toBeInTheDocument();
});

const placementClass = () =>
  // eslint-disable-next-line testing-library/no-node-access
  Array.from(document.querySelector('.ant-dropdown')?.classList ?? []).find(
    name => name.startsWith('ant-dropdown-placement-'),
  );

const overlay = () => <div>Overlay</div>;

test('mirrors an explicit placement in a right-to-left layout', () => {
  render(
    <DropdownButton popupRender={overlay} placement="bottomLeft" open>
      Click
    </DropdownButton>,
    { direction: 'rtl' },
  );
  expect(placementClass()).toBe('ant-dropdown-placement-bottomRight');
});

test('leaves the default placement to Ant Design', () => {
  // Ant Design opens the menu at the end of the button and mirrors that
  // default itself: bottomRight left-to-right, bottomLeft right-to-left.
  const { unmount } = render(
    <DropdownButton popupRender={overlay} open>
      Click
    </DropdownButton>,
  );
  expect(placementClass()).toBe('ant-dropdown-placement-bottomRight');
  unmount();
  render(
    <DropdownButton popupRender={overlay} open>
      Click
    </DropdownButton>,
    { direction: 'rtl' },
  );
  expect(placementClass()).toBe('ant-dropdown-placement-bottomLeft');
});

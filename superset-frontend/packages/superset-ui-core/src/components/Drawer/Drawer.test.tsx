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
import { render } from '@superset-ui/core/spec';
import { Drawer } from '.';

// eslint-disable-next-line testing-library/no-node-access
const drawer = () => document.querySelector('.ant-drawer');

test('opens on the right by default in a left-to-right layout', () => {
  render(<Drawer open>Content</Drawer>);
  expect(drawer()).toHaveClass('ant-drawer-right');
});

test('opens on the left by default in a right-to-left layout', () => {
  render(<Drawer open>Content</Drawer>, { direction: 'rtl' });
  expect(drawer()).toHaveClass('ant-drawer-left');
});

test('mirrors an explicit side in a right-to-left layout', () => {
  render(
    <Drawer open placement="left">
      Content
    </Drawer>,
    { direction: 'rtl' },
  );
  expect(drawer()).toHaveClass('ant-drawer-right');
});

test('leaves a vertical placement untouched', () => {
  render(
    <Drawer open placement="bottom">
      Content
    </Drawer>,
    { direction: 'rtl' },
  );
  expect(drawer()).toHaveClass('ant-drawer-bottom');
});

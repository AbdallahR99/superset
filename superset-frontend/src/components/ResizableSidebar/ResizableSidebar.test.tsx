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
import { render } from 'spec/helpers/testing-library';
import ResizableSidebar from '.';

const renderSidebar = (direction?: 'ltr' | 'rtl', enable = true) =>
  render(
    <ResizableSidebar id="test" initialWidth={200} enable={enable}>
      {width => <div data-test="content">{width}</div>}
    </ResizableSidebar>,
    { direction },
  );

const handles = (container: HTMLElement) =>
  // eslint-disable-next-line testing-library/no-node-access
  Array.from(container.querySelectorAll<HTMLElement>('.sidebar-resizer'));

test('puts the resize handle on the right edge in a left-to-right layout', () => {
  const { container } = renderSidebar();
  const [handle, ...others] = handles(container);
  expect(others).toHaveLength(0);
  expect(handle.style.right).toBe('-5px');
  expect(handle.style.left).toBe('');
});

test('puts the resize handle on the left edge in a right-to-left layout', () => {
  const { container } = renderSidebar('rtl');
  const [handle, ...others] = handles(container);
  expect(others).toHaveLength(0);
  expect(handle.style.left).toBe('-5px');
  expect(handle.style.right).toBe('');
});

test.each(['ltr', 'rtl'] as const)(
  'renders no handle when resizing is disabled (%s)',
  direction => {
    const { container } = renderSidebar(direction, false);
    expect(handles(container)).toHaveLength(0);
  },
);

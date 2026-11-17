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
import { render, screen } from 'spec/helpers/testing-library';
import {
  ExplorePopoverContent,
  getResizeDeltaX,
} from './ExploreContentPopover';

const renderGrip = (direction?: 'rtl') =>
  render(
    <ExplorePopoverContent data-test="content">
      <span className="edit-popover-resize" />
    </ExplorePopoverContent>,
    { direction },
  );

const GRIP = { target: '.edit-popover-resize' };

test('getResizeDeltaX grows with a drag to the right', () => {
  expect(getResizeDeltaX(500, 560, false)).toBe(60);
  expect(getResizeDeltaX(500, 440, false)).toBe(-60);
});

test('getResizeDeltaX grows with a drag to the left in right-to-left layouts', () => {
  expect(getResizeDeltaX(500, 440, true)).toBe(60);
  expect(getResizeDeltaX(500, 560, true)).toBe(-60);
});

test('puts the resize grip on the bottom-right corner', () => {
  renderGrip();
  const content = screen.getByTestId('content');

  expect(content).toHaveStyleRule('float', 'right', GRIP);
  expect(content).toHaveStyleRule('cursor', 'nwse-resize', GRIP);
  expect(content).toHaveStyleRule('transform', 'scaleX(-1)', GRIP);
});

test('puts the resize grip on the bottom-left corner in right-to-left layouts', () => {
  renderGrip('rtl');
  const content = screen.getByTestId('content');

  // `float` is mirrored by the style engine; the cursor and the arrows are
  // not, so they follow the direction explicitly.
  expect(content).toHaveStyleRule('float', 'left', GRIP);
  expect(content).toHaveStyleRule('cursor', 'nesw-resize', GRIP);
  expect(content).toHaveStyleRule('transform', 'none', GRIP);
});

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
  createEvent,
  fireEvent,
  render,
  screen,
} from 'spec/helpers/testing-library';
import type { Direction } from '@apache-superset/core/theme';
import DashboardProvider from 'src/core/dashboard/DashboardProvider';
import 'src/core/dashboard';
import EditorPanel, { resizedWidth } from './EditorPanel';

const provider = DashboardProvider.getInstance();

beforeEach(() => {
  provider.reset();
});

const mount = (direction: Direction) =>
  render(<EditorPanel onAdd={jest.fn()} />, { direction });

const widthOf = (): number =>
  parseInt(screen.getByTestId('editor-panel').style.width, 10);

/** Drags the panel's edge from one viewport x to another. */
const dragHandle = (fromX: number, toX: number): void => {
  const handle = screen.getByTestId('panel-resize');
  // jsdom has no `PointerEvent`, so a `clientX` handed to `fireEvent` never
  // reaches the handler; it is defined on the event itself instead.
  const firePointer = (
    type: 'pointerDown' | 'pointerMove' | 'pointerUp',
    clientX: number,
  ): void => {
    const event = createEvent[type](handle);
    Object.defineProperty(event, 'clientX', { value: clientX });
    Object.defineProperty(event, 'pointerId', { value: 1 });
    fireEvent(handle, event);
  };
  firePointer('pointerDown', fromX);
  firePointer('pointerMove', toX);
  firePointer('pointerUp', toX);
};

test('a drag to the right widens a rail on the left and narrows one on the right', () => {
  expect(resizedWidth(400, 500, 540, false)).toBe(440);
  expect(resizedWidth(400, 500, 540, true)).toBe(360);
  expect(resizedWidth(400, 500, 460, true)).toBe(440);
});

test('left-to-right, dragging the edge right makes the panel wider', () => {
  mount('ltr');

  dragHandle(400, 440);

  expect(widthOf()).toBe(440);
});

test('right-to-left, dragging the edge left makes the panel wider', () => {
  mount('rtl');

  dragHandle(800, 760);

  expect(widthOf()).toBe(440);
});

test('right-to-left, dragging the edge right makes the panel narrower', () => {
  mount('rtl');

  dragHandle(800, 840);

  expect(widthOf()).toBe(360);
});

test('right-to-left, the arrow pointing away from the panel is the one that grows it', () => {
  mount('rtl');
  const handle = screen.getByTestId('panel-resize');

  fireEvent.keyDown(handle, { key: 'ArrowLeft' });
  expect(widthOf()).toBe(416);

  fireEvent.keyDown(handle, { key: 'ArrowRight' });
  fireEvent.keyDown(handle, { key: 'ArrowRight' });
  expect(widthOf()).toBe(384);
});

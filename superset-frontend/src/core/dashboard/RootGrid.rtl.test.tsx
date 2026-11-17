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
import DashboardProvider from './DashboardProvider';
import RootGrid from './RootGrid';
import { registerBuiltInWidgets } from './registerBuiltInWidgets';
import {
  __getLastGridStackInstance,
  __resetGridStackMock,
} from '../../../spec/__mocks__/gridstackMock';

/** 24 columns across 1200px: one column every 50px. */
const CONTAINER_WIDTH = 1200;

const provider = DashboardProvider.getInstance();

beforeAll(() => {
  registerBuiltInWidgets();
});

beforeEach(() => {
  provider.reset();
  __resetGridStackMock();
  document.elementFromPoint = jest.fn().mockReturnValue(null);
  jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width: CONTAINER_WIDTH,
    height: 800,
    top: 0,
    left: 0,
    right: CONTAINER_WIDTH,
    bottom: 800,
    x: 0,
    y: 0,
    toJSON: () => {},
  });
});

afterEach(() => {
  jest.restoreAllMocks();
});

const paletteTransfer = (type: string) => {
  const data = new Map([['application/x-dashboard-widget', type]]);
  return {
    types: [...data.keys()],
    getData: (key: string) => data.get(key) ?? '',
    setData: (key: string, value: string) => data.set(key, value),
    dropEffect: '',
    effectAllowed: '',
  };
};

/**
 * One widget filling the second half of the first rows (columns 13 to 24),
 * so the first half is open space and the two halves are told apart by
 * where a drop lands.
 */
const mount = (direction: Direction) => {
  const rootId = provider.getRoot().id;
  const existing = provider.addWidget(rootId, 0, {
    type: 'markdown',
    layout: { col: 13, row: 1, colSpan: 12, rowSpan: 4 },
  });
  render(<RootGrid nodeId={rootId} />, { direction });
  return { rootId, existing };
};

const gridElement = (): Element =>
  screen.getByTestId('grid-container').querySelector('.grid-stack')!;

/**
 * Fires a drag event that really carries a pointer position. jsdom has no
 * `DragEvent`, so the `clientX`/`clientY` handed to `fireEvent.drop` are
 * dropped on the floor and a handler reads `undefined` for both; they are
 * defined on the event itself here.
 */
const fireDrag = (type: 'dragOver' | 'drop', clientX: number): void => {
  const event = createEvent[type](gridElement(), {
    dataTransfer: paletteTransfer('markdown'),
  });
  Object.defineProperty(event, 'clientX', { value: clientX });
  // Two rows down: the middle of the existing widget's height, clear of the
  // bands along its top and bottom edges that mean "above" and "below".
  Object.defineProperty(event, 'clientY', { value: 96 });
  fireEvent(gridElement(), event);
};

/** Drops a palette widget at a viewport x and returns the node it created. */
const dropAt = (clientX: number, rootId: string, existing: string) => {
  fireDrag('dragOver', clientX);
  const ghost = screen.getByTestId('grid-drop-ghost');
  const ghostStyle = { left: ghost.style.left, right: ghost.style.right };
  fireDrag('drop', clientX);
  const created = (provider.getNode(rootId)?.children ?? []).find(
    id => id !== existing,
  );
  return { ghostStyle, layout: provider.getNode(created ?? '')?.layout };
};

test('the grid engine is told when the page reads right-to-left', () => {
  mount('rtl');

  expect(__getLastGridStackInstance()?.options.rtl).toBe(true);
});

test('the grid engine is left-to-right otherwise', () => {
  mount('ltr');

  expect(__getLastGridStackInstance()?.options.rtl).toBe(false);
});

test('left-to-right, a drop near the left edge lands in the first column', () => {
  const { rootId, existing } = mount('ltr');

  const { ghostStyle, layout } = dropAt(10, rootId, existing);

  expect(layout?.col).toBe(1);
  expect(ghostStyle.left).not.toBe('');
  expect(ghostStyle.right).toBe('');
});

test('right-to-left, the first column is at the right edge, for the preview and for the drop', () => {
  const { rootId, existing } = mount('rtl');

  // 10px in from the right edge: the first column when columns count from
  // the right, and the last one if the pointer were read left-to-right.
  const { ghostStyle, layout } = dropAt(CONTAINER_WIDTH - 10, rootId, existing);

  expect(layout?.col).toBe(1);
  // The preview is anchored to the same edge the columns are counted from.
  expect(ghostStyle.right).not.toBe('');
  expect(ghostStyle.left).toBe('');
});

test('right-to-left, a drop near the left edge lands on the widget in the last columns', () => {
  const { rootId, existing } = mount('rtl');

  const { layout } = dropAt(10, rootId, existing);

  // Not open space: the pointer is over the existing widget, so the new one
  // takes part of its columns rather than the free first half.
  expect(layout?.col).toBeGreaterThan(12);
});

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
import type { ClientRect } from '@dnd-kit/core';
import { horizontalListSortingStrategy } from '@dnd-kit/sortable';
import { rtlHorizontalListSortingStrategy } from './rtlHorizontalListSortingStrategy';

const rect = (left: number, width: number): ClientRect => ({
  left,
  width,
  right: left + width,
  top: 0,
  bottom: 40,
  height: 40,
});

const GAP = 10;
// three tabs of different widths, first tab on the left
const ltrRects = [rect(100, 100), rect(210, 110), rect(330, 50)];
// the same tabs in a right-to-left tab bar: first tab on the right
const rtlRects = [rect(300, 100), rect(180, 110), rect(120, 50)];

const shifts = (
  strategy: typeof horizontalListSortingStrategy,
  rects: ClientRect[],
  activeIndex: number,
  overIndex: number,
) =>
  rects.map(
    (_, index) =>
      strategy({ rects, activeNodeRect: null, activeIndex, overIndex, index })
        ?.x,
  );

test('moving the first tab to the end shifts the others towards the start', () => {
  // left-to-right reference: the others close the gap by moving left
  expect(shifts(horizontalListSortingStrategy, ltrRects, 0, 2)).toEqual([
    330 + 50 - (100 + 100),
    -(100 + GAP),
    -(100 + GAP),
  ]);
  // right-to-left: the same move, mirrored
  expect(shifts(rtlHorizontalListSortingStrategy, rtlRects, 0, 2)).toEqual([
    120 - 300,
    100 + GAP,
    100 + GAP,
  ]);
});

test('moving the last tab to the start shifts the others towards the end', () => {
  expect(shifts(horizontalListSortingStrategy, ltrRects, 2, 0)).toEqual([
    50 + GAP,
    50 + GAP,
    100 - 330,
  ]);
  expect(shifts(rtlHorizontalListSortingStrategy, rtlRects, 2, 0)).toEqual([
    -(50 + GAP),
    -(50 + GAP),
    300 + 100 - (120 + 50),
  ]);
});

test('tabs outside the moved range stay where they are', () => {
  expect(shifts(rtlHorizontalListSortingStrategy, rtlRects, 0, 1)).toEqual([
    180 - 300,
    100 + GAP,
    0,
  ]);
});

test('returns nothing when the dragged tab has no measured rect', () => {
  expect(
    rtlHorizontalListSortingStrategy({
      rects: [],
      activeNodeRect: null,
      activeIndex: 0,
      overIndex: 1,
      index: 1,
    }),
  ).toBeNull();
});

test('the stock strategy is not usable as is in a right-to-left tab bar', () => {
  // documents why the mirrored strategy exists: with the first tab moved to
  // the end the stock strategy shifts the second tab by its own width instead
  // of by the width of the dragged one
  expect(shifts(horizontalListSortingStrategy, rtlRects, 0, 2)[1]).not.toBe(
    100 + GAP,
  );
});

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
  cellAtPoint,
  inlineOffsetPx,
  pixelRectForCell,
  positionStyleForRect,
  resolveCellGeometry,
} from './layoutStyle';

/** A grid that does not start at the viewport's own edge. */
const RECT = { left: 100, right: 1300 };
const GEOMETRY = resolveCellGeometry(
  { columns: 24, gap: 16, rowUnitPx: 32 },
  RECT.right - RECT.left,
);

test('left-to-right, the pointer offset is measured from the left edge', () => {
  expect(inlineOffsetPx(150, RECT, false)).toBe(50);
});

test('right-to-left, the pointer offset is measured from the right edge', () => {
  expect(inlineOffsetPx(1250, RECT, true)).toBe(50);
  expect(inlineOffsetPx(150, RECT, true)).toBe(1150);
});

test('the same physical point is the mirrored column in the other direction', () => {
  const ltr = cellAtPoint(inlineOffsetPx(125, RECT, false), 0, GEOMETRY).col;
  const rtl = cellAtPoint(inlineOffsetPx(125, RECT, true), 0, GEOMETRY).col;

  expect(ltr).toBeCloseTo(0.5);
  expect(rtl).toBeCloseTo(23.5);
});

test('a pointer and the preview drawn for it agree in both directions', () => {
  [false, true].forEach(isRtl => {
    // The centre of the third column, wherever that is on screen.
    const clientX = isRtl ? RECT.right - 125 : RECT.left + 125;
    const { col } = cellAtPoint(
      inlineOffsetPx(clientX, RECT, isRtl),
      0,
      GEOMETRY,
    );
    const style = positionStyleForRect(
      pixelRectForCell({ x: Math.floor(col), y: 0, w: 1, h: 1 }, GEOMETRY),
      isRtl,
    );
    const inlineStart = isRtl ? style.right : style.left;
    const physicalLeft = isRtl
      ? RECT.right - (inlineStart ?? 0) - style.width
      : RECT.left + (inlineStart ?? 0);

    expect(Math.floor(col)).toBe(2);
    expect(physicalLeft).toBeLessThanOrEqual(clientX);
    expect(physicalLeft + style.width).toBeGreaterThanOrEqual(clientX);
  });
});

test('the preview is anchored to one edge only', () => {
  const pixelRect = { left: 8, top: 8, width: 34, height: 32 };

  expect(positionStyleForRect(pixelRect, false)).toEqual({
    left: 8,
    top: 8,
    width: 34,
    height: 32,
  });
  expect(positionStyleForRect(pixelRect, true)).toEqual({
    right: 8,
    top: 8,
    width: 34,
    height: 32,
  });
});

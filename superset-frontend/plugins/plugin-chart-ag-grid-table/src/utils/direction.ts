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

/**
 * Maps a physical horizontal alignment to its logical equivalent, so that a
 * "left" aligned column sits at the start of the row and a "right" aligned
 * one at its end in both left-to-right and right-to-left grids. Other values
 * (`center`, ...) are returned as they are.
 */
export function toLogicalTextAlign(align: string): string {
  if (align === 'left') {
    return 'start';
  }
  if (align === 'right') {
    return 'end';
  }
  return align;
}

export interface PopoverAnchorRect {
  left: number;
  right: number;
}

/**
 * Horizontal position (viewport `left`, in pixels) of a header popover.
 *
 * Left-to-right: the popover ends at the trigger's right edge and is pushed
 * 170px further right while that still fits in the window. Right-to-left is
 * the mirror image: it starts at the trigger's left edge and is pushed 170px
 * further left while that still fits. The result never leaves the viewport on
 * the side the popover grows towards.
 */
export function getPopoverLeft({
  rect,
  popoverWidth,
  measuredPopoverWidth = popoverWidth,
  windowWidth,
  isRtl,
}: {
  rect: PopoverAnchorRect;
  /** Width used for the "does it fit" check (falls back to an estimate). */
  popoverWidth: number;
  /** Width actually measured, 0 before the first layout. */
  measuredPopoverWidth?: number;
  windowWidth: number;
  isRtl: boolean;
}): number {
  if (isRtl) {
    const leftEdgePosition = rect.right - 10 - 160 - popoverWidth;
    const shouldUseOffset = leftEdgePosition >= 0;
    return Math.max(
      0,
      Math.min(
        windowWidth - measuredPopoverWidth,
        rect.left - (shouldUseOffset ? 170 : 0),
      ),
    );
  }
  const rightEdgePosition = rect.left + 10 + 160 + popoverWidth;
  // Check if popover would spill out of the window
  const shouldUseOffset = rightEdgePosition <= windowWidth;
  return Math.max(
    0,
    rect.right - measuredPopoverWidth + (shouldUseOffset ? 170 : 0),
  );
}

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
import {
  horizontalListSortingStrategy,
  type SortingStrategy,
} from '@dnd-kit/sortable';

// Reflects a rect across the vertical axis.
const mirror = (rect: ClientRect): ClientRect => ({
  ...rect,
  left: -(rect.left + rect.width),
  right: -rect.left,
});

/**
 * horizontalListSortingStrategy for a list laid out right-to-left.
 *
 * The stock strategy derives how far the items between the dragged tab and
 * its target move from the assumption that the next item is on the right. In
 * a right-to-left tab bar the next item is on the left, which gives the tabs
 * a wrong displacement as soon as their widths differ. The layout is
 * reflected into the one the strategy expects and the resulting horizontal
 * shift is reflected back.
 */
export const rtlHorizontalListSortingStrategy: SortingStrategy = args => {
  const transform = horizontalListSortingStrategy({
    ...args,
    rects: args.rects.map(rect => rect && mirror(rect)),
    activeNodeRect: args.activeNodeRect && mirror(args.activeNodeRect),
  });
  return transform && { ...transform, x: transform.x ? -transform.x : 0 };
};

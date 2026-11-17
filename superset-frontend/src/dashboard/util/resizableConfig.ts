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
// config for a ResizableContainer
const adjustableWidthAndHeight = {
  top: false,
  right: true,
  bottom: true,
  left: false,
  topRight: false,
  bottomRight: true,
  bottomLeft: false,
  topLeft: false,
};

const adjustableWidth = {
  ...adjustableWidthAndHeight,
  bottomRight: false,
  bottom: false,
};

const adjustableHeight = {
  ...adjustableWidthAndHeight,
  bottomRight: false,
  right: false,
};

const notAdjustable = {
  ...adjustableWidthAndHeight,
  bottomRight: false,
  bottom: false,
  right: false,
};

const resizableConfig = {
  widthAndHeight: adjustableWidthAndHeight,
  widthOnly: adjustableWidth,
  heightOnly: adjustableHeight,
  notAdjustable,
};

type ResizableEdges = typeof adjustableWidthAndHeight;

// A grid component is anchored at its inline-start edge and grows towards
// inline-end, so the width handles belong on the inline-end edge: the
// physical left one when the layout is right-to-left.
const toInlineEnd = (edges: ResizableEdges): ResizableEdges => ({
  ...edges,
  right: edges.left,
  left: edges.right,
  bottomRight: edges.bottomLeft,
  bottomLeft: edges.bottomRight,
  topRight: edges.topLeft,
  topLeft: edges.topRight,
});

const rtlResizableConfig: typeof resizableConfig = {
  widthAndHeight: toInlineEnd(adjustableWidthAndHeight),
  widthOnly: toInlineEnd(adjustableWidth),
  heightOnly: toInlineEnd(adjustableHeight),
  notAdjustable: toInlineEnd(notAdjustable),
};

export const getResizableConfig = (isRtl: boolean): typeof resizableConfig =>
  isRtl ? rtlResizableConfig : resizableConfig;

export default resizableConfig;

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
import resizableConfig, {
  getResizableConfig,
} from 'src/dashboard/util/resizableConfig';

const enabledEdges = (edges: Record<string, boolean>) =>
  Object.keys(edges)
    .filter(edge => edges[edge])
    .sort();

test('left-to-right uses the default config with handles on the right edge', () => {
  const config = getResizableConfig(false);
  expect(config).toBe(resizableConfig);
  expect(enabledEdges(config.widthAndHeight)).toEqual([
    'bottom',
    'bottomRight',
    'right',
  ]);
  expect(enabledEdges(config.widthOnly)).toEqual(['right']);
  expect(enabledEdges(config.heightOnly)).toEqual(['bottom']);
  expect(enabledEdges(config.notAdjustable)).toEqual([]);
});

test('right-to-left moves the width handles to the left edge', () => {
  const config = getResizableConfig(true);
  expect(enabledEdges(config.widthAndHeight)).toEqual([
    'bottom',
    'bottomLeft',
    'left',
  ]);
  expect(enabledEdges(config.widthOnly)).toEqual(['left']);
  expect(enabledEdges(config.heightOnly)).toEqual(['bottom']);
  expect(enabledEdges(config.notAdjustable)).toEqual([]);
});

test('the right-to-left config is stable between calls', () => {
  expect(getResizableConfig(true)).toBe(getResizableConfig(true));
});

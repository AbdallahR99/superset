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
import { FeatureFlag } from '@superset-ui/core';
import { views } from 'src/core/views';
import { isContainerType } from './DashboardProvider';
import { registerBuiltInWidgetsIfEnabled } from './registerBuiltInWidgets';
import { DASHBOARD_WIDGETS_LOCATION } from './resolveWidgetView';

type FlagWindow = { featureFlags?: Record<string, boolean> };

const setFlag = (enabled: boolean | undefined): void => {
  (window as unknown as FlagWindow).featureFlags =
    enabled === undefined ? {} : { [FeatureFlag.DashboardV2]: enabled };
};

const registeredIds = (): string[] =>
  (views.getViews(DASHBOARD_WIDGETS_LOCATION) ?? []).map(view => view.id);

afterAll(() => {
  setFlag(undefined);
});

// One test, in this order, on purpose: registration happens once per page
// and is not undone, so "off registers nothing" can only be shown before
// "on registers everything".
test('the built-in widgets are registered only where Dashboard v2 is turned on', () => {
  setFlag(undefined);
  expect(registerBuiltInWidgetsIfEnabled()).toBe(false);
  setFlag(false);
  expect(registerBuiltInWidgetsIfEnabled()).toBe(false);
  expect(registeredIds()).toEqual([]);
  expect(isContainerType('tabs')).toBe(false);

  setFlag(true);
  expect(registerBuiltInWidgetsIfEnabled()).toBe(true);

  expect(registeredIds()).toEqual(
    expect.arrayContaining([
      'markdown',
      'echarts',
      'ag-grid-table',
      'metric-tile',
      'filter.select',
      'filter.bar',
      'tabs',
      'collapsible',
      'carousel',
    ]),
  );
  expect(isContainerType('tabs')).toBe(true);

  // Asking again registers nothing twice.
  const count = registeredIds().length;
  expect(registerBuiltInWidgetsIfEnabled()).toBe(true);
  expect(registeredIds()).toHaveLength(count);
});

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
import { Behavior, getChartMetadataRegistry, VizType } from '@superset-ui/core';
import { ChartCustomizationPlugins, FilterPlugins } from 'src/constants';
import MainPreset from './MainPreset';

// Charts that are documents rather than plots: they follow the direction of
// the interface. Every other chart of the preset is a plot and stays
// left-to-right in a right-to-left interface. A chart is added here together
// with `direction: 'inherit'` in its metadata, after its layout has been
// checked in a right-to-left language.
const DOCUMENT_CHARTS: string[] = [
  VizType.BigNumber,
  VizType.BigNumberTotal,
  VizType.Handlebars,
  VizType.PivotTable,
  VizType.Table,
  VizType.TimeTable,
];

// Interface controls rendered through the chart registry.
const INTERFACE_CONTROLS: string[] = [
  ...Object.values(FilterPlugins),
  ...Object.values(ChartCustomizationPlugins),
];

const followsInterface = (key: string) => {
  const metadata = getChartMetadataRegistry().get(key);
  if (metadata?.direction) {
    return metadata.direction === 'inherit';
  }
  const behaviors = metadata?.behaviors ?? [];
  return (
    behaviors.includes(Behavior.NativeFilter) ||
    behaviors.includes(Behavior.ChartCustomization)
  );
};

test('every chart of the main preset has a deliberate direction', () => {
  new MainPreset().register();
  const keys = getChartMetadataRegistry().keys();
  expect(keys.length).toBeGreaterThan(0);

  const following = keys.filter(followsInterface).sort();
  expect(following).toEqual([...DOCUMENT_CHARTS, ...INTERFACE_CONTROLS].sort());

  // Plots never opt in: their axes, legends and canvases stay left-to-right.
  const plots = keys.filter(key => !followsInterface(key));
  expect(plots).toEqual(
    expect.arrayContaining([
      VizType.Bar,
      VizType.Line,
      VizType.Pie,
      VizType.Funnel,
      VizType.Heatmap,
      VizType.Calendar,
      VizType.PairedTTest,
      'deck_scatter',
    ]),
  );
  plots.forEach(key => {
    expect(getChartMetadataRegistry().get(key)?.direction).not.toBe('inherit');
  });
});

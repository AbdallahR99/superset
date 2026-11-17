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
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { widgetPreview } from '../src/widgetPreview.ts';

test('builds a metric tile binding without dimensions or executable options', () => {
  assert.deepEqual(
    widgetPreview({
      type: 'metric-tile',
      title: 'Revenue',
      datasetId: 10,
      metric: 'sum__amount',
      dimension: 'region',
    }),
    {
      type: 'metric-tile',
      props: {
        dataBinding: {
          datasetId: 10,
          metrics: ['sum__amount'],
          dimensions: [],
          rowLimit: 100,
        },
        label: 'Revenue',
      },
    },
  );
});

test('uses the same allowlisted data binding for table and chart previews', () => {
  const input = { datasetId: 10, metric: 'sum__amount', dimension: 'region' };
  const table = widgetPreview({ ...input, type: 'ag-grid-table' });
  const chart = widgetPreview({ ...input, type: 'echarts' });
  assert.deepEqual(table?.props.dataBinding, chart?.props.dataBinding);
  assert.deepEqual(chart?.props.echartsOptions, {
    xAxis: {
      type: 'category',
      data: { $bind: { source: 'dimension', alias: 'region' } },
    },
    yAxis: { type: 'value' },
    series: [
      {
        type: 'bar',
        data: { $bind: { source: 'metric', alias: 'sum__amount' } },
      },
    ],
  });
  assert.equal(chart?.props.crossFilter, true);
});

test('leaves an incomplete widget preview idle until its binding can run', () => {
  assert.equal(
    widgetPreview({ type: 'metric-tile', datasetId: 0, metric: 'count' }),
    undefined,
  );
  assert.equal(
    widgetPreview({ type: 'metric-tile', datasetId: 1, metric: ' ' }),
    undefined,
  );
  assert.equal(
    widgetPreview({ type: 'echarts', datasetId: 1, metric: 'count' }),
    undefined,
  );
});

test('keeps an edited chart title in its declarative widget option', () => {
  const chart = widgetPreview({
    type: 'echarts',
    datasetId: 10,
    metric: 'sum__amount',
    dimension: 'region',
    title: '  Reviewed chart  ',
  });
  assert.equal(
    (chart?.props.echartsOptions as { title: { text: string } }).title.text,
    'Reviewed chart',
  );
});

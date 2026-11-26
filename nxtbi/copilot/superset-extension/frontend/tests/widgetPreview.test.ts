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
import {
  changeWidgetDataset,
  changeWidgetType,
  expandTableFields,
  preserveRateCutoff,
  widgetPreview,
} from '../src/widgetPreview.ts';
import type { ProposedWidget } from '../src/widgetPreview.ts';

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

test('ranks a bounded set of categories with horizontal bars and readable labels', () => {
  const input = { datasetId: 10, metric: 'sum__amount', dimension: 'region' };
  const table = widgetPreview({ ...input, type: 'ag-grid-table' });
  const chart = widgetPreview(
    { ...input, type: 'echarts', chartStyle: 'ranked-bar' },
    'd',
    {
      metrics: new Map([['sum__amount', 'Amount']]),
      dimensions: new Map(),
    },
  );
  assert.deepEqual(table?.props.dataBinding, {
    datasetId: 10,
    metrics: ['sum__amount'],
    dimensions: ['region'],
    rowLimit: 100,
  });
  assert.deepEqual(chart?.props.dataBinding, {
    datasetId: 10,
    metrics: ['sum__amount'],
    dimensions: ['region'],
    rowLimit: 12,
    orderByMetric: true,
  });
  assert.equal(chart?.props.crossFilter, true);
  assert.ok(chart);
  const options = chart.props.echartsOptions as {
    title: { text: string };
    xAxis: { type: string; minInterval: number; name: string };
    yAxis: unknown;
    series: unknown;
  };
  assert.equal(options.title.text, 'Amount · Top 12');
  assert.equal(options.xAxis.type, 'value');
  assert.equal(options.xAxis.minInterval, 1);
  assert.equal(options.xAxis.name, 'Amount');
  assert.deepEqual(options.yAxis, {
    type: 'category',
    inverse: true,
    axisLabel: {
      width: 148,
      overflow: 'break',
      fontSize: 11,
      hideOverlap: true,
    },
    data: { $bind: { source: 'dimension', alias: 'region' } },
  });
  assert.deepEqual(options.series, [
    {
      type: 'bar',
      name: 'Amount',
      data: { $bind: { source: 'metric', alias: 'sum__amount' } },
      barMaxWidth: 24,
      realtimeSort: true,
    },
  ]);
});

test('keeps explicit and default legacy bar proposals vertical and unranked', () => {
  const base = {
    type: 'echarts',
    datasetId: 10,
    metric: 'count',
    dimension: 'region',
  } as const;
  const preview = widgetPreview(base);
  assert.deepEqual(widgetPreview({ ...base, chartStyle: 'bar' }), preview);
  assert.ok(preview);
  assert.deepEqual(preview.props.dataBinding, {
    datasetId: 10,
    metrics: ['count'],
    dimensions: ['region'],
    rowLimit: 100,
  });
  assert.deepEqual(preview.props.echartsOptions, {
    animation: false,
    grid: { left: 64, right: 24, bottom: 40, top: 48 },
    tooltip: { trigger: 'axis', renderMode: 'richText' },
    xAxis: {
      type: 'category',
      axisLabel: { hideOverlap: true },
      data: { $bind: { source: 'dimension', alias: 'region' } },
    },
    yAxis: { type: 'value' },
    series: [
      { type: 'bar', data: { $bind: { source: 'metric', alias: 'count' } } },
    ],
  });
});

test('shows saved percentage units for a default vertical bar without changing its layout', () => {
  const preview = widgetPreview(
    {
      type: 'echarts',
      datasetId: 10,
      metric: 'return_rate',
      dimension: 'region',
    },
    '.1%',
  );
  assert.ok(preview);
  assert.deepEqual(preview.props.echartsOptions, {
    animation: false,
    grid: { left: 64, right: 24, bottom: 40, top: 48 },
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
      formatter: '{b0}: {c0}%',
    },
    xAxis: {
      type: 'category',
      axisLabel: { hideOverlap: true },
      data: { $bind: { source: 'dimension', alias: 'region' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: '{value}%' },
      minInterval: 0.1,
    },
    series: [
      {
        type: 'bar',
        data: {
          $bind: { source: 'metric', alias: 'return_rate', format: 'percent' },
        },
      },
    ],
  });
  assert.deepEqual(preview.props.dataBinding, {
    datasetId: 10,
    metrics: ['return_rate'],
    dimensions: ['region'],
    rowLimit: 100,
  });
});

test('shows real points and gaps on a chronologically ordered trend', () => {
  const preview = widgetPreview({
    type: 'echarts',
    datasetId: 10,
    chartStyle: 'line',
    metric: 'amount',
    dimension: 'sale_month',
  });
  assert.ok(preview);
  assert.equal(preview.props.crossFilter, false);
  assert.deepEqual(preview.props.dataBinding, {
    datasetId: 10,
    metrics: ['amount'],
    dimensions: ['sale_month'],
    orderByDimension: true,
    rowLimit: 100,
  });
  const options = preview.props.echartsOptions as {
    xAxis: unknown;
    series: unknown;
  };
  assert.deepEqual(options.xAxis, {
    type: 'category',
    axisLabel: { fontSize: 11, hideOverlap: true },
    data: {
      $bind: { source: 'dimension', alias: 'sale_month', format: 'date' },
    },
  });
  assert.deepEqual(options.series, [
    {
      type: 'line',
      name: 'amount',
      data: { $bind: { source: 'metric', alias: 'amount' } },
      showSymbol: true,
      symbol: 'circle',
      symbolSize: 7,
      smooth: false,
      connectNulls: false,
      lineStyle: { width: 2.5 },
    },
  ]);
});

const rateWidget: ProposedWidget = {
  type: 'echarts',
  chartStyle: 'ranked-bar',
  datasetId: 10,
  metric: 'approval_rate',
  dimension: 'district',
  filter: { column: 'year', value: 2026 },
  rateCutoff: { denominatorMetric: 'applications', minimumSampleSize: 25 },
};

test('previews the rate and eligible sample size in one grouped binding', () => {
  const chart = widgetPreview(rateWidget, '.1%');
  assert.ok(chart);
  assert.deepEqual(chart.props.dataBinding, {
    datasetId: 10,
    metrics: ['approval_rate', 'applications'],
    dimensions: ['district'],
    rowLimit: 12,
    orderByMetric: true,
    filters: [
      {
        expressionType: 'SIMPLE',
        clause: 'WHERE',
        subject: 'year',
        operator: '==',
        comparator: 2026,
      },
    ],
  });
  assert.deepEqual(chart.props.rateCutoff, {
    ...rateWidget.rateCutoff,
    scope: {
      datasetId: 10,
      rateMetric: 'approval_rate',
      dimension: 'district',
    },
  });
  const options = chart.props.echartsOptions as { series: { data: unknown }[] };
  assert.equal(options.series.length, 1);
  assert.deepEqual(options.series[0]?.data, {
    $bind: { source: 'metric', alias: 'approval_rate', format: 'percent' },
  });
});

test('keeps an approved cutoff for caption edits and clears it on scope changes', () => {
  assert.deepEqual(
    preserveRateCutoff(rateWidget, { ...rateWidget, title: 'New caption' })
      .rateCutoff,
    rateWidget.rateCutoff,
  );
  for (const next of [
    changeWidgetDataset(rateWidget, 20),
    changeWidgetType(rateWidget, 'ag-grid-table'),
    { ...rateWidget, metric: 'reject_rate' },
    { ...rateWidget, dimension: 'other_district' },
    { ...rateWidget, chartStyle: 'line' as const },
    { ...rateWidget, filter: undefined },
    { ...rateWidget, filter: { column: 'year', value: 2025 } },
  ]) {
    assert.equal(preserveRateCutoff(rateWidget, next).rateCutoff, undefined);
  }
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
  assert.ok(chart);
  assert.equal(
    (chart.props.echartsOptions as { title: { text: string } }).title.text,
    'Reviewed chart',
  );
});

test('uses a localized ranked title and percentage units without editing the proposal', () => {
  const widget: ProposedWidget = {
    type: 'echarts',
    datasetId: 10,
    chartStyle: 'ranked-bar',
    metric: 'return_rate',
    dimension: 'region',
    title: 'معدل الإرجاع',
  };
  const preview = widgetPreview(widget, '.1%', undefined, 'ar');
  assert.ok(preview);
  const options = preview.props.echartsOptions as {
    title: { text: string };
    xAxis: { minInterval: number; axisLabel: { formatter: string } };
    tooltip: { formatter: string };
    series: { data: unknown }[];
  };
  assert.equal(widget.title, 'معدل الإرجاع');
  assert.equal(options.title.text, 'معدل الإرجاع · أعلى ١٢');
  assert.equal(options.xAxis.minInterval, 0.1);
  assert.equal(options.xAxis.axisLabel.formatter, '{value}٪');
  assert.equal(options.tooltip.formatter, '{b0}: {c0}٪');
  assert.deepEqual(options.series[0]?.data, {
    $bind: { source: 'metric', alias: 'return_rate', format: 'percent' },
  });
});

test('previews every compound table field in selection order with saved labels and date formatting', () => {
  const preview = widgetPreview(
    {
      type: 'ag-grid-table',
      datasetId: 10,
      metrics: ['revenue', 'orders'],
      dimensions: ['month', 'district'],
    },
    undefined,
    {
      metrics: new Map([
        ['revenue', 'Revenue'],
        ['month', 'Months counted'],
      ]),
      dimensions: new Map([
        ['month', { label: 'Month', temporal: true }],
        ['district', { label: 'District', temporal: false }],
        ['revenue', { label: 'Revenue source', temporal: false }],
      ]),
    },
  );
  assert.deepEqual(preview?.props.dataBinding, {
    datasetId: 10,
    metrics: ['revenue', 'orders'],
    dimensions: ['month', 'district'],
    orderByDimension: true,
    rowLimit: 100,
  });
  const metricColumn = {
    flex: 1,
    minWidth: 132,
    wrapHeaderText: true,
    autoHeaderHeight: true,
  };
  const dimensionColumn = {
    ...metricColumn,
    flex: 2,
    minWidth: 160,
    wrapText: true,
    autoHeight: true,
  };
  assert.deepEqual(preview?.props.columnDefs, [
    {
      ...dimensionColumn,
      field: 'month',
      headerName: 'Month',
      valueFormat: 'date',
    },
    { ...dimensionColumn, field: 'district', headerName: 'District' },
    { ...metricColumn, field: 'revenue', headerName: 'Revenue' },
    { ...metricColumn, field: 'orders', headerName: 'orders' },
  ]);
  assert.deepEqual(
    widgetPreview({
      type: 'ag-grid-table',
      datasetId: 10,
      metrics: ['revenue', 'orders'],
      dimensions: [],
    })?.props.dataBinding,
    {
      datasetId: 10,
      metrics: ['revenue', 'orders'],
      dimensions: [],
      rowLimit: 100,
    },
  );
});

test('previews accepted metric formats per table column and ignores unknown formats', () => {
  const preview = widgetPreview(
    {
      type: 'ag-grid-table',
      datasetId: 10,
      metrics: ['return_rate', 'count', 'fees', 'unknown'],
      dimensions: [],
    },
    undefined,
    {
      metrics: new Map(),
      dimensions: new Map(),
      metricFormats: new Map([
        ['return_rate', '.1%'],
        ['count', ',d'],
        ['fees', ',.10f'],
        ['unknown', '.11f'],
      ]),
    },
  );
  assert.ok(preview);
  const columns = preview.props.columnDefs as {
    field: string;
    valueFormat?: string;
    valueFormatPrecision?: number;
  }[];
  assert.deepEqual(
    columns.map(({ field, valueFormat, valueFormatPrecision }) => [
      field,
      valueFormat,
      valueFormatPrecision,
    ]),
    [
      ['return_rate', 'percent', 1],
      ['count', 'decimal', 0],
      ['fees', 'decimal', 10],
      ['unknown', undefined, undefined],
    ],
  );
});

test('uses saved metric labels and fixed decimal precision for a metric tile', () => {
  const preview = widgetPreview(
    { type: 'metric-tile', datasetId: 10, metric: 'avg_amount' },
    ',.2f',
    {
      metrics: new Map([['avg_amount', 'Average amount']]),
      dimensions: new Map([
        ['avg_amount', { label: 'Reference amount', temporal: false }],
      ]),
    },
  );
  assert.equal(preview?.props.label, 'Average amount');
  assert.equal(preview?.props.decimals, 2);
  assert.equal(preview?.props.percentage, undefined);
});

test('switching widget type or dataset leaves only the appropriate binding form', () => {
  const scalar: ProposedWidget = {
    type: 'ag-grid-table',
    datasetId: 10,
    metric: 'revenue',
    dimension: 'month',
    title: 'Revenue by month',
    filter: { column: 'year', value: 2026 },
  };
  const expanded = expandTableFields(scalar);
  assert.deepEqual(expanded, {
    type: 'ag-grid-table',
    datasetId: 10,
    metrics: ['revenue'],
    dimensions: ['month'],
    title: scalar.title,
    filter: scalar.filter,
  });
  assert.ok(expanded.metrics);
  const compound: ProposedWidget = {
    ...expanded,
    type: 'ag-grid-table',
    metrics: ['revenue', 'orders'],
    dimensions: ['month', 'district'],
  };
  assert.deepEqual(changeWidgetType(compound, 'echarts'), {
    ...scalar,
    type: 'echarts',
  });
  const datasetChanged = changeWidgetDataset(compound, 20);
  assert.deepEqual(datasetChanged, {
    ...compound,
    datasetId: 20,
    metrics: [],
    dimensions: [],
    filter: undefined,
  });
  assert.equal(widgetPreview(datasetChanged), undefined);
});

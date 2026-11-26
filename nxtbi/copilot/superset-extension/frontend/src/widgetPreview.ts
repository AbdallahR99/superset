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
import type { DashboardProposal } from '@nxtbi/copilot';

export type ProposedWidget = DashboardProposal['widgets'][number];

export function changeWidgetDataset(
  widget: ProposedWidget,
  datasetId: number,
): ProposedWidget {
  return widget.metrics === undefined
    ? {
        ...widget,
        datasetId,
        metric: '',
        dimension: undefined,
        filter: undefined,
      }
    : { ...widget, datasetId, metrics: [], dimensions: [], filter: undefined };
}

export function changeWidgetType(
  widget: ProposedWidget,
  type: ProposedWidget['type'],
): ProposedWidget {
  if (widget.type === type) return widget;
  if (widget.metrics === undefined) {
    return {
      ...widget,
      type,
      chartStyle: type === 'echarts' ? widget.chartStyle : undefined,
    };
  }
  const { metrics, dimensions, ...shared } = widget;
  return {
    ...shared,
    type,
    metric: metrics[0] ?? '',
    dimension: type === 'echarts' ? dimensions[0] : undefined,
  };
}

export function expandTableFields(widget: ProposedWidget): ProposedWidget {
  if (widget.type !== 'ag-grid-table' || widget.metrics !== undefined)
    return widget;
  const { metric, dimension, ...shared } = widget;
  return {
    ...shared,
    type: 'ag-grid-table',
    metrics: metric ? [metric] : [],
    dimensions: dimension ? [dimension] : [],
  };
}

interface WidgetPreview {
  type: ProposedWidget['type'];
  props: Record<string, unknown>;
}

interface PreviewFields {
  metrics: ReadonlyMap<string, string>;
  dimensions: ReadonlyMap<string, { label: string; temporal: boolean }>;
}

export function widgetPreview(
  widget: ProposedWidget,
  d3format?: string,
  fields?: PreviewFields,
): WidgetPreview | undefined {
  const { type, datasetId, title, chartStyle, filter } = widget;
  const isTrend = chartStyle === 'line';
  const metric = widget.metric?.trim();
  const dimension = widget.dimension?.trim();
  const metrics = widget.metrics ?? (metric ? [metric] : []);
  const dimensions =
    widget.dimensions ??
    (dimension && type !== 'metric-tile' ? [dimension] : []);
  if (!Number.isSafeInteger(datasetId) || datasetId < 1 || !metrics.length) {
    return undefined;
  }
  if (
    widget.metrics &&
    new Set([...metrics, ...dimensions]).size !==
      metrics.length + dimensions.length
  ) {
    return undefined;
  }

  const dataBinding = {
    datasetId,
    metrics,
    dimensions,
    rowLimit: 100,
    ...((isTrend || (widget.metrics && dimensions.length > 0)) && {
      orderByDimension: true,
    }),
    ...(filter && {
      filters: [
        {
          expressionType: 'SIMPLE',
          clause: 'WHERE',
          subject: filter.column,
          operator: '==',
          comparator: filter.value,
        },
      ],
    }),
  };

  switch (type) {
    case 'metric-tile': {
      if (!metric) return undefined;
      const precision = d3format?.match(/^(?:\.([0-9]))?%$/);
      const fixedPrecision = d3format?.match(/^,?\.([0-9]|10)f$/);
      return {
        type,
        props: {
          dataBinding,
          label: title?.trim() || fields?.metrics.get(metric) || metric,
          ...(precision
            ? { percentage: true, decimals: Number(precision[1] ?? 0) }
            : fixedPrecision && { decimals: Number(fixedPrecision[1]) }),
        },
      };
    }
    case 'ag-grid-table': {
      const columnDefs = widget.metrics && [
        ...dimensions.map(field => {
          const metadata = fields?.dimensions.get(field);
          return {
            field,
            headerName: metadata?.label || field,
            ...(metadata?.temporal && { valueFormat: 'date' }),
          };
        }),
        ...metrics.map(field => ({
          field,
          headerName: fields?.metrics.get(field) || field,
        })),
      ];
      return {
        type,
        props: {
          dataBinding,
          label: title?.trim(),
          ...(columnDefs && { columnDefs }),
        },
      };
    }
    case 'echarts':
      if (!metric || !dimension) return undefined;
      return {
        type,
        props: {
          dataBinding,
          crossFilter: !isTrend,
          echartsOptions: {
            animation: false,
            ...(title?.trim() && { title: { text: title.trim() } }),
            grid: { left: 64, right: 24, bottom: 40, top: 48 },
            tooltip: { trigger: 'axis', renderMode: 'richText' },
            xAxis: {
              type: 'category',
              axisLabel: { hideOverlap: true },
              data: {
                $bind: {
                  source: 'dimension',
                  alias: dimension,
                  ...(isTrend && { format: 'date' }),
                },
              },
            },
            yAxis: { type: 'value' },
            series: [
              {
                type: chartStyle ?? 'bar',
                data: { $bind: { source: 'metric', alias: metric } },
              },
            ],
          },
        },
      };
    default:
      return undefined;
  }
}

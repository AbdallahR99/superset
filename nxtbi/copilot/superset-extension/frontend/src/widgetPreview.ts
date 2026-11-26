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
import type { DashboardContentLocale, DashboardProposal } from '@nxtbi/copilot';

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
  metricFormats?: ReadonlyMap<string, string | undefined>;
}

const RANKED_CATEGORY_LIMIT = 12;

export function rankedChartTitle(title: string, locale: DashboardContentLocale) {
  return `${title} · ${locale === 'ar' ? 'أعلى ١٢' : `Top ${RANKED_CATEGORY_LIMIT}`}`;
}

function percentPrecision(d3format?: string): number | undefined {
  const match = d3format?.match(/^(?:\.([0-9]))?%$/);
  return match ? Number(match[1] ?? 0) : undefined;
}

function tableMetricFormat(d3format?: string) {
  const precision = percentPrecision(d3format);
  if (precision !== undefined) {
    return { valueFormat: 'percent', valueFormatPrecision: precision };
  }
  const fixedPrecision = d3format?.match(/^,?\.([0-9]|10)f$/);
  if (fixedPrecision || /^,?d$/.test(d3format ?? '')) {
    return {
      valueFormat: 'decimal',
      valueFormatPrecision: Number(fixedPrecision?.[1] ?? 0),
    };
  }
  return {};
}

function chartOptions(
  metric: string,
  dimension: string,
  metricLabel: string,
  style: NonNullable<ProposedWidget['chartStyle']>,
  title?: string,
  d3format?: string,
  locale: DashboardContentLocale = 'en',
) {
  const precision = percentPrecision(d3format);
  const percentSign = locale === 'ar' ? '٪' : '%';
  const percentTooltip =
    precision === undefined ? {} : { formatter: `{b0}: {c0}${percentSign}` };
  const metricBinding = {
    $bind: {
      source: 'metric',
      alias: metric,
      ...(precision !== undefined && { format: 'percent' }),
    },
  };
  if (style === 'bar') {
    return {
      animation: false,
      ...(title && { title: { text: title } }),
      grid: { left: 64, right: 24, bottom: 40, top: 48 },
      tooltip: { trigger: 'axis', renderMode: 'richText', ...percentTooltip },
      xAxis: {
        type: 'category',
        axisLabel: { hideOverlap: true },
        data: { $bind: { source: 'dimension', alias: dimension } },
      },
      yAxis: {
        type: 'value',
        ...(precision !== undefined && {
          axisLabel: { formatter: `{value}${percentSign}` },
          minInterval: 10 ** -precision,
        }),
      },
      series: [{ type: 'bar', data: metricBinding }],
    };
  }

  const isTrend = style === 'line';
  const fixedPrecision = d3format?.match(/^\$?,?\.([0-9]|10)f$/);
  const minInterval =
    precision !== undefined
      ? 10 ** -precision
      : fixedPrecision
        ? 10 ** -Number(fixedPrecision[1])
        : /^,?d$/.test(d3format ?? '')
          ? 1
          : undefined;
  const categoryAxis = {
    type: 'category',
    ...(isTrend ? {} : { inverse: true }),
    axisLabel: {
      fontSize: 11,
      hideOverlap: true,
      ...(isTrend ? {} : { width: 148, overflow: 'break' }),
    },
    data: {
      $bind: {
        source: 'dimension',
        alias: dimension,
        ...(isTrend && { format: 'date' }),
      },
    },
  };
  const valueAxis = {
    type: 'value',
    name: metricLabel,
    nameLocation: 'middle',
    nameGap: isTrend ? 54 : 32,
    nameTextStyle: { width: 170, overflow: 'break' },
    axisLabel: {
      fontSize: 11,
      ...(precision !== undefined
        ? { formatter: `{value}${percentSign}` }
        : fixedPrecision &&
          d3format?.startsWith('$') && { formatter: '${value}' }),
    },
    splitLine: {
      lineStyle: {
        color: { $bind: { source: 'theme', token: 'colorBorderSecondary' } },
      },
    },
    ...(minInterval !== undefined && { minInterval }),
  };

  return {
    animation: false,
    ...(title && { title: { text: title } }),
    aria: { enabled: true },
    color: [{ $bind: { source: 'theme', token: 'colorPrimary' } }],
    grid: {
      left: 14,
      right: 14,
      top: 16,
      bottom: 14,
      outerBoundsMode: 'same',
      outerBoundsContain: 'all',
    },
    legend: { show: false },
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
      confine: true,
      axisPointer: { type: isTrend ? 'line' : 'shadow' },
      ...percentTooltip,
    },
    xAxis: isTrend ? categoryAxis : valueAxis,
    yAxis: isTrend ? valueAxis : categoryAxis,
    series: [
      {
        type: isTrend ? 'line' : 'bar',
        name: metricLabel,
        data: metricBinding,
        ...(isTrend
          ? {
              showSymbol: true,
              symbol: 'circle',
              symbolSize: 7,
              smooth: false,
              connectNulls: false,
              lineStyle: { width: 2.5 },
            }
          : { barMaxWidth: 24, realtimeSort: true }),
      },
    ],
  };
}

export function widgetPreview(
  widget: ProposedWidget,
  d3format?: string,
  fields?: PreviewFields,
  locale: DashboardContentLocale = 'en',
  titleLocale = locale,
): WidgetPreview | undefined {
  const { type, datasetId, title, chartStyle, filter } = widget;
  const isTrend = chartStyle === 'line';
  const isRanked = type === 'echarts' && chartStyle === 'ranked-bar';
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
    rowLimit: isRanked ? RANKED_CATEGORY_LIMIT : 100,
    ...(isRanked && { orderByMetric: true }),
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
      const precision = percentPrecision(d3format);
      const fixedPrecision = d3format?.match(/^,?\.([0-9]|10)f$/);
      return {
        type,
        props: {
          dataBinding,
          label: title?.trim() || fields?.metrics.get(metric) || metric,
          ...(precision !== undefined
            ? { percentage: true, decimals: precision }
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
            flex: 2,
            minWidth: 160,
            wrapHeaderText: true,
            autoHeaderHeight: true,
            wrapText: true,
            autoHeight: true,
            ...(metadata?.temporal && { valueFormat: 'date' }),
          };
        }),
        ...metrics.map(field => ({
          field,
          headerName: fields?.metrics.get(field) || field,
          flex: 1,
          minWidth: 132,
          wrapHeaderText: true,
          autoHeaderHeight: true,
          ...tableMetricFormat(fields?.metricFormats?.get(field)),
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
    case 'echarts': {
      if (!metric || !dimension) return undefined;
      const metricLabel = fields?.metrics.get(metric) || metric;
      return {
        type,
        props: {
          dataBinding,
          crossFilter: !isTrend,
          echartsOptions: chartOptions(
            metric,
            dimension,
            metricLabel,
            chartStyle ?? 'bar',
            isRanked
              ? rankedChartTitle(title?.trim() || metricLabel, titleLocale)
              : title?.trim(),
            d3format,
            locale,
          ),
        },
      };
    }
    default:
      return undefined;
  }
}

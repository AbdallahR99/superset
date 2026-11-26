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
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import type { EChartsCoreOption, ECharts } from 'echarts/core';
import {
  BarChart,
  BoxplotChart,
  CustomChart,
  FunnelChart,
  GaugeChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  SankeyChart,
  ScatterChart,
  SunburstChart,
  TreeChart,
  TreemapChart,
} from 'echarts/charts';
import {
  AriaComponent,
  DataZoomComponent,
  GraphicComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import { LabelLayout } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';
import { dashboard as dashboardApi } from '@apache-superset/core';
import { LtrIsolate, styled, useTheme } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import type { QueryFormMetric } from '@superset-ui/core';
import { Flex, Loading, Typography } from '@superset-ui/core/components';
import { useWidgetBus } from '../bus';
import { resolveBindings } from '../resolveBindings';
import type { FilterValueChangedPayload } from '../filterVocabulary';
import type { WidgetProps } from '../types';
import { useWidgetData } from '../useWidgetData';
import { sanitizeEchartsOption } from './echartsSafety';
import {
  applyStructuredEchartsSeries,
  type EchartsChartType,
  type SeriesOverrideValue,
} from './echartsStructuredSeries';
import {
  applyStructuredChrome,
  type EchartsChromeValue,
} from './echartsStructuredChrome';

const TYPE = 'echarts';

type DataBindingSpec = dashboardApi.DataBindingSpec;
interface ChartWidgetProps extends WidgetProps {
  /** The host's displayed title after any dashboard content translation. */
  accessibleTitle?: string;
}

const EMPTY_ROWS: dashboardApi.DataRow[] = [];

const DataToggle = styled.button`
  align-self: flex-end;
  background: transparent;
  border: 0;
  border-radius: ${({ theme }) => theme.borderRadiusSM}px;
  color: ${({ theme }) => theme.colorLink};
  cursor: pointer;
  flex: none;
  font: inherit;
  font-size: ${({ theme }) => theme.fontSizeSM}px;
  min-height: 24px;
  padding-inline: ${({ theme }) => theme.sizeSM}px;
  text-decoration: underline;

  &:focus-visible {
    outline: 2px solid ${({ theme }) => theme.colorPrimary};
    outline-offset: -2px;
  }
`;

const TableScroll = styled.section`
  box-sizing: border-box;
  height: 100%;
  overflow: auto;
  padding-inline: ${({ theme }) => theme.sizeSM}px;

  &:focus-visible {
    outline: 2px solid ${({ theme }) => theme.colorPrimary};
    outline-offset: -2px;
  }

  table {
    border-collapse: separate;
    border-spacing: 0;
    inline-size: 100%;
    font-size: ${({ theme }) => theme.fontSizeSM}px;
  }

  th,
  td {
    border-block-end: 1px solid ${({ theme }) => theme.colorBorderSecondary};
    min-inline-size: 5ch;
    overflow-wrap: anywhere;
    padding: ${({ theme }) => theme.sizeXXS}px ${({ theme }) => theme.sizeXS}px;
    text-align: start;
  }

  thead th {
    background: ${({ theme }) => theme.colorBgContainer};
    inset-block-start: 0;
    position: sticky;
    z-index: 1;
  }

  tbody th {
    font-weight: inherit;
  }

  .chart-number {
    white-space: nowrap;
  }
`;

const visuallyHidden = {
  position: 'absolute',
  width: 1,
  height: 1,
  overflow: 'hidden',
  clipPath: 'inset(50%)',
} as const;

type ChartCell = string | number | boolean | null | undefined;

interface ChartTableData {
  headers: string[];
  rows: ChartCell[][];
  formatValue: (value: number) => string;
  rowHeader?: 'category' | 'name';
}

function optionRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function firstOption(value: unknown) {
  return optionRecord(Array.isArray(value) ? value[0] : value);
}

function chartText(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function chartCell(value: unknown): ChartCell {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }
  return typeof value === 'string' || typeof value === 'boolean'
    ? value
    : undefined;
}

function pointValue(point: unknown) {
  const entry = optionRecord(point);
  return entry && 'value' in entry ? entry.value : point;
}

function chartValueFormatter(
  valueAxis: Record<string, unknown> | undefined,
  locale: string | undefined,
) {
  const template = optionRecord(valueAxis?.axisLabel)?.formatter;
  const interval = valueAxis?.minInterval;
  const precision =
    typeof interval === 'number' && interval > 0 && interval <= 1
      ? -Math.log10(interval)
      : undefined;
  const digits =
    precision !== undefined && Number.isInteger(precision) && precision <= 10
      ? precision
      : undefined;
  const isPercent = template === '{value}%' || template === '{value}٪';
  const formatter = new Intl.NumberFormat(locale, {
    style: isPercent ? 'percent' : 'decimal',
    minimumFractionDigits: digits,
    maximumFractionDigits: isPercent ? (digits ?? 15) : 15,
  });
  return (value: number) => {
    const formatted = formatter.format(isPercent ? value / 100 : value);
    return template === '${value}' ? `$${formatted}` : formatted;
  };
}

function chartTable(
  option: Record<string, unknown>,
  binding: DataBindingSpec | undefined,
  locale: string | undefined,
): ChartTableData | undefined {
  const xAxis = firstOption(option.xAxis);
  const yAxis = firstOption(option.yAxis);
  const categoryOnY = yAxis?.type === 'category';
  const categoryAxis = categoryOnY ? yAxis : xAxis;
  const valueAxis = categoryOnY ? xAxis : yAxis;
  const authoredSeries = Array.isArray(option.series)
    ? option.series
    : [option.series];
  const series = authoredSeries
    .map(optionRecord)
    .filter((item): item is Record<string, unknown> & { data: unknown[] } =>
      Array.isArray(item?.data),
    );

  // A dataset-backed series can share the option with explicitly authored
  // points. Showing just those points would omit part of the chart.
  if (!series.length || series.length !== authoredSeries.length)
    return undefined;

  const categories = categoryAxis?.data;
  if (
    categoryAxis &&
    Array.isArray(categories) &&
    (categoryAxis.type === undefined || categoryAxis.type === 'category') &&
    valueAxis?.type !== 'category' &&
    [option.xAxis, option.yAxis].every(
      axis => !Array.isArray(axis) || axis.length === 1,
    ) &&
    series.every(
      item =>
        (item.type === 'bar' ||
          item.type === 'line' ||
          item.type === 'scatter') &&
        (item.xAxisIndex ?? 0) === 0 &&
        (item.yAxisIndex ?? 0) === 0 &&
        item.xAxisId === undefined &&
        item.yAxisId === undefined &&
        item.encode === undefined &&
        (item.coordinateSystem === undefined ||
          item.coordinateSystem === 'cartesian2d') &&
        item.data.length <= categories.length &&
        item.data.every(point => {
          const value = pointValue(point);
          return value == null || chartCell(value) !== undefined;
        }),
    )
  ) {
    return {
      headers: [
        chartText(categoryAxis.name) ||
          binding?.dimensions?.[0] ||
          t('Category'),
        ...series.map(
          (item, index) =>
            chartText(item.name) ||
            (series.length === 1 ? chartText(valueAxis?.name) : '') ||
            (typeof binding?.metrics?.[index] === 'string'
              ? binding.metrics[index]
              : '') ||
            (series.length === 1 ? t('Value') : `${t('Series')} ${index + 1}`),
        ),
      ],
      rows: series.some(item => item.data.length)
        ? categories.map((category, index) => [
            chartCell(pointValue(category)),
            ...series.map(item => chartCell(pointValue(item.data[index]))),
          ])
        : [],
      formatValue: chartValueFormatter(valueAxis, locale),
      rowHeader: 'category',
    };
  }

  if (series.length === 1) {
    const [item] = series;
    if (
      item.type === 'pie' ||
      item.type === 'funnel' ||
      item.type === 'gauge'
    ) {
      return {
        headers: [t('Name'), chartText(item.name) || t('Value')],
        rows: item.data.map((point, index) => {
          const entry = optionRecord(point);
          return [
            chartCell(entry?.name) ?? index + 1,
            chartCell(pointValue(point)),
          ];
        }),
        formatValue: chartValueFormatter(undefined, locale),
        rowHeader: 'name',
      };
    }
  }
  return undefined;
}

/** The one field of ECharts' own click-event payload this widget reads — a data point's category/name, exactly what a bar/pie/etc. click carries for a categorical series. */
interface EchartsClickParams {
  name?: string;
}

// Registers the renderer plus a broad set of chart/component types, once, at
// module load. Mirrors plugin-chart-echarts's own Echart.tsx registration —
// that component isn't reusable here (not part of the package's public
// exports, and has a Redux dependency this page has no reason to take on),
// and nothing else guarantees these are registered before a chart renders:
// a ChartPlugin's registration is metadata-only, and the real render module
// (with its own `use([...])` call) only loads lazily the first time that
// specific plugin actually renders — which never happens on this page,
// since it bypasses ChartPlugin/SuperChart entirely. authored options can
// use any of these series/component types, hence registering broadly rather
// than guessing which ones this page will need.
echarts.use([
  CanvasRenderer,
  BarChart,
  BoxplotChart,
  CustomChart,
  FunnelChart,
  GaugeChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  SankeyChart,
  ScatterChart,
  SunburstChart,
  TreeChart,
  TreemapChart,
  AriaComponent,
  DataZoomComponent,
  GraphicComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  LegendComponent,
  ToolboxComponent,
  TooltipComponent,
  TitleComponent,
  VisualMapComponent,
  LabelLayout,
]);

/**
 * Tracks an element's rendered pixel size — ECharts has no self-sizing (it
 * only reacts to explicit `resize({width, height})` calls), so whatever
 * renders it owns measuring the DOM. This measures both dimensions: a grid
 * item's cell is always a definite pixel box (its column share of the
 * container's width, its `rowSpan × rowUnit` height, both enforced by the
 * parent grid — see `RootGrid`), so there's no case here where a
 * measured size is ambiguous or collapses to zero the way an unconstrained
 * flex height could.
 */
function useElementSize() {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) {
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return [ref, size] as const;
}

const GRID_INSET = 8;
const LEGEND_BAND = 32;

/**
 * ECharts' own grid default reserves fixed 65/80px bands and 15%/10% sides,
 * which leaves most of a small widget empty. Without an authored `grid`, the
 * plot fills the widget and ECharts shrinks it to fit axis labels and names,
 * leaving room for a top or bottom legend.
 */
function withDefaultGrid(option: Record<string, unknown>) {
  if (option.grid != null || (option.xAxis == null && option.yAxis == null)) {
    return option;
  }
  const legend = (
    Array.isArray(option.legend) ? option.legend[0] : option.legend
  ) as Record<string, unknown> | undefined;
  const legendShown = legend != null && legend.show !== false;
  const legendBottom =
    legendShown && (legend.top === 'bottom' || legend.bottom != null);
  const legendTop =
    legendShown &&
    !legendBottom &&
    legend.top !== 'middle' &&
    legend.left !== 'left' &&
    legend.left !== 'right';
  return {
    ...option,
    grid: {
      left: GRID_INSET,
      right: GRID_INSET,
      top: GRID_INSET + (legendTop ? LEGEND_BAND : 0),
      bottom: GRID_INSET + (legendBottom ? LEGEND_BAND : 0),
      outerBoundsMode: 'same',
      outerBoundsContain: 'all',
    },
  };
}

/**
 * A minimal, self-contained ECharts canvas — deliberately not the
 * `<Echart>` wrapper `plugin-chart-echarts` uses internally (that component
 * isn't part of the package's public exports, and pulls in a Redux
 * dependency this prototype has no reason to take on). The renderer and
 * chart/component modules it needs are registered by this module's own
 * `use([...])` call above, so this only needs to init/setOption/resize.
 */
function EchartsCanvas({
  width,
  height,
  option,
  onPointClick,
}: {
  width: number;
  height: number;
  option: EChartsCoreOption;
  onPointClick?: (params: EchartsClickParams) => void;
}) {
  const divRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts>();
  // The click listener is bound once, in the same effect that creates the
  // chart instance — re-binding it on every `onPointClick` identity change
  // would mean adding/removing an ECharts listener on every render for no
  // reason. A ref always reads the *latest* callback instead, the same
  // "stable subscription, fresh closure" split any addEventListener-based
  // effect needs once the handler itself isn't the effect's only dependency.
  const onPointClickRef = useRef(onPointClick);
  useEffect(() => {
    onPointClickRef.current = onPointClick;
  }, [onPointClick]);

  useEffect(() => {
    if (!divRef.current) return undefined;
    chartRef.current = echarts.init(divRef.current);
    chartRef.current.on('click', (params: EchartsClickParams) =>
      onPointClickRef.current?.(params),
    );
    return () => {
      chartRef.current?.dispose();
      chartRef.current = undefined;
    };
  }, []);

  useEffect(() => {
    if (width > 0 && height > 0) {
      chartRef.current?.resize({ width, height });
    }
  }, [width, height]);

  useEffect(() => {
    // notMerge: true — an edit can change series/axis shapes drastically
    // between calls (e.g. pie -> bar), so stale config from the previous
    // option must not linger.
    chartRef.current?.setOption(option, true);
  }, [option]);

  return <div ref={divRef} style={{ width, height }} />;
}

/**
 * The built-in `echarts` widget — registered like any other widget
 * (see `registry.ts`). Fetches its `dataBinding`
 * (generic, viz_type-less — see `dataClient.ts`), resolves any `$bind`
 * markers in its `echartsOptions` against the results, and draws the
 * result. No `SuperChart`/`ChartPlugin`/`buildQuery`/`transformProps`
 * involved — the author writes close to a real ECharts `option` directly.
 *
 * `props.crossFilter: true` turns a click on a data point into a filter —
 * this widget emitting `dashboard.VALUE_CHANGED_EVENT` on itself, the exact
 * same event/payload shape `FilterSelectWidget` emits (see
 * `filterVocabulary.ts`). Nothing downstream (`activeFilters.ts`,
 * every other query-bound widget reading the same dataset) knows or cares
 * that the source this time is a chart reacting to its own click rather
 * than a purpose-built filter control — that's the entire point of the
 * event bus being general rather than filter-specific. A standalone
 * `echarts` widget with `crossFilter` unset behaves exactly as it always
 * has; this is additive, not a mode switch.
 */
export default function ChartWidget(widgetProps: ChartWidgetProps) {
  const { accessibleTitle, instanceId, props } = widgetProps;
  const bus = useWidgetBus();
  const theme = useTheme();
  const [containerRef, size] = useElementSize();
  const contentId = useId();
  const captionId = useId();
  const [showTable, setShowTable] = useState(false);
  const dataBinding = props.dataBinding as DataBindingSpec | undefined;
  // Fetches for the binding and the filters that apply to this widget, and
  // re-renders it on every bus emit (see `useWidgetData`).
  const data = useWidgetData(
    TYPE,
    widgetProps,
    'This chart widget has no dataBinding.',
  );
  const rows = dataBinding ? data.result?.rows : EMPTY_ROWS;

  // Cross-filtering: opt-in (see `props.crossFilter`) and, for this
  // prototype, scoped to the *first* dimension only — a data point from a
  // multi-dimension query (e.g. a stacked bar grouped by two columns)
  // could in principle resolve a constraint per dimension, but nothing
  // here disambiguates which of ECharts' click fields maps to which
  // dimension beyond the category name, so a second dimension is simply
  // not filterable by click yet.
  const crossFilterColumn = dataBinding?.dimensions?.[0];
  const crossFilterEnabled =
    Boolean(props.crossFilter) && crossFilterColumn !== undefined;
  const currentSelection = bus.getValue(
    instanceId,
    dashboardApi.VALUE_CHANGED_EVENT,
  ) as FilterValueChangedPayload | undefined;

  const handlePointClick = (params: EchartsClickParams) => {
    if (!crossFilterEnabled || !crossFilterColumn || !dataBinding) return;
    const clickedValue = params.name;
    if (clickedValue == null) return;

    const current = bus.getValue(
      instanceId,
      dashboardApi.VALUE_CHANGED_EVENT,
    ) as FilterValueChangedPayload | undefined;
    // Clicking the same point again clears the cross-filter rather than
    // re-asserting it — the same toggle a filter's own `allowClear` gives
    // a viewer, just reached by clicking the data itself instead of an
    // "x" on a control.
    const alreadySelected =
      current?.resolved?.column === crossFilterColumn &&
      current.resolved.value === clickedValue;

    bus.emit(
      instanceId,
      dashboardApi.VALUE_CHANGED_EVENT,
      alreadySelected
        ? { selection: null, resolved: null }
        : {
            selection: clickedValue,
            resolved: {
              column: crossFilterColumn,
              operator: 'EQUALS',
              value: clickedValue,
              datasource: dataBinding.datasetId,
            },
          },
    );
  };

  const chartType = props.chartType as EchartsChartType | null | undefined;
  const customizeSeries = (
    props.customize as
      | { series?: Record<string, SeriesOverrideValue> }
      | undefined
  )?.series;
  const chrome = props.chrome as EchartsChromeValue | undefined;
  const authoredOption = props.echartsOptions as
    | Record<string, unknown>
    | undefined;
  const title =
    chartText(accessibleTitle) ||
    chartText(chrome?.titleText) ||
    chartText(firstOption(authoredOption?.title)?.text) ||
    t('Chart');
  const locale =
    globalThis.document?.documentElement.lang.replaceAll('_', '-') || undefined;

  const option = useMemo(() => {
    if (!rows) return undefined;
    const resolved = resolveBindings(authoredOption ?? {}, { rows, theme });
    const withStructuredSeries = applyStructuredEchartsSeries(
      resolved,
      chartType,
      (dataBinding?.metrics ?? []) as QueryFormMetric[],
      rows,
      customizeSeries,
    );
    const withStructuredChrome = applyStructuredChrome(
      withStructuredSeries,
      chrome,
    );
    // The chart's name is drawn by the widget's header, which reads it from
    // this same option (see `widgetLabel`). Leaving it here too would print it
    // twice, at two sizes, in two places — and the header's copy is the one
    // that sits where every other widget's name sits.
    const withoutTitle = { ...withStructuredChrome };
    delete withoutTitle.title;
    // Last, on the finished option: nothing after this adds authored values.
    return sanitizeEchartsOption(withDefaultGrid(withoutTitle));
  }, [
    authoredOption,
    chartType,
    customizeSeries,
    chrome,
    dataBinding,
    rows,
    theme,
  ]);

  const table = useMemo<ChartTableData | undefined>(() => {
    if (!option) return undefined;
    const plotted = chartTable(option, dataBinding, locale);
    if (plotted) return plotted;

    // Unstructured options can have a more complex shape (e.g. scatter).
    // The authorized query result still gives readers the source values.
    // Structured series omit explicitly hidden metrics in the plotted view.
    const { result } = data;
    if (chartType || !result?.columns?.length) return undefined;
    return {
      headers: result.columns,
      rows: result.rows.map(row =>
        result.columns.map(column => chartCell(row[column])),
      ),
      formatValue: chartValueFormatter(undefined, locale),
    };
  }, [chartType, data.result, dataBinding, locale, option]);
  const error = dataBinding || !table?.rows.length ? data.error : undefined;
  const canInspect = !error && table !== undefined;
  const filterValues =
    showTable &&
    table?.rowHeader === 'category' &&
    crossFilterEnabled &&
    crossFilterColumn
      ? new Set(rows?.map(row => row[crossFilterColumn]))
      : undefined;

  return (
    <div
      data-test={`chart-${instanceId}`}
      // `WidgetView`'s own root has an onClick that selects this widget on
      // *any* click inside it, native-DOM-bubbling up to it regardless of
      // what ECharts does with the same click — ECharts' own click handler
      // (see `EchartsCanvas`) gets a synthetic params object, not the DOM
      // event, so there's no stopping propagation from inside it. This is
      // the one point in the tree between the canvas and that handler this
      // widget still controls, so it's where a cross-filter click has to be
      // kept from also reselecting the widget — deliberately not taught to
      // `WidgetView` itself, which has no business knowing what
      // `crossFilter` is. `role` says what's true regardless: this div
      // gains no interactive semantics of its own from the handler below
      // (it neither needs nor gets a keyboard equivalent) — the actual
      // interactive surface is ECharts' own canvas, which isn't part of the
      // accessibility tree at all.
      role="presentation"
      // The other half of the fix, and the one that actually matters:
      // `RootGrid`'s GridStack instance treats a press *anywhere* in this
      // widget as the start of a drag unless the target matches its own
      // cancel selector (see `cancelSelectorFor`) — GridStack has no
      // built-in exemption for an arbitrary `<canvas>` the way it does for
      // a plain form control, so without this attribute the press never
      // reaches ECharts' own click detection at all, drag or not. The
      // `onClick`/`role` above only guard what happens *after* a click
      // does fire; this is what lets one fire in the first place.
      // `undefined` (not `false`) when disabled — a `data-*` attribute set
      // to `false` still renders as the string `"false"` and would still
      // match `[data-widget-interactive]`, which only tests presence.
      data-widget-interactive={crossFilterEnabled || undefined}
      onClick={
        crossFilterEnabled ? event => event.stopPropagation() : undefined
      }
      style={{
        // Fills the box its container gives this
        // widget — that wrapper is always a definite pixel box (its column
        // share of the container's width, its `rowSpan × rowUnit` height),
        // so this is never zero or ambiguous.
        width: '100%',
        height: '100%',
        // Surface, border and corners belong to the card a host
        // draws around this widget and the name above it, so that the name is
        // inside the frame rather than over it.
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {canInspect && (
        <DataToggle
          type="button"
          aria-expanded={showTable}
          aria-controls={contentId}
          aria-describedby={captionId}
          data-widget-interactive
          onClick={event => {
            event.stopPropagation();
            setShowTable(open => !open);
          }}
        >
          {t('View as table')}
        </DataToggle>
      )}
      <span id={captionId} style={visuallyHidden}>
        {title}
      </span>
      <div
        ref={containerRef}
        id={contentId}
        style={{ flex: '1 1 0', minHeight: 0, minWidth: 0, overflow: 'hidden' }}
      >
        {error && (
          <Flex align="center" justify="center" style={{ height: '100%' }}>
            <Typography.Text type="danger">{error}</Typography.Text>
          </Flex>
        )}
        {!error && !option && (
          <Flex align="center" justify="center" style={{ height: '100%' }}>
            <Loading position="inline-centered" size="s" />
          </Flex>
        )}
        {!error && option && size.width > 0 && size.height > 0 && (
          <div hidden={canInspect && showTable}>
            {/* Axes, legends and tooltips keep their physical layout. */}
            <LtrIsolate>
              <EchartsCanvas
                width={size.width}
                height={size.height}
                option={option}
                onPointClick={handlePointClick}
              />
            </LtrIsolate>
          </div>
        )}
        {canInspect && showTable && (
          <TableScroll
            aria-labelledby={captionId}
            tabIndex={table.rows.length ? 0 : undefined}
            data-widget-interactive
          >
            {table.rows.length === 0 ? (
              <output>{t('No data')}</output>
            ) : (
              <table>
                <caption style={visuallyHidden}>{title}</caption>
                <thead>
                  <tr>
                    {table.headers.map((header, index) => (
                      <th scope="col" key={`${index}-${header}`}>
                        <bdi>{header}</bdi>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row, rowIndex) => (
                    // Some series have repeated categories and no point IDs.
                    // eslint-disable-next-line react/no-array-index-key
                    <tr key={rowIndex}>
                      {row.map((value, index) => {
                        const isRowHeader = index === 0 && table.rowHeader;
                        const isNumber = typeof value === 'number';
                        const cell = isNumber
                          ? isRowHeader
                            ? String(value)
                            : table.formatValue(value)
                          : value == null
                            ? t('N/A')
                            : String(value);
                        const content = (
                          <bdi
                            className={isNumber ? 'chart-number' : undefined}
                          >
                            {cell}
                          </bdi>
                        );
                        if (isRowHeader) {
                          return (
                            <th scope="row" key={table.headers[index]}>
                              {typeof value === 'string' &&
                              filterValues?.has(value) ? (
                                <DataToggle
                                  type="button"
                                  title={t('Filter by')}
                                  aria-pressed={
                                    currentSelection?.resolved?.column ===
                                      crossFilterColumn &&
                                    currentSelection?.resolved?.value === value
                                  }
                                  onClick={() =>
                                    handlePointClick({ name: value })
                                  }
                                >
                                  {content}
                                </DataToggle>
                              ) : (
                                content
                              )}
                            </th>
                          );
                        }
                        return (
                          <td key={`${index}-${table.headers[index]}`}>
                            {content}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TableScroll>
        )}
      </div>
    </div>
  );
}

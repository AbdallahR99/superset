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
import {
  Component,
  useContext,
  useEffect,
  useId,
  useMemo,
  useState,
  type CSSProperties,
  type ErrorInfo,
  type ReactNode,
} from 'react';
import { dashboard as dashboardApi } from '@apache-superset/core';
import { useDirection } from '@apache-superset/core/theme';
import { Flex, Loading, Typography } from '@superset-ui/core/components';
import { useWidgetBus } from '../bus';
import { useWidgetDataClient } from '../dataClient';
import {
  toError,
  useWidgetErrorReporter,
  type WidgetErrorInfo,
} from '../errors';
import { WidgetComponentsContext, getWidgetComponent } from '../registry';
import type { DataBindingSpec, SavedWidget, WidgetDataClient } from '../types';
import { useExtensionWidget } from './extensionLoader';

export interface CommonWidgetProps {
  /** Identity on the bus; defaults to a stable generated id. */
  instanceId?: string;
  className?: string;
  style?: CSSProperties;
  /** Shown while a saved widget loads. */
  fallback?: ReactNode;
  renderError?: (error: Error) => ReactNode;
  /**
   * Render the widget's own title above it. In a dashboard the title lives in
   * the builder's widget header, so the widget itself never draws it.
   */
  showTitle?: boolean;
}

export type WidgetElementProps = CommonWidgetProps &
  (
    | { type: string; props?: Record<string, unknown>; id?: never }
    | { id: string; type?: never; props?: never }
  );

function widgetTitle(
  type: string,
  props: Record<string, unknown>,
): string | undefined {
  if (type !== 'echarts') return undefined;
  const chromeText = (props.chrome as { titleText?: unknown } | undefined)
    ?.titleText;
  const rawTitle = (props.echartsOptions as { title?: unknown } | undefined)
    ?.title;
  const first = Array.isArray(rawTitle) ? rawTitle[0] : rawTitle;
  const text =
    typeof chromeText === 'string' && chromeText.trim() !== ''
      ? chromeText
      : (first as { text?: unknown } | undefined)?.text;
  return typeof text === 'string' && text.trim() !== ''
    ? text.trim()
    : undefined;
}

function DefaultError({ error }: { error: Error }) {
  return (
    <Flex
      align="center"
      justify="center"
      style={{ width: '100%', height: '100%' }}
    >
      <Typography.Text type="danger">{error.message}</Typography.Text>
    </Flex>
  );
}

class WidgetErrorBoundary extends Component<
  {
    renderError?: (error: Error) => ReactNode;
    onError: (error: Error) => void;
    children: ReactNode;
  },
  { error?: Error }
> {
  state: { error?: Error } = {};

  static getDerivedStateFromError(error: unknown) {
    return { error: toError(error) };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('[superset-widgets]', error, info.componentStack);
    this.props.onError(toError(error));
  }

  render() {
    const { error } = this.state;
    if (error) {
      return this.props.renderError?.(error) ?? <DefaultError error={error} />;
    }
    return this.props.children;
  }
}

interface LoadedDefinition {
  client: WidgetDataClient;
  id: string;
  widget?: SavedWidget;
  error?: Error;
}

/**
 * One Superset widget, rendered in place: either an inline definition
 * (`type` + `props`) or a widget saved in Superset (`id`). Must be inside a
 * `SupersetProvider`.
 *
 * Nothing here throws while rendering: a definition that cannot be loaded, a
 * type nobody draws and a widget that fails are each shown in the widget's
 * own box (or through `renderError`) and reported to the provider's
 * `onError`.
 */
export function Widget(widgetProps: WidgetElementProps) {
  const {
    instanceId,
    className,
    style,
    fallback,
    renderError,
    showTitle = true,
    id,
  } = widgetProps;
  const reactId = useId();
  const bus = useWidgetBus();
  const client = useWidgetDataClient();
  const reportError = useWidgetErrorReporter();
  const providerComponents = useContext(WidgetComponentsContext);
  const direction = useDirection();
  // `useId` repeats across React roots, so two roots sharing one bus would
  // emit under the same id and hide each other's filters. A bus that hands
  // out ids is asked for one instead, kept for as long as the bus is.
  const allocatedId = useMemo(() => bus.createSourceId?.(), [bus]);
  const busId = instanceId ?? allocatedId ?? `widget${reactId}`;
  const [loaded, setLoaded] = useState<LoadedDefinition>();

  useEffect(() => {
    if (!id) return undefined;
    const fail = (error: Error) => {
      setLoaded({ client, id, error });
      reportError(error, {
        phase: 'definition',
        instanceId: busId,
        savedId: id,
      });
    };
    if (!client.getSavedWidget) {
      fail(new Error('This data client cannot load saved widgets.'));
      return undefined;
    }
    // Aborted when the id or the client changes and on unmount: the
    // definition asked for before never replaces the one asked for after.
    const controller = new AbortController();
    const { signal } = controller;
    let pending: Promise<SavedWidget>;
    try {
      pending = client.getSavedWidget(id, { signal });
    } catch (thrown) {
      pending = Promise.reject(thrown);
    }
    pending.then(
      widget => {
        if (!signal.aborted) setLoaded({ client, id, widget });
      },
      (reason: unknown) => {
        if (!signal.aborted) fail(toError(reason));
      },
    );
    return () => controller.abort();
  }, [busId, client, id, reportError]);

  // A widget that leaves must not keep filtering the ones that stay.
  useEffect(
    () => () => {
      if (bus.forget) {
        bus.forget(busId);
        return;
      }
      const value = bus.getValue(busId, dashboardApi.VALUE_CHANGED_EVENT) as
        | { resolved?: unknown }
        | undefined;
      if (value?.resolved) {
        bus.emit(busId, dashboardApi.VALUE_CHANGED_EVENT, {
          selection: null,
          resolved: null,
        });
      }
    },
    [bus, busId],
  );

  // What was loaded counts only for the id and the client on screen.
  const current =
    id && loaded && loaded.id === id && loaded.client === client
      ? loaded
      : undefined;
  const saved = current?.widget;
  const loadError = current?.error;
  const type = id ? saved?.widget_type : widgetProps.type;
  const props = id ? saved?.props : (widgetProps.props ?? {});
  // A provider's own widget types come first, then the page-wide registry. A
  // type neither has may still belong to an extension, whose frontend is
  // fetched from Superset the first time one of its widgets renders.
  const registered = type
    ? (providerComponents?.[type] ?? getWidgetComponent(type))
    : undefined;
  const extension = useExtensionWidget(registered ? undefined : type, busId);
  const WidgetComponent = registered ?? extension.component;
  const unknownType =
    type && props && !WidgetComponent && !extension.loading && !extension.error
      ? type
      : undefined;
  const errorInfo = useMemo<WidgetErrorInfo>(
    () => ({
      phase: 'render',
      instanceId: busId,
      widgetType: type,
      savedId: id,
    }),
    [busId, type, id],
  );

  useEffect(() => {
    if (unknownType) {
      reportError(new Error(`Unknown widget type "${unknownType}"`), errorInfo);
    }
  }, [unknownType, errorInfo, reportError]);

  let content: ReactNode;
  if (loadError) {
    content = renderError?.(loadError) ?? <DefaultError error={loadError} />;
  } else if (extension.error) {
    content = renderError?.(extension.error) ?? (
      <DefaultError error={extension.error} />
    );
  } else if (!type || !props || extension.loading) {
    content = fallback ?? <Loading position="inline-centered" size="s" />;
  } else if (!WidgetComponent) {
    const error = new Error(`Unknown widget type "${type}"`);
    content = renderError?.(error) ?? <DefaultError error={error} />;
  } else {
    content = (
      // Keyed by what is drawn, so an error caught for one definition does
      // not stay on screen for the next.
      <WidgetErrorBoundary
        key={`${type}:${id ?? ''}`}
        renderError={renderError}
        onError={error => reportError(error, errorInfo)}
      >
        <WidgetComponent instanceId={busId} props={props} savedId={id} />
      </WidgetErrorBoundary>
    );
  }

  const title =
    showTitle && type && props ? widgetTitle(type, props) : undefined;

  return (
    <Flex
      vertical
      gap="small"
      className={className}
      style={{ position: 'relative', width: '100%', height: '100%', ...style }}
      data-superset-widget={type}
      // Text follows the provider's direction even in a page that declares
      // another one (or none).
      dir={direction}
    >
      {title && (
        <Typography.Text strong ellipsis style={{ flex: 'none' }}>
          {title}
        </Typography.Text>
      )}
      <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
        {content}
      </div>
    </Flex>
  );
}

function splitCommon<T extends CommonWidgetProps>(
  all: T,
): [CommonWidgetProps, Omit<T, keyof CommonWidgetProps>] {
  const {
    instanceId,
    className,
    style,
    fallback,
    renderError,
    showTitle,
    ...rest
  } = all;
  return [
    { instanceId, className, style, fallback, renderError, showTitle },
    rest,
  ];
}

export interface ChartProps extends CommonWidgetProps {
  dataBinding: DataBindingSpec;
  /** A near-raw ECharts option; `$bind` markers splice in query results. */
  echartsOptions?: Record<string, unknown>;
  chartType?: 'bar' | 'line' | 'scatter';
  chrome?: Record<string, unknown>;
  customize?: Record<string, unknown>;
  crossFilter?: boolean;
}

export interface MetricTileProps extends CommonWidgetProps {
  dataBinding: DataBindingSpec;
  label?: string;
  prefix?: string;
  suffix?: string;
  decimals?: number;
}

export interface TableProps extends CommonWidgetProps {
  dataBinding: DataBindingSpec;
  /**
   * Declarative column settings only (`field`, `headerName`, `width`,
   * `pinned`, `hide`, ...). Anything AG Grid would evaluate or call is
   * dropped; see `sanitizeColumnDefs`.
   */
  columnDefs?: Record<string, unknown>[];
}

export interface FilterSelectProps extends CommonWidgetProps {
  datasetId: number;
  column: string;
  options?: string[];
  defaultSelection?: string[];
  scope?: { targets?: string[] };
}

export interface MarkdownProps extends CommonWidgetProps {
  /** Markdown source. Raw HTML in it is sanitised before it is rendered. */
  content: string;
}

export function Chart(chartProps: ChartProps) {
  const [common, props] = splitCommon(chartProps);
  return <Widget {...common} type="echarts" props={{ ...props }} />;
}

export function MetricTile(tileProps: MetricTileProps) {
  const [common, props] = splitCommon(tileProps);
  return <Widget {...common} type="metric-tile" props={{ ...props }} />;
}

export function Table(tableProps: TableProps) {
  const [common, props] = splitCommon(tableProps);
  return <Widget {...common} type="ag-grid-table" props={{ ...props }} />;
}

export function FilterSelect(filterProps: FilterSelectProps) {
  const [common, props] = splitCommon(filterProps);
  return <Widget {...common} type="filter.select" props={{ ...props }} />;
}

export function Markdown(markdownProps: MarkdownProps) {
  const [common, props] = splitCommon(markdownProps);
  return <Widget {...common} type="markdown" props={{ ...props }} />;
}

Widget.displayName = 'Widget';
Chart.displayName = 'Chart';
MetricTile.displayName = 'MetricTile';
Table.displayName = 'Table';
FilterSelect.displayName = 'FilterSelect';
Markdown.displayName = 'Markdown';

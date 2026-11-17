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
import { styled, useTheme } from '@apache-superset/core/theme';
import { Flex, Loading, Typography } from '@superset-ui/core/components';
import { Icons } from '@superset-ui/core/components/Icons';
import type { WidgetProps } from '../types';
import { useWidgetData } from '../useWidgetData';

const TYPE = 'metric-tile';

type Theme = ReturnType<typeof useTheme>;

interface DeltaSpec {
  value: number;
  direction?: 'up' | 'down' | 'flat';
  suffix?: string;
}

// The && bumps specificity above antd's own Title margin rules, which a
// plain inline style prop can't override (same trick as
// `DashboardBuilderV2`'s own `HeaderTitle`) — without it the default margin
// throws off vertical centering against the label/delta stacked below it.
const BigNumber = styled(Typography.Title)`
  && {
    margin: 0;
    line-height: 1.1;
  }
`;

function formatNumber(value: unknown, decimals: number): string {
  const num = typeof value === 'number' ? value : Number(value);
  if (value == null || Number.isNaN(num))
    return value == null ? '—' : String(value);
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);
}

function DeltaIndicator({ delta, theme }: { delta: DeltaSpec; theme: Theme }) {
  const direction =
    delta.direction ??
    (delta.value > 0 ? 'up' : delta.value < 0 ? 'down' : 'flat');
  const color =
    direction === 'up'
      ? theme.colorSuccess
      : direction === 'down'
        ? theme.colorError
        : theme.colorTextSecondary;
  const Icon =
    direction === 'up'
      ? Icons.CaretUpOutlined
      : direction === 'down'
        ? Icons.CaretDownOutlined
        : undefined;

  return (
    <Flex align="center" gap={4}>
      {Icon && <Icon style={{ color }} />}
      <Typography.Text style={{ color }}>
        {formatNumber(Math.abs(delta.value), 1)}
        {delta.suffix ?? ''}
      </Typography.Text>
    </Flex>
  );
}

/**
 * The built-in `metric-tile` widget ("big number") — registered
 * like any other widget (see `registry.ts`). Fetches its
 * `dataBinding` the same generic way `ChartWidget`/`AgGridTableWidget` do, and
 * renders the first result row's value directly as text — no ECharts
 * gauge/`graphic` text workaround and no `$bind` splicing, since there is
 * nothing here to splice into: the whole point of this widget is a single
 * live number.
 *
 * `dataBinding` is expected to resolve one column (one metric, no
 * `dimensions`) — the value shown is always the *first* row's value for
 * that column; a tile shows one number, so grouping isn't meaningful here
 * the way it is for a chart or table.
 */
export default function MetricTileWidget(widgetProps: WidgetProps) {
  const { props } = widgetProps;
  const theme = useTheme();
  const { result, error, loading } = useWidgetData(
    TYPE,
    widgetProps,
    'This metric tile has no dataBinding.',
  );
  // One number: the first row's value for the first column.
  const [column] = result?.columns ?? [];
  const columnLabel = column ?? null;
  const value = column ? result?.rows[0]?.[column] : undefined;
  const loaded = !loading && result !== undefined;

  const decimals = (props.decimals as number | undefined) ?? 0;
  const prefix = (props.prefix as string | undefined) ?? '';
  const suffix = (props.suffix as string | undefined) ?? '';
  const label = (props.label as string | undefined) ?? columnLabel ?? '';
  const delta = props.delta as DeltaSpec | undefined;

  return (
    <Flex
      vertical
      justify="center"
      style={{
        // Fills the box its container gives this
        // widget — always a definite pixel box, same as `ChartWidget`.
        width: '100%',
        height: '100%',
        // Surface, border, corners and inset all belong to the card
        // `WidgetView` draws around this widget and the name above
        // it, so that the name is inside the frame rather than over it.
        overflow: 'hidden',
      }}
    >
      {error && <Typography.Text type="danger">{error}</Typography.Text>}
      {!error && !loaded && <Loading position="inline-centered" size="s" />}
      {!error && loaded && (
        <>
          <BigNumber level={2}>
            {prefix}
            {formatNumber(value, decimals)}
            {suffix}
          </BigNumber>
          {label && (
            <Typography.Text
              type="secondary"
              style={{ marginTop: theme.marginXS }}
            >
              {label}
            </Typography.Text>
          )}
          {delta && (
            <div style={{ marginTop: theme.marginXS }}>
              <DeltaIndicator delta={delta} theme={theme} />
            </div>
          )}
        </>
      )}
    </Flex>
  );
}

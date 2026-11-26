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
import type { CSSProperties, ReactElement } from 'react';
import { css, styled, useTheme } from '@apache-superset/core/theme';
import { useDashboardStore, useDashboardRevision } from './store';
import { DASHBOARD_VIEW_CONTAINER, resolveGridMetrics } from './layoutStyle';
import type { GridMetrics } from './layoutStyle';
import { packChildLayout } from './gridPacking';
// eslint-disable-next-line import/no-cycle
import WidgetView from './WidgetView';

const Surface = styled.div`
  container: ${DASHBOARD_VIEW_CONTAINER} / inline-size;
  inline-size: 100%;
  min-inline-size: 0;
`;

const Layout = styled.div<{ $metrics: GridMetrics }>`
  ${({ $metrics, theme }) => css`
    display: grid;
    grid-template-columns: repeat(${$metrics.columns}, minmax(0, 1fr));
    grid-auto-rows: ${$metrics.rowUnitPx}px;
    gap: ${$metrics.gap}px;

    > [data-dashboard-grid-item] {
      grid-column: var(--dashboard-grid-column);
      grid-row: var(--dashboard-grid-row);
      inline-size: 100%;
      block-size: 100%;
      min-inline-size: 0;
    }

    @container ${DASHBOARD_VIEW_CONTAINER} (inline-size <= ${theme.screenSMMax}px) {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      grid-auto-rows: auto;
      gap: min(${$metrics.gap}px, ${theme.sizeUnit * 2}px);

      > [data-dashboard-grid-item] {
        grid-column: 1 / -1;
        grid-row: auto;
        block-size: var(--dashboard-grid-block-size);
      }

      > [data-dashboard-grid-item='metric-tile'] {
        block-size: auto;
        min-block-size: 7.25rem;
      }

      > [data-dashboard-grid-item='echarts'] {
        block-size: clamp(16rem, var(--dashboard-grid-block-size), 18rem);
      }

      > [data-dashboard-grid-item='markdown'] {
        block-size: auto;
        overflow-wrap: anywhere;
      }
    }

    @container ${DASHBOARD_VIEW_CONTAINER} (320px <= inline-size <= ${theme.screenSMMax}px) {
      > [data-dashboard-paired-tile] {
        grid-column: auto;
      }
    }
  `}
`;

/**
 * Read-only counterpart to `RootGrid`: the same packing (so a viewer sees the
 * layout the author arranged), with compact tiles and full-width charts
 * when space is limited.
 */
export default function StaticGrid({
  nodeId,
}: {
  nodeId: string;
}): ReactElement | null {
  const store = useDashboardStore();
  useDashboardRevision(store);
  const theme = useTheme();
  const node = store.getNode(nodeId);
  if (!node) return null;

  const children = node.children ?? [];
  const metrics = resolveGridMetrics(node.layout, theme);
  const packed = packChildLayout(children, metrics.columns, store.getNode);
  // Keep keyboard and mobile reading order aligned with the desktop grid.
  // Packed x starts at the inline edge in both directions.
  const items = Object.entries(packed)
    .sort(([, a], [, b]) => a.y - b.y || a.x - b.x)
    .map(([id, rect]) => ({ id, rect, type: store.getNode(id)?.type ?? '' }));
  const pairedTiles = new Set<string>();
  for (let index = 1; index < items.length; index += 1) {
    const first = items[index - 1];
    const second = items[index];
    if (first.type === 'metric-tile' && second.type === 'metric-tile') {
      pairedTiles.add(first.id);
      pairedTiles.add(second.id);
      index += 1;
    }
  }

  return (
    <Surface>
      <Layout
        data-test="static-grid"
        data-container-id={nodeId}
        $metrics={metrics}
      >
        {items.map(({ id, rect, type }) => (
          <WidgetView
            key={id}
            nodeId={id}
            data-dashboard-grid-item={type}
            data-dashboard-paired-tile={pairedTiles.has(id) || undefined}
            style={
              {
                '--dashboard-grid-column': `${rect.x + 1} / span ${rect.w}`,
                '--dashboard-grid-row': `${rect.y + 1} / span ${rect.h}`,
                '--dashboard-grid-block-size': `${rect.h * (metrics.rowUnitPx + metrics.gap) - metrics.gap}px`,
              } as CSSProperties
            }
          />
        ))}
      </Layout>
    </Surface>
  );
}

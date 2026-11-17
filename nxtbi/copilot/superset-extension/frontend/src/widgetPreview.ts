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

interface WidgetPreview {
  type: ProposedWidget['type'];
  props: Record<string, unknown>;
}

export function widgetPreview(
  widget: ProposedWidget,
): WidgetPreview | undefined {
  const { type, datasetId, title } = widget;
  const metric = widget.metric.trim();
  const dimension = widget.dimension?.trim();
  if (!Number.isSafeInteger(datasetId) || datasetId < 1 || !metric) {
    return undefined;
  }

  const dataBinding = {
    datasetId,
    metrics: [metric],
    dimensions: dimension && type !== 'metric-tile' ? [dimension] : [],
    rowLimit: 100,
  };

  switch (type) {
    case 'metric-tile':
      return { type, props: { dataBinding, label: title?.trim() || metric } };
    case 'ag-grid-table':
      return { type, props: { dataBinding } };
    case 'echarts':
      if (!dimension) return undefined;
      return {
        type,
        props: {
          dataBinding,
          crossFilter: true,
          echartsOptions: {
            ...(title?.trim() && { title: { text: title.trim() } }),
            xAxis: {
              type: 'category',
              data: { $bind: { source: 'dimension', alias: dimension } },
            },
            yAxis: { type: 'value' },
            series: [
              {
                type: 'bar',
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

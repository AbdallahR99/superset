/*
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

import type { ReactNode } from 'react';
import type { A2uiAction, A2uiReactCatalog } from './a2ui';

export interface CopilotTextMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export interface CopilotConversation {
  threadId: string;
  messages: CopilotTextMessage[];
  updatedAt: string;
  savedDashboard?: { id: number; url: string };
}

export interface CopilotHistory {
  list: (signal: AbortSignal) => Promise<CopilotConversation[]>;
  save: (conversation: CopilotConversation, signal: AbortSignal) => Promise<void>;
}

export interface AgUiRunInput {
  threadId: string;
  runId: string;
  messages: CopilotTextMessage[];
  tools: [];
  state: Record<string, unknown>;
  context: Array<{ description: string; value: string }>;
  forwardedProps: { a2uiAction?: A2uiAction };
}

export interface DashboardWidget {
  type: 'metric-tile' | 'ag-grid-table' | 'echarts';
  datasetId: number;
  metric: string;
  dimension?: string;
  title?: string;
}

export interface DashboardProposal {
  title: string;
  widgets: DashboardWidget[];
  approvalToken: string;
}

/** Host capabilities stay outside model-generated UI. */
export interface CopilotHost {
  locale?: string;
  direction?: 'ltr' | 'rtl';
  context: () => Record<string, unknown>;
  run: (input: AgUiRunInput, signal: AbortSignal) => Promise<Response>;
  history?: CopilotHistory;
  approve?: (
    proposal: DashboardProposal,
    signal: AbortSignal,
  ) => Promise<{ id: number; url: string }>;
  navigate?: (url: string) => void;
  catalog?: A2uiReactCatalog;
  allowedActions?: readonly string[];
  onAction?: (action: A2uiAction) => boolean;
  renderProposal?: (
    proposal: DashboardProposal,
    onChange: (proposal: DashboardProposal) => void,
  ) => ReactNode;
}

export function readProposal(value: unknown): DashboardProposal | undefined {
  if (typeof value !== 'object' || value === null) return undefined;
  const proposal = value as DashboardProposal;
  if (
    typeof proposal.title !== 'string' ||
    proposal.title.length > 256 ||
    typeof proposal.approvalToken !== 'string' ||
    proposal.approvalToken.length > 2048 ||
    !Array.isArray(proposal.widgets) ||
    !proposal.widgets.length ||
    proposal.widgets.length > 8 ||
    !proposal.widgets.every(
      item =>
        item &&
        ['metric-tile', 'ag-grid-table', 'echarts'].includes(item.type) &&
        Number.isSafeInteger(item.datasetId) &&
        item.datasetId > 0 &&
        typeof item.metric === 'string' &&
        item.metric.length <= 256 &&
        [item.dimension, item.title].every(
          text => text === undefined || (typeof text === 'string' && text.length <= 256),
        ),
    )
  ) {
    return undefined;
  }
  return {
    title: proposal.title,
    approvalToken: proposal.approvalToken,
    widgets: proposal.widgets.map(({ type, datasetId, metric, dimension, title }) => ({
      type, datasetId, metric, dimension, title,
    })),
  };
}

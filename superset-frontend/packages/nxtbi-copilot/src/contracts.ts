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
  save: (
    conversation: CopilotConversation,
    signal: AbortSignal,
  ) => Promise<void>;
}

export interface AgUiRunInput {
  threadId: string;
  runId: string;
  messages: CopilotTextMessage[];
  tools: [];
  state: Record<string, unknown>;
  context: Array<{ description: string; value: string }>;
  forwardedProps: {
    a2uiAction?: A2uiAction;
    dashboardLocalization?: DashboardLocalizationRequest;
    datasetDraft?: { datasetId: number };
  };
}

export type DashboardType = 'v1' | 'v2';
export type DashboardContentLocale = 'en' | 'ar';

export interface DashboardLocalizationRequest {
  sourceLocale: DashboardContentLocale;
  targetLocale: DashboardContentLocale;
  captions: (string | null)[];
}

export function readCaptionSuggestions(
  value: unknown,
  request: DashboardLocalizationRequest,
): (string | null)[] | undefined {
  if (
    typeof value !== 'object' ||
    value === null ||
    !('targetLocale' in value) ||
    value.targetLocale !== request.targetLocale ||
    !('captions' in value) ||
    !Array.isArray(value.captions) ||
    value.captions.length !== request.captions.length ||
    !value.captions.every(
      (caption, index) =>
        caption === null ||
        (request.captions[index] !== null &&
          typeof caption === 'string' &&
          caption.trim().length > 0 &&
          caption.length <= 256),
    )
  ) {
    return undefined;
  }
  return value.captions.map(caption =>
    typeof caption === 'string' ? caption.trim() : null,
  );
}

export interface DashboardTitles {
  title?: string;
  titleTranslations?: Partial<Record<DashboardContentLocale, string>>;
}

export function dashboardLocale(locale?: string): DashboardContentLocale {
  return /^ar(?:$|[-_])/i.test(locale ?? '') ? 'ar' : 'en';
}

export function dashboardTitleIn(
  titles: DashboardTitles,
  canonicalLocale: DashboardContentLocale,
  locale: DashboardContentLocale,
): string | undefined {
  return locale === canonicalLocale
    ? titles.title
    : titles.titleTranslations?.[locale];
}

export function editDashboardTitle<T extends DashboardTitles>(
  titles: T,
  canonicalLocale: DashboardContentLocale,
  locale: DashboardContentLocale,
  value: T['title'],
): T {
  const titleTranslations = { ...titles.titleTranslations };
  if (
    value?.trim() &&
    (locale !== canonicalLocale || locale in titleTranslations)
  ) {
    titleTranslations[locale] = value;
  } else {
    delete titleTranslations[locale];
  }
  return {
    ...titles,
    ...(locale === canonicalLocale && { title: value }),
    titleTranslations: Object.keys(titleTranslations).length
      ? titleTranslations
      : undefined,
  };
}

export interface DashboardWidget extends DashboardTitles {
  type: 'metric-tile' | 'ag-grid-table' | 'echarts';
  datasetId: number;
  metric: string;
  dimension?: string;
  chartStyle?: 'bar' | 'line';
  filter?: { column: string; value: string | number | boolean };
}

export interface DashboardProposal extends DashboardTitles {
  title: string;
  widgets: DashboardWidget[];
  approvalToken: string;
  dashboardType?: DashboardType;
  contentLocale?: DashboardContentLocale;
}

export interface CopilotUploadedDataset {
  id: number;
  name: string;
}

export interface CopilotDatasetOption {
  id: number;
  name: string;
  detail?: string;
}

/** Host capabilities stay outside model-generated UI. */
export interface CopilotHost {
  locale?: string;
  direction?: 'ltr' | 'rtl';
  context: () => Record<string, unknown>;
  /** Available draft formats. The first is the default. */
  dashboardTypes?: readonly DashboardType[];
  run: (input: AgUiRunInput, signal: AbortSignal) => Promise<Response>;
  /** List authorized datasets using a zero-based page. */
  listDatasets?: (
    query: string,
    page: number,
    signal: AbortSignal,
  ) => Promise<{ items: CopilotDatasetOption[]; hasMore: boolean }>;
  uploadDataset?: (
    file: File,
    signal: AbortSignal,
  ) => Promise<CopilotUploadedDataset>;
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
    previewLocale: DashboardContentLocale,
  ) => ReactNode;
}

function validTranslations(
  value: unknown,
): value is DashboardTitles['titleTranslations'] {
  if (value === undefined) return true;
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    Object.entries(value).every(
      ([locale, title]) =>
        (locale === 'en' || locale === 'ar') &&
        typeof title === 'string' &&
        title.trim().length > 0 &&
        title.length <= 256,
    )
  );
}

export function readProposal(value: unknown): DashboardProposal | undefined {
  if (typeof value !== 'object' || value === null) return undefined;
  const proposal = value as DashboardProposal;
  if (
    typeof proposal.title !== 'string' ||
    proposal.title.length > 256 ||
    typeof proposal.approvalToken !== 'string' ||
    proposal.approvalToken.length > 2048 ||
    (proposal.dashboardType !== undefined &&
      proposal.dashboardType !== 'v1' &&
      proposal.dashboardType !== 'v2') ||
    (proposal.contentLocale !== undefined &&
      proposal.contentLocale !== 'en' &&
      proposal.contentLocale !== 'ar') ||
    !validTranslations(proposal.titleTranslations) ||
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
          text =>
            text === undefined ||
            (typeof text === 'string' && text.length <= 256),
        ) &&
        validTranslations(item.titleTranslations) &&
        (item.chartStyle === undefined ||
          (item.type === 'echarts' &&
            ['bar', 'line'].includes(item.chartStyle))) &&
        (item.filter === undefined ||
          (item.filter &&
            typeof item.filter.column === 'string' &&
            item.filter.column.trim().length > 0 &&
            item.filter.column.length <= 256 &&
            (typeof item.filter.value === 'boolean' ||
              (typeof item.filter.value === 'number' &&
                Number.isFinite(item.filter.value)) ||
              (typeof item.filter.value === 'string' &&
                item.filter.value.trim().length > 0 &&
                item.filter.value.length <= 256)))),
    )
  ) {
    return undefined;
  }
  return {
    title: proposal.title,
    approvalToken: proposal.approvalToken,
    dashboardType: proposal.dashboardType,
    contentLocale: proposal.contentLocale,
    titleTranslations: proposal.titleTranslations && {
      ...proposal.titleTranslations,
    },
    widgets: proposal.widgets.map(
      ({
        type,
        datasetId,
        metric,
        dimension,
        title,
        chartStyle,
        filter,
        titleTranslations,
      }) => ({
        type,
        datasetId,
        metric,
        dimension,
        title,
        titleTranslations: titleTranslations && { ...titleTranslations },
        chartStyle,
        filter: filter && { column: filter.column, value: filter.value },
      }),
    ),
  };
}

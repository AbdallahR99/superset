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
import { lazy, Suspense, useMemo, useSyncExternalStore } from 'react';
import { chat, dashboard, navigation, sqlLab } from '@apache-superset/core';
import { CopilotIcon, CopilotPanel } from '@nxtbi/copilot';
import type { CopilotHost } from '@nxtbi/copilot';
import '@nxtbi/copilot/styles.css';
import {
  dashboardDestination,
  deploymentBase,
  readPageContext,
  resolveDashboardLink,
} from './pageContext';
import { createSessionTransport } from './transport';
import { createWidgetCatalog } from './widgetCatalog';

declare const __webpack_public_path__: string;

const ProposalEditor = lazy(() => import('./ProposalEditor'));

const base = deploymentBase(window.location.origin, __webpack_public_path__);
const transport = createSessionTransport(base);

function language(): string {
  return document.documentElement.lang || 'en';
}

function englishOrArabic(english: string, arabic: string): string {
  return language().startsWith('ar') ? arabic : english;
}

function subscribeOpen(onChange: () => void): () => void {
  const opened = chat.onDidOpen(onChange);
  const closed = chat.onDidClose(onChange);
  return () => {
    opened.dispose();
    closed.dispose();
  };
}

function subscribeMode(onChange: () => void): () => void {
  const subscription = chat.onDidChangeDisplayMode(onChange);
  return () => subscription.dispose();
}

function Trigger() {
  const open = useSyncExternalStore(subscribeOpen, chat.isOpen);
  return (
    <button
      type="button"
      aria-controls="nxtbi-copilot-panel"
      aria-expanded={open}
      onClick={() => (open ? chat.close() : chat.open())}
      className="nxtbi-copilot-trigger"
    >
      <span aria-hidden="true">✦</span>
      {englishOrArabic('NxtBI Copilot', 'مساعد NxtBI')}
    </button>
  );
}

function Panel() {
  const mode = useSyncExternalStore(subscribeMode, chat.getDisplayMode);
  const locale = language();
  const modeLabel =
    mode === 'panel'
      ? englishOrArabic('Float', 'عرض عائم')
      : englishOrArabic('Dock', 'تثبيت');
  const direction =
    document.documentElement.dir === 'rtl' || locale.startsWith('ar')
      ? 'rtl'
      : 'ltr';
  const host: CopilotHost = useMemo(
    () => ({
      locale,
      direction,
      context: () => {
        const page = navigation.getPage();
        const activeEntity = {
          dashboardId:
            page === 'dashboard' ? dashboard.getDashboardId() : undefined,
          databaseId:
            page === 'sqllab' ? sqlLab.getCurrentTab()?.databaseId : undefined,
        };
        const context = readPageContext(
          base,
          page,
          new URL(window.location.href),
          activeEntity,
        );
        return {
          page: context.page,
          active_dashboard_id: context.dashboardId,
          active_chart_id: context.chartId,
          active_dataset_id: context.datasetId,
          active_database_id: context.databaseId,
        };
      },
      ...transport,
      catalog: createWidgetCatalog(base, locale, direction),
      allowedActions: ['nxtbi.submit-form', 'nxtbi.open-dashboard'],
      onAction: ({ action }) => {
        if (action.name !== 'nxtbi.open-dashboard') return false;
        void dashboardDestination(base, action.context).then(destination => {
          if (destination) window.location.assign(destination);
        });
        return true;
      },
      navigate: url => {
        const destination = resolveDashboardLink(base, url);
        if (destination) window.location.assign(destination);
      },
      renderProposal: (proposal, onChange) => (
        <Suspense
          fallback={
            <p role="status">
              {englishOrArabic('Loading previews…', 'جارٍ تحميل المعاينات…')}
            </p>
          }
        >
          <ProposalEditor
            key={proposal.approvalToken}
            proposal={proposal}
            onChange={onChange}
            base={base}
            locale={locale}
            direction={direction}
          />
        </Suspense>
      ),
    }),
    [direction, locale],
  );

  return (
    <section
      id="nxtbi-copilot-panel"
      className="nxtbi-copilot-shell"
      data-mode={mode}
      aria-label={englishOrArabic('NxtBI Copilot', 'مساعد NxtBI')}
      lang={locale}
      dir={direction}
    >
      <CopilotPanel
        host={host}
        headerActions={
          <button
            type="button"
            className="nxtbi-copilot__icon-button"
            aria-label={modeLabel}
            title={modeLabel}
            onClick={() =>
              chat.setDisplayMode(mode === 'panel' ? 'floating' : 'panel')
            }
          >
            <CopilotIcon name={mode === 'panel' ? 'float' : 'dock'} />
          </button>
        }
      />
    </section>
  );
}

chat.registerChat(
  { id: 'nxtbi.ai-copilot', name: 'NxtBI AI Copilot' },
  Trigger,
  Panel,
);

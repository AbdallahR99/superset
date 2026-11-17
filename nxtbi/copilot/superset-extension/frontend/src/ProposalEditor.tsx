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
import { useState } from 'react';
import { SupersetProvider, Widget } from '@apache-superset/widgets';
import type { DashboardProposal } from '@nxtbi/copilot';
import { widgetPreview } from './widgetPreview';
import type { ProposedWidget } from './widgetPreview';

interface ProposalEditorProps {
  proposal: DashboardProposal;
  onChange: (proposal: DashboardProposal) => void;
  base: string;
  locale: string;
  direction: 'ltr' | 'rtl';
}

const widgetTypes: readonly ProposedWidget['type'][] = [
  'metric-tile',
  'ag-grid-table',
  'echarts',
];

const labels = {
  en: {
    editor: 'Widget previews',
    widget: 'Widget',
    type: 'Widget type',
    widgetTitle: 'Widget title',
    metric: 'Metric',
    dimension: 'Dimension',
    dataset: 'Dataset',
    refresh: 'Refresh previews',
    idle: 'Choose a metric and any required dimension to preview this widget.',
    unavailable: 'Preview unavailable for this widget.',
    'metric-tile': 'Metric tile',
    'ag-grid-table': 'Table',
    echarts: 'Bar chart',
  },
  ar: {
    editor: 'معاينات العناصر',
    widget: 'عنصر',
    type: 'نوع العنصر',
    widgetTitle: 'عنوان العنصر',
    metric: 'المقياس',
    dimension: 'البُعد',
    dataset: 'مجموعة البيانات',
    refresh: 'تحديث المعاينات',
    idle: 'اختر مقياسًا وأي بُعد مطلوب لمعاينة هذا العنصر.',
    unavailable: 'معاينة هذا العنصر غير متوفرة.',
    'metric-tile': 'بطاقة مقياس',
    'ag-grid-table': 'جدول',
    echarts: 'مخطط أعمدة',
  },
};

export default function ProposalEditor({
  proposal,
  onChange,
  base,
  locale,
  direction,
}: ProposalEditorProps) {
  const text = locale.startsWith('ar') ? labels.ar : labels.en;
  const [previewWidgets, setPreviewWidgets] = useState(proposal.widgets);
  const updateWidget = (index: number, patch: Partial<ProposedWidget>) => {
    onChange({
      ...proposal,
      widgets: proposal.widgets.map((widget, offset) =>
        offset === index ? { ...widget, ...patch } : widget,
      ),
    });
  };

  return (
    <section
      aria-label={text.editor}
      dir={direction}
      lang={locale}
      style={{ display: 'grid', gap: 12 }}
    >
      <div>
        <button
          type="button"
          disabled={previewWidgets === proposal.widgets}
          onClick={() => setPreviewWidgets(proposal.widgets)}
        >
          {text.refresh}
        </button>
      </div>
      <SupersetProvider
        supersetDomain={base}
        locale={locale}
        direction={direction}
        extensionWidgets={false}
      >
        {proposal.widgets.map((widget, index) => {
          const snapshot = previewWidgets[index];
          const preview = snapshot && widgetPreview(snapshot);
          return (
            <fieldset
              key={index}
              style={{ display: 'grid', gap: 8, minInlineSize: 0 }}
            >
              <legend>
                {text.widget} {index + 1}
              </legend>
              <p style={{ margin: 0 }}>
                {text.dataset} {widget.datasetId}
              </p>
              <label>
                {text.type}{' '}
                <select
                  value={widget.type}
                  onChange={event => {
                    const type = widgetTypes.find(
                      value => value === event.target.value,
                    );
                    if (type) updateWidget(index, { type });
                  }}
                >
                  {widgetTypes.map(type => (
                    <option key={type} value={type}>
                      {text[type]}
                    </option>
                  ))}
                </select>
              </label>
              {widget.type !== 'ag-grid-table' && (
                <label>
                  {text.widgetTitle}{' '}
                  <input
                    value={widget.title ?? ''}
                    maxLength={160}
                    onChange={event =>
                      updateWidget(index, {
                        title: event.target.value || undefined,
                      })
                    }
                  />
                </label>
              )}
              <label>
                {text.metric}{' '}
                <input
                  value={widget.metric}
                  maxLength={160}
                  onChange={event =>
                    updateWidget(index, { metric: event.target.value })
                  }
                />
              </label>
              {widget.type !== 'metric-tile' && (
                <label>
                  {text.dimension}{' '}
                  <input
                    value={widget.dimension ?? ''}
                    maxLength={160}
                    onChange={event =>
                      updateWidget(index, {
                        dimension: event.target.value || undefined,
                      })
                    }
                  />
                </label>
              )}
              {preview ? (
                <Widget
                  type={preview.type}
                  props={preview.props}
                  showTitle={false}
                  renderError={() => <p role="status">{text.unavailable}</p>}
                  style={{ height: preview.type === 'metric-tile' ? 90 : 200 }}
                />
              ) : (
                <p role="status">{text.idle}</p>
              )}
            </fieldset>
          );
        })}
      </SupersetProvider>
    </section>
  );
}

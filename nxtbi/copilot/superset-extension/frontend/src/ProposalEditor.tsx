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
import { useEffect, useState } from 'react';
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

interface DatasetSummary {
  id: number;
  table_name: string;
}

interface DatasetFields {
  table_name: string;
  metrics: { metric_name: string; verbose_name?: string }[];
  columns: { column_name: string; verbose_name?: string; groupby: boolean }[];
}

async function readDataset<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    redirect: 'error',
    cache: 'no-store',
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error('Dataset metadata unavailable');
  return response.json();
}

const pageSize = 25;

const labels = {
  en: {
    changed: 'Refresh previews to see your changes.',
    noDimensions: 'No groupable columns. Choose a metric tile or table.',
    retry: 'Retry',
    noMetrics: 'This dataset has no saved metrics. Choose another dataset.',
    loading: 'Loading dataset fields…',
    next: 'Next datasets',
    previous: 'Previous datasets',
    catalogError: 'Could not load dataset list.',
    loadError: 'Could not load dataset fields.',
    noDimension: 'No grouping',
    chooseDimension: 'Choose a dimension',
    chooseMetric: 'Choose a saved metric',
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
    changed: 'حدّث المعاينات لعرض التغييرات.',
    noDimensions: 'لا توجد أعمدة للتجميع. اختر بطاقة مقياس أو جدولًا.',
    retry: 'إعادة المحاولة',
    noMetrics: 'لا توجد مقاييس محفوظة. اختر مجموعة بيانات أخرى.',
    loading: 'جارٍ تحميل حقول مجموعة البيانات…',
    next: 'مجموعات البيانات التالية',
    previous: 'مجموعات البيانات السابقة',
    catalogError: 'تعذّر تحميل قائمة مجموعات البيانات.',
    loadError: 'تعذّر تحميل حقول مجموعة البيانات.',
    noDimension: 'بدون تجميع',
    chooseDimension: 'اختر بُعدًا',
    chooseMetric: 'اختر مقياسًا محفوظًا',
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
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);
  const [catalog, setCatalog] = useState<{
    result: DatasetSummary[];
    count: number;
  } | null>();
  const [fields, setFields] = useState<Record<number, DatasetFields | null>>(
    {},
  );
  const ids = [...new Set(proposal.widgets.map(widget => widget.datasetId))]
    .sort()
    .join(',');
  useEffect(() => {
    const controller = new AbortController();
    setCatalog(undefined);
    const query = `(columns:!(id,table_name),order_column:table_name,order_direction:asc,page:${page},page_size:${pageSize})`;
    readDataset<{ result: DatasetSummary[]; count: number }>(
      `${base}/api/v1/dataset/?q=${query}`,
      controller.signal,
    )
      .then(result => {
        if (!controller.signal.aborted) setCatalog(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setCatalog(null);
      });
    return () => controller.abort();
  }, [base, page, retry]);

  useEffect(() => {
    const controller = new AbortController();
    setFields({});
    const query =
      '(columns:!(table_name,metrics.metric_name,metrics.verbose_name,columns.column_name,columns.verbose_name,columns.groupby))';
    for (const id of ids.split(',').map(Number)) {
      readDataset<{ result: DatasetFields }>(
        `${base}/api/v1/dataset/${id}?q=${query}`,
        controller.signal,
      )
        .then(({ result }) => {
          if (!Array.isArray(result.metrics) || !Array.isArray(result.columns))
            throw new Error('Invalid dataset fields');
          if (!controller.signal.aborted)
            setFields(previous => ({ ...previous, [id]: result }));
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setFields(previous => ({ ...previous, [id]: null }));
        });
    }
    return () => controller.abort();
  }, [base, ids, retry]);
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
        {catalog === null && <p role="status">{text.catalogError}</p>}
        {(catalog === null || Object.values(fields).includes(null)) && (
          <button type="button" onClick={() => setRetry(value => value + 1)}>
            {text.retry}
          </button>
        )}
        {(page > 0 || Boolean(catalog && catalog.count > pageSize)) && (
          <div>
            <button
              type="button"
              disabled={!page}
              onClick={() => setPage(page - 1)}
            >
              {text.previous}
            </button>
            <button
              type="button"
              disabled={!catalog || (page + 1) * pageSize >= catalog.count}
              onClick={() => setPage(page + 1)}
            >
              {text.next}
            </button>
          </div>
        )}
        {proposal.widgets.map((widget, index) => {
          const dataset = fields[widget.datasetId];
          const metrics = dataset?.metrics ?? [];
          const dimensions =
            dataset?.columns.filter(column => column.groupby) ?? [];
          const datasets = catalog?.result ?? [];
          const snapshot = previewWidgets[index];
          const preview = snapshot === widget && widgetPreview(snapshot);
          return (
            <fieldset
              key={index}
              style={{ display: 'grid', gap: 8, minInlineSize: 0 }}
            >
              <legend>
                {text.widget} {index + 1}
              </legend>
              <label>
                {text.dataset}{' '}
                <select
                  value={widget.datasetId}
                  onChange={event => {
                    updateWidget(index, {
                      datasetId: Number(event.target.value),
                      metric: '',
                      dimension: undefined,
                    });
                  }}
                >
                  {!datasets.some(item => item.id === widget.datasetId) && (
                    <option value={widget.datasetId}>
                      {dataset?.table_name ?? text.dataset} (#{widget.datasetId}
                      )
                    </option>
                  )}
                  {datasets.map(item => (
                    <option key={item.id} value={item.id}>
                      {item.table_name} (#{item.id})
                    </option>
                  ))}
                </select>
              </label>
              {!dataset && (
                <p role="status">
                  {dataset === null ? text.loadError : text.loading}
                </p>
              )}
              {dataset && !metrics.length && (
                <p role="status">{text.noMetrics}</p>
              )}
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
                <select
                  value={widget.metric}
                  required
                  disabled={!metrics.length}
                  onChange={event =>
                    updateWidget(index, { metric: event.target.value })
                  }
                >
                  <option value="" disabled>
                    {text.chooseMetric}
                  </option>
                  {widget.metric &&
                    !metrics.some(
                      item => item.metric_name === widget.metric,
                    ) && <option value={widget.metric}>{widget.metric}</option>}
                  {metrics.map(item => (
                    <option key={item.metric_name} value={item.metric_name}>
                      {item.verbose_name || item.metric_name}
                    </option>
                  ))}
                </select>
              </label>
              {widget.type !== 'metric-tile' && (
                <label>
                  {text.dimension}{' '}
                  <select
                    value={widget.dimension ?? ''}
                    disabled={!dimensions.length}
                    required={widget.type === 'echarts'}
                    onChange={event =>
                      updateWidget(index, {
                        dimension: event.target.value || undefined,
                      })
                    }
                  >
                    <option value="" disabled={widget.type === 'echarts'}>
                      {widget.type === 'echarts'
                        ? text.chooseDimension
                        : text.noDimension}
                    </option>
                    {widget.dimension &&
                      !dimensions.some(
                        item => item.column_name === widget.dimension,
                      ) && (
                        <option value={widget.dimension}>
                          {widget.dimension}
                        </option>
                      )}
                    {dimensions.map(item => (
                      <option key={item.column_name} value={item.column_name}>
                        {item.verbose_name || item.column_name}
                      </option>
                    ))}
                  </select>
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
                <p role="status">
                  {dataset && widget.type === 'echarts' && !dimensions.length
                    ? text.noDimensions
                    : widgetPreview(widget)
                      ? text.changed
                      : text.idle}
                </p>
              )}
            </fieldset>
          );
        })}
      </SupersetProvider>
    </section>
  );
}

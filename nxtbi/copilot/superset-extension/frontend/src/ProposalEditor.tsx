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
import { useEffect, useState } from "react";
import { SupersetProvider, Widget } from "@apache-superset/widgets";
import {
  dashboardLocale,
  dashboardTitleIn,
  editDashboardTitle,
} from "@nxtbi/copilot";
import type { DashboardContentLocale, DashboardProposal } from "@nxtbi/copilot";
import { widgetPreview } from "./widgetPreview";
import type { ProposedWidget } from "./widgetPreview";
import "./proposal.css";

interface ProposalEditorProps {
  proposal: DashboardProposal;
  onChange: (proposal: DashboardProposal) => void;
  base: string;
  locale: string;
  direction: "ltr" | "rtl";
  previewLocale: DashboardContentLocale;
}

const widgetTypes: readonly ProposedWidget["type"][] = ["metric-tile", "ag-grid-table", "echarts"];

interface DatasetSummary {
  id: number;
  table_name: string;
}

interface DatasetFields {
  table_name: string;
  description?: string | null;
  metrics: { metric_name: string; verbose_name?: string; d3format?: string }[];
  columns: {
    column_name: string;
    verbose_name?: string;
    groupby: boolean;
    is_dttm: boolean;
  }[];
}

function datasetDisplayName(dataset: DatasetFields): string {
  if (/^copilot_csv_[0-9a-f]{24}$/.test(dataset.table_name)) {
    const name = dataset.description?.match(
      /^Uploaded through Copilot from ([^/\\\p{C}]{1,120}\.csv)\.$/u,
    )?.[1];
    if (name?.slice(0, -4).trim()) return name;
  }
  return dataset.table_name;
}

async function readDataset<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    redirect: "error",
    cache: "no-store",
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("Dataset metadata unavailable");
  return response.json();
}

const pageSize = 25;

const labels = {
  en: {
    changed: "Refresh previews to see your changes.",
    noDimensions: "No groupable columns. Choose a metric tile or table.",
    retry: "Retry",
    noMetrics: "This dataset has no saved metrics. Choose another dataset.",
    loading: "Loading dataset fields…",
    next: "Next datasets",
    previous: "Previous datasets",
    catalogError: "Could not load dataset list.",
    loadError: "Could not load dataset fields.",
    noDimension: "No grouping",
    chooseDimension: "Choose a dimension",
    chooseMetric: "Choose a saved metric",
    editor: "Widget previews",
    editWidget: "Edit widget",
    widget: "Widget",
    type: "Widget type",
    widgetTitle: "Widget title",
    metric: "Metric",
    dimension: "Dimension",
    dataset: "Dataset",
    refresh: "Refresh previews",
    idle: "Choose a metric and any required dimension to preview this widget.",
    unavailable: "Preview unavailable for this widget.",
    chartStyle: "Chart style",
    bar: "Bar chart",
    line: "Line chart",
    scope: "Fixed filter",
    clearScope: "Remove filter",
    "metric-tile": "Metric tile",
    "ag-grid-table": "Table",
    echarts: "Chart",
  },
  ar: {
    changed: "حدّث المعاينات لعرض التغييرات.",
    noDimensions: "لا توجد أعمدة للتجميع. اختر بطاقة مقياس أو جدولًا.",
    retry: "إعادة المحاولة",
    noMetrics: "لا توجد مقاييس محفوظة. اختر مجموعة بيانات أخرى.",
    loading: "جارٍ تحميل حقول مجموعة البيانات…",
    next: "مجموعات البيانات التالية",
    previous: "مجموعات البيانات السابقة",
    catalogError: "تعذّر تحميل قائمة مجموعات البيانات.",
    loadError: "تعذّر تحميل حقول مجموعة البيانات.",
    noDimension: "بدون تجميع",
    chooseDimension: "اختر بُعدًا",
    chooseMetric: "اختر مقياسًا محفوظًا",
    editor: "معاينات العناصر",
    editWidget: "تحرير العنصر",
    widget: "عنصر",
    type: "نوع العنصر",
    widgetTitle: "عنوان العنصر",
    metric: "المقياس",
    dimension: "البُعد",
    dataset: "مجموعة البيانات",
    refresh: "تحديث المعاينات",
    idle: "اختر مقياسًا وأي بُعد مطلوب لمعاينة هذا العنصر.",
    unavailable: "معاينة هذا العنصر غير متوفرة.",
    chartStyle: "نمط المخطط",
    bar: "مخطط أعمدة",
    line: "مخطط خطي",
    scope: "عامل تصفية ثابت",
    clearScope: "إزالة عامل التصفية",
    "metric-tile": "بطاقة مقياس",
    "ag-grid-table": "جدول",
    echarts: "مخطط",
  },
};

export default function ProposalEditor({
  proposal,
  onChange,
  base,
  locale,
  direction,
  previewLocale,
}: ProposalEditorProps) {
  const text = labels[dashboardLocale(locale)];
  const canonicalLocale = proposal.contentLocale ?? dashboardLocale(locale);
  const previewDirection = previewLocale === "ar" ? "rtl" : "ltr";
  const [previewWidgets, setPreviewWidgets] = useState(proposal.widgets);
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);
  const [catalog, setCatalog] = useState<{
    result: DatasetSummary[];
    count: number;
  } | null>();
  const [fields, setFields] = useState<Record<number, DatasetFields | null>>({});
  const ids = [...new Set(proposal.widgets.map((widget) => widget.datasetId))].sort().join(",");
  useEffect(() => {
    const controller = new AbortController();
    setCatalog(undefined);
    const query = `(columns:!(id,table_name),order_column:table_name,order_direction:asc,page:${page},page_size:${pageSize})`;
    readDataset<{ result: DatasetSummary[]; count: number }>(
      `${base}/api/v1/dataset/?q=${query}`,
      controller.signal,
    )
      .then((result) => {
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
      "(columns:!(table_name,description,metrics.metric_name,metrics.verbose_name,metrics.d3format,columns.column_name,columns.verbose_name,columns.groupby,columns.is_dttm))";
    for (const id of ids.split(",").map(Number)) {
      readDataset<{ result: DatasetFields }>(
        `${base}/api/v1/dataset/${id}?q=${query}`,
        controller.signal,
      )
        .then(({ result }) => {
          if (!Array.isArray(result.metrics) || !Array.isArray(result.columns))
            throw new Error("Invalid dataset fields");
          if (!controller.signal.aborted) setFields((previous) => ({ ...previous, [id]: result }));
        })
        .catch(() => {
          if (!controller.signal.aborted) setFields((previous) => ({ ...previous, [id]: null }));
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

  const needsRefresh = previewWidgets !== proposal.widgets;

  return (
    <section
      className="nxtbi-proposal-editor"
      aria-label={text.editor}
      dir={direction}
      lang={locale}
    >
      <div className="nxtbi-proposal-editor__tools">
        <button
          type="button"
          disabled={!needsRefresh}
          onClick={() => setPreviewWidgets(proposal.widgets)}
        >
          {text.refresh}
        </button>
        {needsRefresh && <span role="status">{text.changed}</span>}
      </div>
      <SupersetProvider
        supersetDomain={base}
        locale={previewLocale}
        direction={previewDirection}
        extensionWidgets={false}
      >
        {catalog === null && <p role="status">{text.catalogError}</p>}
        {(catalog === null || Object.values(fields).includes(null)) && (
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            {text.retry}
          </button>
        )}
        {(page > 0 || Boolean(catalog && catalog.count > pageSize)) && (
          <div>
            <button type="button" disabled={!page} onClick={() => setPage(page - 1)}>
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
            dataset?.columns.filter(
              (column) => column.groupby && (widget.chartStyle !== "line" || column.is_dttm),
            ) ?? [];
          const selectedMetric = metrics.find((item) => item.metric_name === widget.metric);
          const datasets = catalog?.result ?? [];
          const snapshot = previewWidgets[index];
          const translatedTitle = dashboardTitleIn(widget, canonicalLocale, previewLocale);
          const title = translatedTitle || widget.title;
          const titleLocale = translatedTitle ? previewLocale : canonicalLocale;
          const preview =
            snapshot === widget &&
            widgetPreview({ ...widget, title }, selectedMetric?.d3format);
          return (
            <article className="nxtbi-proposal-widget" key={index}>
              <header className="nxtbi-proposal-widget__header">
                <h4>
                  <bdi lang={title ? titleLocale : locale}>{title || text[widget.type]}</bdi>
                </h4>
                {dataset && (
                  <p>
                    <bdi>{datasetDisplayName(dataset)}</bdi>
                  </p>
                )}
              </header>
              <div
                className="nxtbi-proposal-widget__preview"
                lang={previewLocale}
                dir={previewDirection}
              >
                {preview ? (
                  <Widget
                    type={preview.type}
                    props={preview.props}
                    showTitle={false}
                    renderError={() => <p role="status">{text.unavailable}</p>}
                    style={{ height: preview.type === "metric-tile" ? 88 : 236 }}
                  />
                ) : (
                  <p role="status">
                    {dataset && widget.type === "echarts" && !dimensions.length
                      ? text.noDimensions
                      : widgetPreview(widget)
                        ? text.changed
                        : text.idle}
                  </p>
                )}
              </div>
              <details className="nxtbi-proposal-widget__settings">
                <summary>{text.editWidget}</summary>
                <fieldset>
                  <legend>
                    {text.widget} {index + 1}
                  </legend>
                  <label>
                    {text.dataset}{" "}
                    <select
                      value={widget.datasetId}
                      onChange={(event) => {
                        updateWidget(index, {
                          datasetId: Number(event.target.value),
                          metric: "",
                          dimension: undefined,
                          filter: undefined,
                        });
                      }}
                    >
                      {!datasets.some((item) => item.id === widget.datasetId) && (
                        <option value={widget.datasetId}>
                          {dataset ? datasetDisplayName(dataset) : text.dataset} (#
                          {widget.datasetId})
                        </option>
                      )}
                      {datasets.map((item) => {
                        const details = fields[item.id];
                        return (
                          <option key={item.id} value={item.id}>
                            {details ? datasetDisplayName(details) : item.table_name} (#{item.id})
                          </option>
                        );
                      })}
                    </select>
                  </label>
                  {!dataset && (
                    <p role="status">{dataset === null ? text.loadError : text.loading}</p>
                  )}
                  {dataset && !metrics.length && <p role="status">{text.noMetrics}</p>}
                  <label>
                    {text.type}{" "}
                    <select
                      value={widget.type}
                      onChange={(event) => {
                        const type = widgetTypes.find((value) => value === event.target.value);
                        if (type)
                          updateWidget(index, {
                            type,
                            chartStyle: type === "echarts" ? widget.chartStyle : undefined,
                          });
                      }}
                    >
                      {widgetTypes.map((type) => (
                        <option key={type} value={type}>
                          {text[type]}
                        </option>
                      ))}
                    </select>
                  </label>
                  {widget.type === "echarts" && (
                    <label>
                      {text.chartStyle}{" "}
                      <select
                        value={widget.chartStyle ?? "bar"}
                        onChange={(event) => {
                          const chartStyle = event.target.value === "line" ? "line" : "bar";
                          const temporal = dataset?.columns.some(
                            (column) => column.column_name === widget.dimension && column.is_dttm,
                          );
                          updateWidget(index, {
                            chartStyle,
                            dimension:
                              chartStyle === "line" && !temporal ? undefined : widget.dimension,
                          });
                        }}
                      >
                        <option value="bar">{text.bar}</option>
                        <option value="line">{text.line}</option>
                      </select>
                    </label>
                  )}
                  <label>
                    {text.widgetTitle}{" "}
                    <input
                      value={translatedTitle ?? ""}
                      placeholder={previewLocale !== canonicalLocale ? widget.title : undefined}
                      lang={previewLocale}
                      dir={previewDirection}
                      maxLength={proposal.dashboardType === "v1" ? 250 : 256}
                      onChange={(event) =>
                        updateWidget(
                          index,
                          editDashboardTitle(
                            widget,
                            canonicalLocale,
                            previewLocale,
                            event.target.value.trim() ? event.target.value : undefined,
                          ),
                        )
                      }
                    />
                  </label>
                  <label>
                    {text.metric}{" "}
                    <select
                      value={widget.metric}
                      required
                      disabled={!metrics.length}
                      onChange={(event) => updateWidget(index, { metric: event.target.value })}
                    >
                      <option value="" disabled>
                        {text.chooseMetric}
                      </option>
                      {widget.metric &&
                        !metrics.some((item) => item.metric_name === widget.metric) && (
                          <option value={widget.metric}>{widget.metric}</option>
                        )}
                      {metrics.map((item) => (
                        <option key={item.metric_name} value={item.metric_name}>
                          {item.verbose_name || item.metric_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {widget.type !== "metric-tile" && (
                    <label>
                      {text.dimension}{" "}
                      <select
                        value={widget.dimension ?? ""}
                        disabled={!dimensions.length}
                        required={widget.type === "echarts"}
                        onChange={(event) =>
                          updateWidget(index, {
                            dimension: event.target.value || undefined,
                          })
                        }
                      >
                        <option value="" disabled={widget.type === "echarts"}>
                          {widget.type === "echarts" ? text.chooseDimension : text.noDimension}
                        </option>
                        {widget.dimension &&
                          !dimensions.some((item) => item.column_name === widget.dimension) && (
                            <option value={widget.dimension}>{widget.dimension}</option>
                          )}
                        {dimensions.map((item) => (
                          <option key={item.column_name} value={item.column_name}>
                            {item.verbose_name || item.column_name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {widget.filter && (
                    <div>
                      {text.scope}{" "}
                      <bdi>
                        {widget.filter.column} = {String(widget.filter.value)}
                      </bdi>{" "}
                      <button
                        type="button"
                        onClick={() => updateWidget(index, { filter: undefined })}
                      >
                        {text.clearScope}
                      </button>
                    </div>
                  )}
                </fieldset>
              </details>
            </article>
          );
        })}
      </SupersetProvider>
    </section>
  );
}

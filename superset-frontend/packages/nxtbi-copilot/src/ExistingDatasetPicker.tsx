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

import { useEffect, useId, useState } from 'react';
import type {
  CopilotDatasetOption,
  CopilotHost,
  DashboardContentLocale,
} from './contracts';

const MAX_QUERY_LENGTH = 100;

const labels = {
  en: {
    open: 'Use existing data',
    query: 'Search datasets',
    search: 'Search',
    loading: 'Loading datasets…',
    empty: 'No datasets are available.',
    noMatches: 'No datasets match your search.',
    failed: 'Could not load datasets.',
    retry: 'Retry',
    choose: 'Choose a dataset',
    previous: 'Previous datasets',
    next: 'Next datasets',
    draft: 'Draft from existing dataset',
  },
  ar: {
    open: 'استخدام البيانات الموجودة',
    query: 'البحث في مجموعات البيانات',
    search: 'بحث',
    loading: 'جارٍ تحميل مجموعات البيانات…',
    empty: 'لا توجد مجموعات بيانات متاحة.',
    noMatches: 'لا توجد مجموعات بيانات تطابق بحثك.',
    failed: 'تعذّر تحميل مجموعات البيانات.',
    retry: 'إعادة المحاولة',
    choose: 'اختر مجموعة بيانات',
    previous: 'مجموعات البيانات السابقة',
    next: 'مجموعات البيانات التالية',
    draft: 'إنشاء مسودة من مجموعة بيانات موجودة',
  },
};

interface DatasetRequest {
  query: string;
  page: number;
}

type ListDatasets = NonNullable<CopilotHost['listDatasets']>;
type DatasetPage = Awaited<ReturnType<ListDatasets>>;

interface ExistingDatasetPickerProps {
  locale: DashboardContentLocale;
  listDatasets: ListDatasets;
  busy: boolean;
  onDraft: (dataset: CopilotDatasetOption) => void;
}

/** Browse authorized datasets and select the source for a dashboard draft. */
export function ExistingDatasetPicker({
  locale,
  listDatasets,
  busy,
  onDraft,
}: ExistingDatasetPickerProps) {
  const id = useId();
  const copy = labels[locale];
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState('');
  const [request, setRequest] = useState<DatasetRequest>({
    query: '',
    page: 0,
  });
  const [response, setResponse] = useState<{
    request: DatasetRequest;
    result: DatasetPage | null;
  }>();
  const [selectedId, setSelectedId] = useState<number>();

  useEffect(() => {
    if (!expanded) return undefined;
    const controller = new AbortController();
    async function load() {
      try {
        const result = await listDatasets(
          request.query,
          request.page,
          controller.signal,
        );
        if (!controller.signal.aborted) setResponse({ request, result });
      } catch {
        if (!controller.signal.aborted) setResponse({ request, result: null });
      }
    }
    load();
    return () => controller.abort();
  }, [expanded, listDatasets, request]);

  const result = response?.request === request ? response.result : undefined;
  const selected = result?.items.find(dataset => dataset.id === selectedId);

  function loadPage(query: string, page: number) {
    setSelectedId(undefined);
    setRequest({ query, page });
  }

  return (
    <section className="nxtbi-copilot__dataset-picker">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={`${id}-browser`}
        onClick={() => {
          if (!expanded) loadPage(request.query, request.page);
          setExpanded(!expanded);
        }}
      >
        {copy.open}
      </button>
      <div
        id={`${id}-browser`}
        className="nxtbi-copilot__dataset-browser"
        hidden={!expanded}
      >
        <form
          onSubmit={event => {
            event.preventDefault();
            loadPage(input.trim().slice(0, MAX_QUERY_LENGTH), 0);
          }}
        >
          <label htmlFor={`${id}-query`}>{copy.query}</label>
          <div className="nxtbi-copilot__dataset-actions">
            <input
              id={`${id}-query`}
              type="search"
              dir="auto"
              maxLength={MAX_QUERY_LENGTH}
              value={input}
              onChange={event => setInput(event.target.value)}
            />
            <button type="submit">{copy.search}</button>
          </div>
        </form>
        <output className="nxtbi-copilot__dataset-status">
          {result === undefined && copy.loading}
          {result?.items.length === 0 &&
            (request.query ? copy.noMatches : copy.empty)}
        </output>
        {result === null && (
          <div>
            <p role="alert">{copy.failed}</p>
            <button
              type="button"
              onClick={() => loadPage(request.query, request.page)}
            >
              {copy.retry}
            </button>
          </div>
        )}
        {result && result.items.length > 0 && (
          <fieldset>
            <legend>{copy.choose}</legend>
            <ul>
              {result.items.map(dataset => {
                const optionId = `${id}-option-${dataset.id}`;
                const detailId = `${optionId}-detail`;
                return (
                  <li key={dataset.id}>
                    <input
                      type="radio"
                      id={optionId}
                      name={id}
                      aria-describedby={dataset.detail ? detailId : undefined}
                      checked={dataset.id === selectedId}
                      onChange={() => setSelectedId(dataset.id)}
                    />
                    <div>
                      <label htmlFor={optionId}>
                        <bdi>{dataset.name}</bdi>
                      </label>
                      {dataset.detail && (
                        <div
                          id={detailId}
                          className="nxtbi-copilot__dataset-detail"
                        >
                          <bdi>{dataset.detail}</bdi>
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </fieldset>
        )}
        {(request.page > 0 || result?.hasMore) && (
          <div className="nxtbi-copilot__dataset-actions">
            <button
              type="button"
              disabled={request.page === 0 || result === undefined}
              onClick={() => loadPage(request.query, request.page - 1)}
            >
              {copy.previous}
            </button>
            <button
              type="button"
              disabled={!result?.hasMore}
              onClick={() => loadPage(request.query, request.page + 1)}
            >
              {copy.next}
            </button>
          </div>
        )}
        <button
          type="button"
          disabled={!selected || busy}
          onClick={() => {
            if (selected) onDraft(selected);
          }}
        >
          {copy.draft}
        </button>
      </div>
    </section>
  );
}

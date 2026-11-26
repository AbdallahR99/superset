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

import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type {
  SemanticDraftResult,
  SemanticSavedDashboard,
  SemanticTransport,
} from './semanticTransport';
import './semantic-catalog.css';

const copyByLocale = {
  en: {
    name: 'Semantic catalog',
    request: 'Metric or dashboard request',
    hint: 'Try “average property price” to compare the approved definitions.',
    choose: 'Choose the metric you mean',
    generate: 'Generate draft',
    generating: 'Generating draft…',
    save: 'Save dashboard',
    saving: 'Saving dashboard…',
    saved: 'Dashboard saved.',
    open: 'Open dashboard',
    unmatched:
      'No approved metric matches that request. Try the example above.',
    draftError: 'Superset could not read the approved metrics. Try again.',
    saveError:
      'Superset could not save this dashboard. Generate a new draft or try again.',
    ready: 'Draft ready for review.',
    preview: 'Breakdown by property type',
    propertyType: 'Property type',
    value: 'Value',
    missing: 'Unavailable',
  },
  ar: {
    name: 'الكتالوج الدلالي',
    request: 'المقياس أو طلب لوحة المعلومات',
    hint: 'جرّب «متوسط سعر العقار» للمقارنة بين التعريفات المعتمدة.',
    choose: 'اختر المقياس الذي تقصده',
    generate: 'إنشاء مسودة',
    generating: 'جارٍ إنشاء المسودة…',
    save: 'حفظ لوحة المعلومات',
    saving: 'جارٍ حفظ لوحة المعلومات…',
    saved: 'تم حفظ لوحة المعلومات.',
    open: 'فتح لوحة المعلومات',
    unmatched: 'لا يوجد مقياس معتمد يطابق طلبك. جرّب المثال أعلاه.',
    draftError: 'تعذّرت قراءة المقاييس المعتمدة في Superset. حاول مجددًا.',
    saveError:
      'تعذّر حفظ لوحة المعلومات في Superset. أنشئ مسودة جديدة أو حاول مجددًا.',
    ready: 'المسودة جاهزة للمراجعة.',
    preview: 'التفاصيل حسب نوع العقار',
    propertyType: 'نوع العقار',
    value: 'القيمة',
    missing: 'غير متاح',
  },
};

type Props = {
  locale: 'en' | 'ar';
  transport: SemanticTransport;
  dashboardHref: (url: string) => string | undefined;
};

function SemanticCatalogForm({
  locale,
  transport,
  dashboardHref,
  summaryId,
}: Props & { summaryId: string }) {
  const id = useId();
  const text = copyByLocale[locale];
  const [phrase, setPhrase] = useState('');
  const [chosenMetric, setChosenMetric] = useState('');
  const [result, setResult] = useState<SemanticDraftResult>();
  const [saved, setSaved] = useState<SemanticSavedDashboard>();
  const [pending, setPending] = useState<'draft' | 'save'>();
  const [error, setError] = useState('');
  const request = useRef<AbortController | undefined>(undefined);
  const choices = useRef<HTMLFieldSetElement>(null);
  const candidates =
    result?.status === 'ambiguous' ? result.candidates : undefined;
  const draft = result?.status === 'draft' ? result : undefined;
  const href = saved && dashboardHref(saved.url);
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });

  function formatValue(value: number | null) {
    return value === null ? text.missing : number.format(value);
  }

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (candidates) choices.current?.focus();
  }, [candidates]);

  async function run<T>(
    operation: 'draft' | 'save',
    perform: (signal: AbortSignal) => Promise<T>,
    success: (value: T) => void,
  ) {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(operation);
    setError('');
    try {
      const next = await perform(controller.signal);
      if (!controller.signal.aborted) success(next);
    } catch {
      if (!controller.signal.aborted) {
        setError(operation === 'draft' ? text.draftError : text.saveError);
      }
    } finally {
      request.current = undefined;
      if (!controller.signal.aborted) setPending(undefined);
    }
  }

  function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requestText = phrase.trim();
    if (!requestText || (candidates && !chosenMetric)) return;
    setSaved(undefined);
    run(
      'draft',
      signal =>
        transport.draft(
          {
            phrase: requestText,
            locale,
            ...(candidates && { metricId: chosenMetric }),
          },
          signal,
        ),
      next => {
        setResult(next);
        setChosenMetric('');
      },
    );
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || saved) return;
    run(
      'save',
      signal => transport.approve(draft.approvalToken, signal),
      setSaved,
    );
  }

  return (
    <div className="nxtbi-copilot-semantic__body">
      <form aria-labelledby={summaryId} onSubmit={generate} method="post">
        <label htmlFor={`${id}-request`}>{text.request}</label>
        <p id={`${id}-hint`}>{text.hint}</p>
        <input
          id={`${id}-request`}
          name="phrase"
          aria-describedby={`${id}-hint`}
          className="nxtbi-copilot-semantic__request"
          required
          maxLength={200}
          value={phrase}
          disabled={!!pending}
          onChange={event => {
            setPhrase(event.currentTarget.value);
            setChosenMetric('');
            setResult(undefined);
            setSaved(undefined);
            setError('');
          }}
        />
        {candidates && (
          <fieldset
            ref={choices}
            tabIndex={-1}
            disabled={!!pending}
            className="nxtbi-copilot-semantic__choices"
          >
            <legend>{text.choose}</legend>
            {candidates.map((metric, index) => {
              const optionId = `${id}-metric-${index}`;
              const descriptionId = `${optionId}-definition`;
              return (
                <div
                  className="nxtbi-copilot-semantic__choice"
                  key={metric.metricId}
                >
                  <input
                    id={optionId}
                    type="radio"
                    name={`${id}-metric`}
                    value={metric.metricId}
                    checked={chosenMetric === metric.metricId}
                    onChange={() => setChosenMetric(metric.metricId)}
                    aria-describedby={descriptionId}
                    required
                  />
                  <div>
                    <label htmlFor={optionId}>{metric.label}</label>
                    <p id={descriptionId}>
                      {metric.definition} <bdi>{metric.unit}</bdi>
                    </p>
                  </div>
                </div>
              );
            })}
          </fieldset>
        )}
        <button
          type="submit"
          disabled={
            !!pending || !phrase.trim() || (!!candidates && !chosenMetric)
          }
        >
          {pending === 'draft' ? text.generating : text.generate}
        </button>
      </form>
      <output>
        {result?.status === 'unmatched' && text.unmatched}
        {draft && !saved && !error && text.ready}
      </output>
      {error && (
        <p role="alert" className="nxtbi-copilot__error">
          {error}
        </p>
      )}
      {draft && (
        <section
          aria-labelledby={`${id}-title`}
          className="nxtbi-copilot-semantic__preview"
        >
          <h3 id={`${id}-title`}>{draft.title}</h3>
          <p>{draft.metric.definition}</p>
          <p className="nxtbi-copilot-semantic__total">
            <strong>{draft.metric.label}</strong>{' '}
            <bdi>{formatValue(draft.value)}</bdi> <bdi>{draft.metric.unit}</bdi>
          </p>
          {draft.rows.length > 0 && (
            <table>
              <caption>{text.preview}</caption>
              <thead>
                <tr>
                  <th scope="col">{text.propertyType}</th>
                  <th scope="col">{text.value}</th>
                </tr>
              </thead>
              <tbody>
                {draft.rows.map(row => (
                  <tr key={row.label}>
                    <th scope="row">
                      <bdi>{row.label}</bdi>
                    </th>
                    <td>
                      <bdi>{formatValue(row.value)}</bdi>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!saved && (
            <form aria-labelledby={`${id}-title`} onSubmit={save} method="post">
              <button
                type="submit"
                disabled={!!pending}
                className="nxtbi-copilot__primary"
              >
                {pending === 'save' ? text.saving : text.save}
              </button>
            </form>
          )}
          {saved && (
            <div className="nxtbi-copilot__saved">
              <output>{text.saved}</output>
              {href && <a href={href}>{text.open}</a>}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default function SemanticCatalogDraft(props: Props) {
  const { locale, transport } = props;
  const summaryId = useId();
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setAvailable(false);
    transport
      .available(controller.signal)
      .then(supported => {
        if (!controller.signal.aborted) setAvailable(supported);
      })
      .catch(() => {
        if (!controller.signal.aborted) setAvailable(false);
      });
    return () => controller.abort();
  }, [transport]);

  if (!available) return null;
  return (
    <details
      className="nxtbi-copilot-semantic"
      data-test="semantic-catalog-draft"
      dir={locale === 'ar' ? 'rtl' : 'ltr'}
      lang={locale}
    >
      <summary id={summaryId}>{copyByLocale[locale].name}</summary>
      <SemanticCatalogForm key={locale} {...props} summaryId={summaryId} />
    </details>
  );
}

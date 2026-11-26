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
import type { createSessionWriter } from './transport';

export interface SemanticMetric {
  metricId: string;
  label: string;
  definition: string;
  unit: string;
}

export interface SemanticDraftInput {
  phrase: string;
  locale: 'en' | 'ar';
  metricId?: string;
}

interface SemanticBreakdownRow {
  label: string;
  value: number | null;
}

export interface SemanticDraft {
  status: 'draft';
  metric: SemanticMetric;
  title: string;
  value: number | null;
  rows: SemanticBreakdownRow[];
  approvalToken: string;
}

export type SemanticDraftResult =
  | SemanticDraft
  | { status: 'ambiguous' | 'unmatched'; candidates: SemanticMetric[] };

export interface SemanticSavedDashboard {
  id: number;
  url: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isText(value: unknown, maxLength: number): value is string {
  return (
    typeof value === 'string' && value.length <= maxLength && !!value.trim()
  );
}

function isFiniteValue(value: unknown): value is number | null {
  return (
    value === null || (typeof value === 'number' && Number.isFinite(value))
  );
}

function isMetric(value: unknown): value is SemanticMetric {
  return (
    isRecord(value) &&
    typeof value.metricId === 'string' &&
    /^[a-z_][a-z0-9_]{0,79}$/.test(value.metricId) &&
    isText(value.label, 256) &&
    isText(value.definition, 1024) &&
    isText(value.unit, 64)
  );
}

function isBreakdownRow(value: unknown): value is SemanticBreakdownRow {
  return (
    isRecord(value) && isText(value.label, 256) && isFiniteValue(value.value)
  );
}

function readDraft(value: unknown): SemanticDraftResult {
  if (isRecord(value)) {
    const { status, candidates, metric, title, rows, approvalToken } = value;
    if (
      status === 'draft' &&
      isMetric(metric) &&
      isText(title, 256) &&
      isFiniteValue(value.value) &&
      Array.isArray(rows) &&
      rows.length <= 100 &&
      rows.every(isBreakdownRow) &&
      isText(approvalToken, 2048)
    ) {
      return { status, metric, title, value: value.value, rows, approvalToken };
    }
    if (
      (status === 'ambiguous' || status === 'unmatched') &&
      Array.isArray(candidates) &&
      candidates.length <= 8 &&
      candidates.every(isMetric) &&
      (status === 'ambiguous'
        ? candidates.length >= 2
        : candidates.length === 0) &&
      new Set(candidates.map(option => option.metricId)).size ===
        candidates.length
    ) {
      return { status, candidates };
    }
  }
  throw new Error('Superset returned an invalid semantic dashboard draft.');
}

async function readJson(
  response: Response,
  signal?: AbortSignal,
): Promise<unknown> {
  const value: unknown = await response.json().catch(() => undefined);
  signal?.throwIfAborted();
  return value;
}

export function createSemanticTransport(
  base: string,
  write: ReturnType<typeof createSessionWriter>,
) {
  return {
    async available(signal?: AbortSignal): Promise<boolean> {
      const response = await fetch(
        `${base}/api/v1/nxtbi_copilot/semantic_catalog`,
        {
          mode: 'same-origin',
          credentials: 'same-origin',
          redirect: 'error',
          cache: 'no-store',
          headers: { Accept: 'application/json' },
          signal,
        },
      );
      if ([401, 403, 404].includes(response.status)) return false;
      if (!response.ok)
        throw new Error('Could not check the semantic catalog.');
      const value = await readJson(response, signal);
      return isRecord(value) && value.available === true;
    },
    async draft(
      input: SemanticDraftInput,
      signal?: AbortSignal,
    ): Promise<SemanticDraftResult> {
      const { phrase, locale, metricId } = input;
      const response = await write(
        'semantic_catalog/draft',
        { phrase, locale, metricId },
        'application/json',
        signal,
      );
      if (!response.ok) {
        throw new Error('Superset could not draft a semantic dashboard.');
      }
      return readDraft(await readJson(response, signal));
    },
    async approve(
      approvalToken: string,
      signal?: AbortSignal,
    ): Promise<SemanticSavedDashboard> {
      const response = await write(
        'semantic_catalog/approve',
        { approvalToken },
        'application/json',
        signal,
      );
      if (response.status !== 200 && response.status !== 201) {
        throw new Error('Superset rejected the semantic dashboard approval.');
      }
      const value = await readJson(response, signal);
      if (
        !isRecord(value) ||
        typeof value.id !== 'number' ||
        !Number.isSafeInteger(value.id) ||
        value.id < 1 ||
        value.id > 2_147_483_647 ||
        value.url !== `/dashboard/${value.id}/`
      ) {
        throw new Error(
          'Superset returned an invalid semantic dashboard response.',
        );
      }
      return { id: value.id, url: value.url };
    },
  };
}

export type SemanticTransport = ReturnType<typeof createSemanticTransport>;

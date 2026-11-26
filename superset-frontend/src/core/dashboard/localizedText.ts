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
import { useDashboardStore } from './store';
import { useDashboardViewMode } from './viewMode';

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;

/** Reads the optional localization metadata from the canonical root props. */
export function readDashboardLocalization(
  value: unknown,
): Record<string, unknown> | undefined {
  const localization = asRecord(value);
  return localization?.sourceLocale === 'en' ||
    localization?.sourceLocale === 'ar'
    ? localization
    : undefined;
}

/** Displays a translation only while its source still matches the saved text. */
export function useDashboardLocalizedText(
  source: string,
  nodeId?: string,
  canonicalSource: string | null = source,
): string {
  const store = useDashboardStore();
  const mode = useDashboardViewMode();
  if (mode !== 'view' || canonicalSource === null) return source;

  // Superset's language switch reloads the page with the active locale in
  // the document, including for locales authored as a regional variant.
  const [locale] = document.documentElement.lang.toLowerCase().split(/[-_]/);
  if (locale !== 'ar' && locale !== 'en') return source;

  const localization = readDashboardLocalization(
    store.getRoot().props?.nxtbiLocalization,
  );
  if (localization?.sourceLocale === locale) return source;
  const entry = asRecord(
    nodeId === undefined
      ? localization?.title
      : asRecord(localization?.widgets)?.[nodeId],
  );
  const translation = asRecord(entry?.translations)?.[locale];
  return entry?.source === canonicalSource &&
    typeof translation === 'string' &&
    translation.trim()
    ? translation
    : source;
}

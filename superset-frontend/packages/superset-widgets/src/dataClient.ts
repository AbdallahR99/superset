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
import { createContext, useContext } from 'react';
import { SupersetClient } from '@superset-ui/core';
import { toAdhocFilters } from './activeFilters';
import { fetchQueryData, toFetchError } from './chartData';
import { widgetDataPayload } from './embed/httpClient';
import type {
  QueryDataResult,
  SavedWidget,
  WidgetDataBindingSpec,
  WidgetDataClient,
  WidgetRef,
} from './types';

export const WidgetDataClientContext = createContext<
  WidgetDataClient | undefined
>(undefined);

export function useWidgetDataClient(): WidgetDataClient {
  const client = useContext(WidgetDataClientContext);
  if (!client) {
    throw new Error(
      'Superset widgets must be rendered inside <SupersetProvider> (or a WidgetDataClientContext provider).',
    );
  }
  return client;
}

export function widgetRef(
  type: string,
  props: Record<string, unknown>,
  savedId?: string,
): WidgetRef {
  return savedId ? { id: savedId, type, props } : { type, props };
}

/**
 * Queries as the signed-in user. The builder sends native dataset queries to
 * chart data and approved semantic view bindings to the widget API.
 */
export const sessionDataClient: WidgetDataClient = {
  fetchData: async ({ widget, filters, signal }) => {
    const binding = widget.props.dataBinding as
      | WidgetDataBindingSpec
      | undefined;
    if (!binding) {
      throw new Error('This widget has no dataBinding.');
    }
    if (typeof binding.semanticViewId === 'string') {
      let json: { result?: QueryDataResult } | undefined;
      try {
        ({ json } = await SupersetClient.post({
          endpoint: '/api/v1/widget/data',
          jsonPayload: widgetDataPayload(widget, filters),
          signal,
        }));
      } catch (error) {
        throw await toFetchError(error);
      }
      if (!json?.result) {
        throw new Error('Widget data request returned no result');
      }
      return json.result;
    }
    return fetchQueryData(
      {
        ...binding,
        filters: [
          ...(binding.filters ?? []),
          ...filters.flatMap(filter => toAdhocFilters(filter)),
        ],
      },
      { signal },
    );
  },
  fetchValues: async ({ widget, signal }) => {
    const { datasetId, column } = widget.props as {
      datasetId?: number;
      column?: string;
    };
    if (datasetId == null || !column) return [];
    try {
      const { json } = await SupersetClient.get({
        endpoint: `/api/v1/datasource/table/${datasetId}/column/${encodeURIComponent(column)}/values/`,
        signal,
      });
      return (json.result as unknown[] | undefined) ?? [];
    } catch (error) {
      throw await toFetchError(error);
    }
  },
  getSavedWidget: async (id, options) => {
    try {
      const { json } = await SupersetClient.get({
        endpoint: `/api/v1/widget/${encodeURIComponent(id)}`,
        signal: options?.signal,
      });
      return json.result as SavedWidget;
    } catch (error) {
      throw await toFetchError(error);
    }
  },
};

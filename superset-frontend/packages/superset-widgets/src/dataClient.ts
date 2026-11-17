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
import type {
  DataBindingSpec,
  SavedWidget,
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
 * Queries through Superset's own session (`SupersetClient`): the ad hoc
 * chart-data path the dashboard builder uses, where the author is logged in
 * and may run any query their datasource permissions allow.
 */
export const sessionDataClient: WidgetDataClient = {
  fetchData: ({ widget, filters, signal }) => {
    const binding = widget.props.dataBinding as DataBindingSpec | undefined;
    if (!binding) {
      return Promise.reject(new Error('This widget has no dataBinding.'));
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

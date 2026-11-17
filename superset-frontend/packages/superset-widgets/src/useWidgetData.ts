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
import { useEffect, useRef, useState } from 'react';
import { getActiveResolvedFilters } from './activeFilters';
import { useWidgetBus, useWidgetBusRevision } from './bus';
import { useWidgetDataClient, widgetRef } from './dataClient';
import { toError, useWidgetErrorReporter } from './errors';
import type {
  DataBindingSpec,
  QueryDataResult,
  WidgetDataClient,
  WidgetProps,
} from './types';

export interface WidgetDataState {
  /** The rows for the widget's binding and the filters that apply to it. */
  result?: QueryDataResult;
  /** Why there are none. */
  error?: string;
  /** True until the request for the binding and filters on screen settles. */
  loading: boolean;
}

interface Settled {
  client: WidgetDataClient;
  key: string;
  result?: QueryDataResult;
  error?: string;
}

/**
 * The rows a data-bound widget draws, for whatever it is bound to at this
 * render: its `dataBinding`, every filter on the page that applies to it, and
 * the provider's data client.
 *
 * A widget never shows an answer to a question it is no longer asking. Each
 * change of binding, filters, saved id or client aborts the request in flight
 * and starts another; a response that still arrives for the old one is
 * dropped, and so is everything after the widget unmounts. Until the request
 * for what is on screen settles the hook reports `loading`, not the rows of
 * the one before.
 */
export function useWidgetData(
  type: string,
  { instanceId, props, savedId }: WidgetProps,
  missingBindingMessage = 'This widget has no dataBinding.',
): WidgetDataState {
  // Re-renders on every bus emit, so the filters that apply are recomputed.
  const bus = useWidgetBus();
  useWidgetBusRevision(bus);
  const client = useWidgetDataClient();
  const reportError = useWidgetErrorReporter();
  const [settled, setSettled] = useState<Settled>();

  const dataBinding = props.dataBinding as DataBindingSpec | undefined;
  // A query-bound widget does not subscribe to individual filter sources: it
  // recomputes which ones apply to it (see `activeFilters.ts`) on each render.
  const activeFilters = dataBinding
    ? getActiveResolvedFilters(bus, dataBinding.datasetId, instanceId)
    : [];
  const hasBinding = dataBinding !== undefined;
  // `props` and `activeFilters` are new objects on every render; the key is
  // their value, so only a real change starts a request.
  const key = JSON.stringify({ dataBinding, activeFilters, savedId });
  // What the request is built from is read when it starts, from the render
  // that produced the key it runs for.
  const latest = useRef({ props, activeFilters });
  latest.current = { props, activeFilters };

  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!hasBinding) return undefined;
    const request = latest.current;
    // Effects run after the render they belong to, and something may have
    // been emitted in between (a filter applying its default, the host's
    // filters on a shared bus). Asking with what the render saw would send a
    // request whose answer nobody wants, so this waits for the render that
    // sees the bus as it is; `retry` makes sure that render runs this again.
    const datasetId = (request.props.dataBinding as DataBindingSpec).datasetId;
    const filtersNow = getActiveResolvedFilters(bus, datasetId, instanceId);
    if (JSON.stringify(filtersNow) !== JSON.stringify(request.activeFilters)) {
      setRetry(count => count + 1);
      return undefined;
    }
    const controller = new AbortController();
    const { signal } = controller;
    let pending: Promise<QueryDataResult>;
    try {
      pending = client.fetchData({
        instanceId,
        widget: widgetRef(type, request.props, savedId),
        filters: request.activeFilters,
        signal,
      });
    } catch (thrown) {
      // A client that throws instead of rejecting fails the same way.
      pending = Promise.reject(thrown);
    }
    pending.then(
      result => {
        if (!signal.aborted) setSettled({ client, key, result });
      },
      (reason: unknown) => {
        if (signal.aborted) return;
        const error = toError(reason);
        setSettled({ client, key, error: error.message });
        reportError(error, {
          phase: 'data',
          instanceId,
          widgetType: type,
          savedId,
        });
      },
    );
    return () => controller.abort();
  }, [
    bus,
    client,
    hasBinding,
    instanceId,
    key,
    reportError,
    retry,
    savedId,
    type,
  ]);

  if (!hasBinding) {
    return { loading: false, error: missingBindingMessage };
  }
  const current =
    settled && settled.client === client && settled.key === key
      ? settled
      : undefined;
  return {
    result: current?.result,
    error: current?.error,
    loading: current === undefined,
  };
}

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
import { useCallback, useRef, useState } from 'react';
import { WidgetApiError, type WidgetErrorInfo } from '@apache-superset/widgets';

export interface ErrorEntry {
  key: number;
  time: string;
  /** `unauthorized`, `forbidden`, `not_found`… or `error` for anything else. */
  kind: string;
  status?: number;
  phase: string;
  widget: string;
  message: string;
}

/**
 * The host's side of `<SupersetProvider onError>`: every failure a widget
 * shows is also reported here, where a real app would send it to its own
 * monitoring. Nothing is thrown while rendering, so no error boundary of the
 * host is involved.
 */
export function useErrorLog(): [
  ErrorEntry[],
  (error: Error, info: WidgetErrorInfo) => void,
] {
  const [entries, setEntries] = useState<ErrorEntry[]>([]);
  const nextKey = useRef(0);
  const onError = useCallback((error: Error, info: WidgetErrorInfo) => {
    nextKey.current += 1;
    const entry: ErrorEntry = {
      key: nextKey.current,
      time: new Date().toLocaleTimeString(),
      kind: error instanceof WidgetApiError ? error.kind : 'error',
      status: error instanceof WidgetApiError ? error.status : undefined,
      phase: info.phase,
      widget: info.savedId ?? info.widgetType ?? info.instanceId ?? '',
      message: error.message,
    };
    setEntries(current => [entry, ...current].slice(0, 20));
  }, []);
  return [entries, onError];
}

export function ErrorLog({ entries }: { entries: ErrorEntry[] }) {
  return (
    <section className="card event-log">
      <h2>Errors reported to the host</h2>
      {entries.length === 0 ? (
        <p className="hint">
          Nothing so far. A refused token, missing access or a deleted widget
          would be listed here, through <code>onError</code>.
        </p>
      ) : (
        <ul>
          {entries.map(entry => (
            <li key={entry.key}>
              <time>{entry.time}</time>{' '}
              <code>
                {entry.kind}
                {entry.status ? ` ${entry.status}` : ''}
              </code>{' '}
              <span className="hint">
                {entry.phase}
                {entry.widget ? ` · ${entry.widget}` : ''}
              </span>
              <div>{entry.message}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

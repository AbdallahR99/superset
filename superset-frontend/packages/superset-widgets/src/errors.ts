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

/**
 * Why a widget could not be shown, in terms a host can act on: prompt a
 * sign-in, mint a wider token, drop a widget that was deleted.
 */
export type WidgetErrorKind =
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'invalid'
  | 'network'
  | 'config'
  | 'unknown';

/** A failed call to Superset, or a provider that cannot make one. */
export class WidgetApiError extends Error {
  readonly kind: WidgetErrorKind;

  /** The HTTP status, when Superset answered at all. */
  readonly status?: number;

  constructor(message: string, kind: WidgetErrorKind, status?: number) {
    super(message);
    this.name = 'WidgetApiError';
    this.kind = kind;
    this.status = status;
  }
}

export function errorKindForStatus(status: number): WidgetErrorKind {
  switch (status) {
    case 401:
      return 'unauthorized';
    case 403:
      return 'forbidden';
    case 404:
      return 'not_found';
    case 409:
      return 'conflict';
    case 400:
    case 422:
      return 'invalid';
    default:
      return 'unknown';
  }
}

/**
 * What the body of a refusal from Superset's widget API says, as one line.
 *
 * A refusal carries a `message` and, when it is about particular fields,
 * `errors: [{loc, message}]`. For a request that failed its schema the
 * `message` already is the first problem; for widget props it is only the
 * verdict ("Widget props failed validation.") and the reasons are in
 * `errors`, so both are read: an author who is told that validation failed
 * and not why cannot fix anything. Returns `undefined` for a body that says
 * nothing readable.
 */
export function describeErrorBody(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null) return undefined;
  const { message, errors } = body as { message?: unknown; errors?: unknown };
  const lines = (Array.isArray(errors) ? errors : [])
    .map(problem => {
      if (typeof problem === 'string') return problem;
      if (typeof problem !== 'object' || problem === null) return '';
      const { loc, message: text } = problem as {
        loc?: unknown;
        message?: unknown;
      };
      if (typeof text !== 'string' || text === '') return '';
      const where = Array.isArray(loc) ? loc.join('.') : '';
      return where !== '' ? `${where}: ${text}` : text;
    })
    .filter(line => line !== '');
  let summary = '';
  if (typeof message === 'string') {
    summary = message;
  } else if (message && typeof message === 'object') {
    // Marshmallow's own shape: `{field: [reason, ...]}`.
    summary = JSON.stringify(message);
  }
  // The summary of a schema error repeats its first problem.
  if (summary === '' || lines.includes(summary)) {
    return lines.length > 0 ? lines.join('; ') : undefined;
  }
  if (lines.length === 0) return summary;
  return `${summary.replace(/[.:\s]+$/, '')}: ${lines.join('; ')}`;
}

export const toError = (error: unknown): Error =>
  error instanceof Error ? error : new Error(String(error));

/** True for the rejection a cancelled `fetch` (or any aborted request) produces. */
export const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  (error as { name?: unknown }).name === 'AbortError';

/** Where in a widget's life an error happened. */
export type WidgetErrorPhase =
  | 'config'
  | 'definition'
  | 'data'
  | 'values'
  | 'extension'
  | 'render';

export interface WidgetErrorInfo {
  phase: WidgetErrorPhase;
  /** The widget's identity on the bus; absent for a provider-level error. */
  instanceId?: string;
  widgetType?: string;
  /** Set when the widget is a saved one. */
  savedId?: string;
}

export type WidgetErrorReporter = (error: Error, info: WidgetErrorInfo) => void;

const ignoreError: WidgetErrorReporter = () => {};

/**
 * Where widgets report what went wrong, besides showing it in place. A
 * provider points it at the host's `onError`; outside one it goes nowhere.
 */
export const WidgetErrorContext =
  createContext<WidgetErrorReporter>(ignoreError);

export const useWidgetErrorReporter = (): WidgetErrorReporter =>
  useContext(WidgetErrorContext);

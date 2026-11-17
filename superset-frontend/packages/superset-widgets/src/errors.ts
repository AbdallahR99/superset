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

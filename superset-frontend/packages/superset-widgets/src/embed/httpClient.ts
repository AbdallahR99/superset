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
import { WidgetApiError, errorKindForStatus, isAbortError } from '../errors';
import type { ResolvedFilter } from '../filterVocabulary';
import type {
  DataRow,
  SavedWidget,
  WidgetDataClient,
  WidgetRef,
} from '../types';

export interface ApiFetchOptions {
  /** Origin (and optional path prefix) of the Superset deployment. */
  supersetDomain: string;
  /** Omit to call with the browser's own Superset session instead. */
  getGuestToken?: () => Promise<string>;
  /**
   * Called with the token Superset answered 401 to, before the one retry:
   * drop it from whatever cache `getGuestToken` reads, so the retry carries
   * a fresh one.
   */
  invalidateGuestToken?: (rejected: string) => void;
  guestTokenHeaderName?: string;
  /**
   * Session mode only: send Superset's CSRF token with every request that
   * changes or posts something. On by default; turn it off for a deployment
   * that exempts the widget API or runs without CSRF protection.
   */
  csrf?: boolean;
}

export type HttpWidgetClientOptions = ApiFetchOptions;

/** Calls a Superset JSON API and unwraps its `result`. */
export type ApiFetch = <T>(path: string, init?: RequestInit) => Promise<T>;

const CSRF_TOKEN_PATH = '/api/v1/security/csrf_token/';
const CSRF_HEADER = 'X-CSRFToken';
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

async function responseMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      message?: unknown;
      errors?: { message?: string }[];
    } | null;
    if (typeof body?.message === 'string') return body.message;
    if (body?.message && typeof body.message === 'object') {
      // Marshmallow validation errors: `{field: [reason, ...]}`.
      return JSON.stringify(body.message);
    }
    if (Array.isArray(body?.errors)) {
      return body.errors.map(error => error.message).join('; ');
    }
  } catch {
    // Not JSON; fall back to the status text.
  }
  return response.statusText;
}

const selectorOf = (widget: WidgetRef) =>
  'id' in widget
    ? { id: widget.id }
    : { widget: { type: widget.type, props: widget.props } };

/**
 * What a non-2xx answer means for whoever is looking at the widget. With a
 * guest token the host's backend decides what the page may read, so the
 * message points there; with a session the viewer's own account does.
 */
async function toApiError(
  response: Response,
  base: string,
  guest: boolean,
): Promise<WidgetApiError> {
  const { status } = response;
  const detail = await responseMessage(response);
  const kind = errorKindForStatus(status);
  const suffix = detail ? `: ${detail}` : '';
  let message: string;
  switch (status) {
    case 401:
      message = guest
        ? `Superset rejected the guest token (401)${suffix}`
        : `Sign in to Superset at ${base} to see this widget.`;
      break;
    case 403:
      message = guest
        ? `The guest token does not grant access to this widget or its data (403)${suffix}`
        : `Your Superset account cannot access this data (403)${suffix}`;
      break;
    case 404:
      message = `Superset could not find what this widget refers to (404)${suffix}`;
      break;
    case 409:
      message = `Superset reported a conflict (409)${suffix}`;
      break;
    default:
      message = `${status}${suffix}`;
  }
  return new WidgetApiError(message, kind, status);
}

/**
 * One deployment's API, as one caller sees it. Everything it remembers — the
 * CSRF token — lives in this closure, so two of them never share a credential
 * even when they point at the same origin.
 */
export function createApiFetch({
  supersetDomain,
  getGuestToken,
  invalidateGuestToken,
  guestTokenHeaderName = 'X-GuestToken',
  csrf = true,
}: ApiFetchOptions): ApiFetch {
  const base = supersetDomain.replace(/\/+$/, '');
  const guest = getGuestToken !== undefined;
  let csrfToken: Promise<string> | undefined;

  async function send(
    path: string,
    init: RequestInit,
    headers: Record<string, string>,
  ): Promise<Response> {
    try {
      return await fetch(`${base}${path}`, {
        ...init,
        mode: 'cors',
        // A guest token is the whole credential: cookies stay home, so a
        // viewer's own Superset session can never widen what the token grants.
        credentials: guest ? 'omit' : 'include',
        headers,
      });
    } catch (error) {
      if (isAbortError(error)) throw error;
      const cause = error instanceof Error ? error.message : String(error);
      throw new WidgetApiError(
        `Could not reach Superset at ${base} (network failure or CORS refusal): ${cause}`,
        'network',
      );
    }
  }

  function fetchCsrfToken(): Promise<string> {
    if (!csrfToken) {
      // Shared by every caller of this client, so it carries nobody's abort
      // signal: one widget unmounting must not fail the others' requests.
      const request = send(
        CSRF_TOKEN_PATH,
        { method: 'GET' },
        { Accept: 'application/json' },
      )
        .then(async response => {
          if (!response.ok) throw await toApiError(response, base, false);
          const body = (await response.json()) as { result?: unknown };
          if (typeof body.result !== 'string' || body.result === '') {
            throw new WidgetApiError(
              'Superset did not return a CSRF token.',
              'unknown',
              response.status,
            );
          }
          return body.result;
        })
        .catch(error => {
          // A failure is never kept for the next caller.
          if (csrfToken === request) csrfToken = undefined;
          throw error;
        });
      csrfToken = request;
    }
    return csrfToken;
  }

  return async function call<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const method = (init.method ?? 'GET').toUpperCase();
    const needsCsrf = !guest && csrf && !SAFE_METHODS.has(method);

    const attempt = async (): Promise<{
      response: Response;
      token?: string;
    }> => {
      const token = getGuestToken ? await getGuestToken() : undefined;
      const headers: Record<string, string> = {
        Accept: 'application/json',
        ...(init.body != null ? { 'Content-Type': 'application/json' } : {}),
        ...(init.headers as Record<string, string> | undefined),
        ...(token ? { [guestTokenHeaderName]: token } : {}),
        ...(needsCsrf ? { [CSRF_HEADER]: await fetchCsrfToken() } : {}),
      };
      return {
        response: await send(path, { ...init, method }, headers),
        token,
      };
    };

    let { response, token } = await attempt();
    if (response.status === 401 && token && invalidateGuestToken) {
      // The token expired or was revoked between the host minting it and
      // Superset reading it: ask the host for another, once.
      invalidateGuestToken(token);
      ({ response, token } = await attempt());
    } else if (response.status === 400 && needsCsrf) {
      const detail = await responseMessage(response.clone());
      if (/csrf/i.test(detail)) {
        // The session (and with it the CSRF token) was replaced under us.
        csrfToken = undefined;
        ({ response, token } = await attempt());
      }
    }
    if (!response.ok) throw await toApiError(response, base, guest);
    const body = (await response.json()) as { result: T };
    return body.result;
  };
}

/**
 * Talks to Superset's widget API with `fetch` rather than the app-wide
 * `SupersetClient` singleton, so several providers (and several Superset
 * deployments) can live on one page.
 */
export function createHttpWidgetClient(
  options: HttpWidgetClientOptions,
): WidgetDataClient {
  const call = createApiFetch(options);

  return {
    async fetchData({ widget, filters, signal }) {
      const result = await call<{ columns?: string[]; rows?: DataRow[] }>(
        '/api/v1/widget/data',
        {
          method: 'POST',
          signal,
          body: JSON.stringify({
            ...selectorOf(widget),
            filters: filters.map(
              ({ column, operator, value }: ResolvedFilter) => ({
                column,
                operator,
                value,
              }),
            ),
          }),
        },
      );
      return { columns: result.columns ?? [], rows: result.rows ?? [] };
    },
    fetchValues: ({ widget, signal }) =>
      call<unknown[]>('/api/v1/widget/values', {
        method: 'POST',
        signal,
        body: JSON.stringify(selectorOf(widget)),
      }),
    getSavedWidget: (id, requestOptions) =>
      call<SavedWidget>(`/api/v1/widget/${encodeURIComponent(id)}`, {
        signal: requestOptions?.signal,
      }),
  };
}

/**
 * The client a provider hands out when it was given nothing to talk to: every
 * request fails with the same explanation, in the widget that made it, rather
 * than the provider throwing while it renders.
 */
export function createUnconfiguredClient(message: string): WidgetDataClient {
  const fail = <T>(): Promise<T> =>
    Promise.reject(new WidgetApiError(message, 'config'));
  return {
    fetchData: () => fail(),
    fetchValues: () => fail(),
    getSavedWidget: () => fail(),
  };
}

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
import { SupersetClient } from '@superset-ui/core';
import type { DocumentNode } from './DashboardProvider';

export const DOCUMENT_VERSION = 1;

export interface DashboardV2Document {
  version: number;
  nodes: Record<string, DocumentNode>;
}

export interface DashboardV2 {
  id: number;
  uuid: string;
  dashboard_title: string;
  changed_on?: string;
  /**
   * Which write of the document this is. The server hands it out on every
   * read and write and expects it back on the next write, which is how a
   * save based on a copy someone else has since replaced is told apart from
   * one that is not.
   */
  revision?: number;
  document: DashboardV2Document;
  embedded: { uuid: string; allowed_domains: string[] } | null;
  /**
   * Client-side only, never sent by the server as a field: set on the answer
   * to a create that the server recognised as a repeat (it answered `200`
   * rather than `201`). The dashboard is then returned as it is stored, which
   * is not necessarily what the repeated request carried.
   */
  replayed?: boolean;
}

/**
 * The server refused a save because the document was written by someone else
 * after the copy being saved was loaded.
 */
export class DashboardV2ConflictError extends Error {
  /** The revision the server holds, when the response said. */
  readonly revision: number | undefined;

  constructor(revision: number | undefined) {
    super('The dashboard was changed by someone else');
    this.name = 'DashboardV2ConflictError';
    this.revision = revision;
  }
}

const asRevision = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isInteger(value) ? value : undefined;

/**
 * The revision a response body carries. A refusal names the one the server
 * holds as `current_revision`; a successful response carries `revision`,
 * directly or under `result`.
 */
export function revisionOf(body: unknown): number | undefined {
  if (typeof body !== 'object' || body === null) return undefined;
  const record = body as Record<string, unknown>;
  return (
    asRevision(record.current_revision) ??
    asRevision(record.revision) ??
    revisionOf(record.result)
  );
}

/** The revision an `ETag` header names: `"3"`, `W/"3"` or a bare `3`. */
export function revisionOfETag(etag: string | null): number | undefined {
  const match = /^(?:W\/)?"?(\d+)"?$/.exec(etag?.trim() ?? '');
  return match ? Number(match[1]) : undefined;
}

/** A revision as the entity tag `If-Match` carries. */
export const toETag = (revision: number): string => `"${revision}"`;

/**
 * The longest name the API accepts for a dashboard. A longer one is cut to
 * this on its way out rather than refused with the rest of the save.
 */
export const MAX_TITLE_LENGTH = 500;

/** 409 is the contract; 412 is what a failed `If-Match` is called in HTTP. */
const isConflictStatus = (status: number): boolean =>
  status === 409 || status === 412;

async function toConflictError(
  error: unknown,
): Promise<DashboardV2ConflictError | undefined> {
  if (!(error instanceof Response) || !isConflictStatus(error.status)) {
    return undefined;
  }
  let body: unknown;
  try {
    body = await error.clone().json();
  } catch {
    body = undefined;
  }
  return new DashboardV2ConflictError(
    revisionOf(body) ?? revisionOfETag(error.headers.get('ETag')),
  );
}

/**
 * Whether a save that failed may nevertheless have been stored.
 *
 * A refusal the server wrote itself (4xx) is an answer: nothing was stored.
 * A request that never got an answer (the connection dropped, the client
 * timed out) or got one from something in between (a 5xx from a gateway) is
 * not: the server may have committed the save and only the acknowledgement
 * was lost. Retrying such a save blindly is how one dashboard is created
 * twice, or how an author is told that "someone else" saved over them when
 * it was their own save.
 */
export function isAmbiguousSaveFailure(error: unknown): boolean {
  if (error instanceof DashboardV2ConflictError) return false;
  if (
    typeof error === 'object' &&
    error !== null &&
    (error as { name?: unknown }).name === 'AbortError'
  ) {
    return false;
  }
  if (error instanceof Response) return error.status >= 500;
  return true;
}

const canonical = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(canonical);
  if (typeof value === 'object' && value !== null) {
    const record = value as Record<string, unknown>;
    const sorted: Record<string, unknown> = {};
    Object.keys(record)
      .sort()
      .forEach(key => {
        if (record[key] !== undefined) sorted[key] = canonical(record[key]);
      });
    return sorted;
  }
  return value;
};

/**
 * Whether two documents are the same document: the same nodes with the same
 * content, whatever order their keys are in and whether an absent value is
 * spelled `undefined` or left out (JSON does not carry the difference).
 */
export function sameDocumentNodes(
  left: Record<string, DocumentNode> | undefined,
  right: Record<string, DocumentNode> | undefined,
): boolean {
  if (left === undefined || right === undefined) return false;
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

/**
 * What a refused save said about particular widgets: the body's `errors`
 * object, keyed by node id, as one line per problem. Empty when the refusal
 * was not about widgets, or was not a readable response at all.
 */
export async function readNodeErrors(
  error: unknown,
): Promise<Record<string, string[]>> {
  if (!(error instanceof Response)) return {};
  let body: unknown;
  try {
    body = await error.clone().json();
  } catch {
    return {};
  }
  if (typeof body !== 'object' || body === null) return {};
  const { errors } = body as { errors?: unknown };
  if (typeof errors !== 'object' || errors === null || Array.isArray(errors)) {
    return {};
  }
  const result: Record<string, string[]> = {};
  Object.entries(errors as Record<string, unknown>).forEach(
    ([nodeId, problems]) => {
      const lines = (Array.isArray(problems) ? problems : [problems])
        .map(problem => {
          if (typeof problem === 'string') return problem;
          if (typeof problem !== 'object' || problem === null) return '';
          const { loc, message } = problem as {
            loc?: unknown;
            message?: unknown;
          };
          const text = typeof message === 'string' ? message : '';
          const where = Array.isArray(loc) ? loc.join('.') : '';
          return where !== '' && text !== '' ? `${where}: ${text}` : text;
        })
        .filter(line => line !== '');
      if (lines.length > 0) result[nodeId] = lines;
    },
  );
  return result;
}

export async function fetchDashboardV2(
  ref: string | number,
  { signal }: { signal?: AbortSignal } = {},
): Promise<DashboardV2> {
  const { json } = await SupersetClient.get({
    endpoint: `/api/v1/dashboard_v2/${encodeURIComponent(String(ref))}`,
    signal,
  });
  return json.result as DashboardV2;
}

/**
 * Creates the dashboard when `id` is omitted, updates it otherwise.
 *
 * An update names the revision it was based on, in the body
 * (`base_revision`) and as `If-Match`, and rejects with a
 * {@link DashboardV2ConflictError} when the server holds a different one.
 *
 * A create may carry a `uuid` the client made up for the unsaved document.
 * It becomes the dashboard's uuid, and a create repeated with the same one
 * writes nothing: the server answers `200` with the dashboard as stored,
 * which is returned here marked `replayed`.
 *
 * The contract is `nxtbi/docs/widgets/05-dashboard-v2-api-contract.md`.
 */
export async function saveDashboardV2({
  id,
  title,
  nodes,
  baseRevision,
  uuid,
  signal,
}: {
  id?: number;
  title: string;
  nodes: Record<string, DocumentNode>;
  baseRevision?: number;
  uuid?: string;
  signal?: AbortSignal;
}): Promise<DashboardV2> {
  const jsonPayload = {
    dashboard_title: title.slice(0, MAX_TITLE_LENGTH),
    document: { version: DOCUMENT_VERSION, nodes },
  };
  try {
    if (id === undefined) {
      const { json, response } = await SupersetClient.post({
        endpoint: '/api/v1/dashboard_v2/',
        jsonPayload:
          uuid === undefined ? jsonPayload : { ...jsonPayload, uuid },
        signal,
      });
      const created = json.result as DashboardV2;
      return response?.status === 200
        ? { ...created, replayed: true }
        : created;
    }
    const { json } = await SupersetClient.put({
      endpoint: `/api/v1/dashboard_v2/${id}`,
      jsonPayload:
        baseRevision === undefined
          ? jsonPayload
          : { ...jsonPayload, base_revision: baseRevision },
      headers:
        baseRevision === undefined
          ? undefined
          : { 'If-Match': toETag(baseRevision) },
      signal,
    });
    return json.result as DashboardV2;
  } catch (error) {
    throw (await toConflictError(error)) ?? error;
  }
}

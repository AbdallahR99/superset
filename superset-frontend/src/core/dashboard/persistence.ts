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
 * The contract is `nxtbi/docs/widgets/05-dashboard-v2-api-contract.md`.
 */
export async function saveDashboardV2({
  id,
  title,
  nodes,
  baseRevision,
  signal,
}: {
  id?: number;
  title: string;
  nodes: Record<string, DocumentNode>;
  baseRevision?: number;
  signal?: AbortSignal;
}): Promise<DashboardV2> {
  const jsonPayload = {
    dashboard_title: title.slice(0, MAX_TITLE_LENGTH),
    document: { version: DOCUMENT_VERSION, nodes },
  };
  try {
    const { json } =
      id === undefined
        ? await SupersetClient.post({
            endpoint: '/api/v1/dashboard_v2/',
            jsonPayload,
            signal,
          })
        : await SupersetClient.put({
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

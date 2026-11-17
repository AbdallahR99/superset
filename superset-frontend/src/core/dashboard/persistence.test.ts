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
import fetchMock from 'fetch-mock';
import {
  DashboardV2ConflictError,
  MAX_TITLE_LENGTH,
  fetchDashboardV2,
  revisionOf,
  revisionOfETag,
  saveDashboardV2,
} from './persistence';
import type { DocumentNode } from './DashboardProvider';

const NODES: Record<string, DocumentNode> = {
  root: { type: 'grid', children: [] },
};

const RESULT = {
  id: 5,
  uuid: 'u',
  dashboard_title: 'T',
  revision: 4,
  document: { version: 1, nodes: NODES },
  embedded: null,
};

afterEach(() => {
  fetchMock.clearHistory().removeRoutes();
});

const lastCall = () => {
  const call = fetchMock.callHistory.lastCall();
  if (!call) throw new Error('no request was made');
  return call;
};

const headerOf = (name: string): string | null =>
  new Headers(lastCall().options.headers as HeadersInit).get(name);

const bodyOf = (): Record<string, unknown> =>
  JSON.parse(lastCall().options.body as string);

test('a read returns the document with its revision', async () => {
  fetchMock.get('glob:*/api/v1/dashboard_v2/5', { result: RESULT });

  await expect(fetchDashboardV2(5)).resolves.toMatchObject({
    id: 5,
    revision: 4,
  });
});

test('a create posts the document and carries no revision', async () => {
  fetchMock.post('glob:*/api/v1/dashboard_v2/', { id: 5, result: RESULT });

  await saveDashboardV2({ title: 'T', nodes: NODES });

  expect(bodyOf()).toEqual({
    dashboard_title: 'T',
    document: { version: 1, nodes: NODES },
  });
  expect(headerOf('If-Match')).toBeNull();
});

test('an update names the revision it was based on, in the body and as If-Match', async () => {
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', { id: 5, result: RESULT });

  const result = await saveDashboardV2({
    id: 5,
    title: 'T',
    nodes: NODES,
    baseRevision: 3,
  });

  expect(bodyOf()).toMatchObject({ base_revision: 3 });
  // An entity tag, quoted as HTTP writes one.
  expect(headerOf('If-Match')).toBe('"3"');
  expect(result.revision).toBe(4);
});

test('a revision of zero is still sent', async () => {
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', { id: 5, result: RESULT });

  await saveDashboardV2({ id: 5, title: 'T', nodes: NODES, baseRevision: 0 });

  expect(bodyOf()).toMatchObject({ base_revision: 0 });
  expect(headerOf('If-Match')).toBe('"0"');
});

test('a name longer than the API accepts is cut rather than failing the save', async () => {
  fetchMock.post('glob:*/api/v1/dashboard_v2/', { id: 5, result: RESULT });

  await saveDashboardV2({ title: 'x'.repeat(600), nodes: NODES });

  expect(bodyOf().dashboard_title).toHaveLength(MAX_TITLE_LENGTH);
});

test('a 409 with only an ETag still says which revision the server holds', async () => {
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', {
    status: 409,
    body: { message: 'changed' },
    headers: { ETag: '"9"' },
  });

  const error = await saveDashboardV2({
    id: 5,
    title: 'T',
    nodes: NODES,
    baseRevision: 3,
  }).catch((caught: unknown) => caught);

  expect(error).toBeInstanceOf(DashboardV2ConflictError);
  expect((error as DashboardV2ConflictError).revision).toBe(9);
});

test('a 409 becomes a conflict carrying the revision the server holds', async () => {
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', {
    status: 409,
    body: { message: 'changed', current_revision: 7 },
  });

  const error = await saveDashboardV2({
    id: 5,
    title: 'T',
    nodes: NODES,
    baseRevision: 3,
  }).catch((caught: unknown) => caught);

  expect(error).toBeInstanceOf(DashboardV2ConflictError);
  expect((error as DashboardV2ConflictError).revision).toBe(7);
});

test('a 409 with no readable body is still a conflict, with no revision', async () => {
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', {
    status: 409,
    body: 'not json',
  });

  const error = await saveDashboardV2({
    id: 5,
    title: 'T',
    nodes: NODES,
    baseRevision: 3,
  }).catch((caught: unknown) => caught);

  expect(error).toBeInstanceOf(DashboardV2ConflictError);
  expect((error as DashboardV2ConflictError).revision).toBeUndefined();
});

test('any other failure is passed through as it was', async () => {
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', { status: 422, body: {} });

  const error = await saveDashboardV2({
    id: 5,
    title: 'T',
    nodes: NODES,
    baseRevision: 3,
  }).catch((caught: unknown) => caught);

  expect(error).toBeInstanceOf(Response);
  expect((error as Response).status).toBe(422);
});

test('the revision is read from a refusal and from a successful response', () => {
  expect(revisionOf({ message: 'changed', current_revision: 5 })).toBe(5);
  expect(revisionOf({ revision: 3 })).toBe(3);
  expect(revisionOf({ result: { revision: 4 } })).toBe(4);
  expect(revisionOf({ current_revision: 0 })).toBe(0);
  expect(revisionOf({ revision: '3' })).toBeUndefined();
  expect(revisionOf(null)).toBeUndefined();
  expect(revisionOf('409')).toBeUndefined();
});

test('an entity tag is read in each form the server may write it', () => {
  expect(revisionOfETag('"3"')).toBe(3);
  expect(revisionOfETag('W/"3"')).toBe(3);
  expect(revisionOfETag('3')).toBe(3);
  expect(revisionOfETag(' "12" ')).toBe(12);
  expect(revisionOfETag('*')).toBeUndefined();
  expect(revisionOfETag('"a"')).toBeUndefined();
  expect(revisionOfETag(null)).toBeUndefined();
});

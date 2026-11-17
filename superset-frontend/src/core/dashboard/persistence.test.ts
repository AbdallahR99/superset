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
  isAmbiguousSaveFailure,
  readNodeErrors,
  revisionOf,
  revisionOfETag,
  sameDocumentNodes,
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

test('a create carries the uuid it is given, and an update never does', async () => {
  fetchMock.post('glob:*/api/v1/dashboard_v2/', {
    status: 201,
    body: { id: 5, result: RESULT },
  });
  fetchMock.put('glob:*/api/v1/dashboard_v2/5', { id: 5, result: RESULT });
  const uuid = '6f0c2a3e-5b1d-4c8e-9f70-1a2b3c4d5e6f';

  const created = await saveDashboardV2({ title: 'T', nodes: NODES, uuid });
  expect(bodyOf()).toEqual({
    dashboard_title: 'T',
    document: { version: 1, nodes: NODES },
    uuid,
  });
  // 201: the row was made by this request.
  expect(created.replayed).toBeUndefined();

  await saveDashboardV2({
    id: 5,
    title: 'T',
    nodes: NODES,
    baseRevision: 3,
    uuid,
  });
  expect(bodyOf()).not.toHaveProperty('uuid');
});

test('a create the server answers with 200 is marked as a repeat', async () => {
  fetchMock.post('glob:*/api/v1/dashboard_v2/', {
    status: 200,
    body: { id: 5, result: RESULT },
  });

  const result = await saveDashboardV2({
    title: 'T',
    nodes: NODES,
    uuid: '6f0c2a3e-5b1d-4c8e-9f70-1a2b3c4d5e6f',
  });

  expect(result).toMatchObject({ id: 5, revision: 4, replayed: true });
});

test('a refusal is an answer, and anything short of one may have been stored', async () => {
  const response = (status: number) => new Response('{}', { status });

  expect(isAmbiguousSaveFailure(response(400))).toBe(false);
  expect(isAmbiguousSaveFailure(response(403))).toBe(false);
  expect(isAmbiguousSaveFailure(response(409))).toBe(false);
  expect(isAmbiguousSaveFailure(response(422))).toBe(false);
  expect(isAmbiguousSaveFailure(new DashboardV2ConflictError(4))).toBe(false);
  // The caller cancelled it; nobody is waiting for an answer.
  expect(
    isAmbiguousSaveFailure(new DOMException('Aborted', 'AbortError')),
  ).toBe(false);

  expect(isAmbiguousSaveFailure(new TypeError('Failed to fetch'))).toBe(true);
  expect(
    isAmbiguousSaveFailure({
      error: 'Request timed out',
      statusText: 'timeout',
    }),
  ).toBe(true);
  expect(isAmbiguousSaveFailure(response(502))).toBe(true);
  expect(isAmbiguousSaveFailure(response(504))).toBe(true);
});

test('two documents are the same whatever their key order and however absence is spelled', () => {
  const sent: Record<string, DocumentNode> = {
    root: { type: 'grid', layout: { columns: 24, gap: 16 }, children: ['a'] },
    a: {
      type: 'markdown',
      props: { content: 'x', nested: { one: 1, two: [1, { three: 3 }] } },
      style: undefined,
      layout: { col: undefined, colSpan: 4 },
    },
  };
  const stored: Record<string, DocumentNode> = {
    a: {
      layout: { colSpan: 4 },
      props: { nested: { two: [1, { three: 3 }], one: 1 }, content: 'x' },
      type: 'markdown',
    },
    root: { children: ['a'], layout: { gap: 16, columns: 24 }, type: 'grid' },
  };

  expect(sameDocumentNodes(sent, stored)).toBe(true);
  expect(
    sameDocumentNodes(sent, {
      ...stored,
      a: { ...stored.a, props: { content: 'y' } },
    }),
  ).toBe(false);
  // The order of children is content, not spelling.
  expect(
    sameDocumentNodes(
      { root: { type: 'grid', children: ['a', 'b'] } },
      { root: { type: 'grid', children: ['b', 'a'] } },
    ),
  ).toBe(false);
  expect(sameDocumentNodes(sent, undefined)).toBe(false);
});

test('a refusal about particular widgets is read as one line per problem, by node', async () => {
  const refusal = new Response(
    JSON.stringify({
      message: 'Widget props failed validation.',
      errors: {
        node_1: [
          { loc: ['dataBinding', 'rowLimit'], message: 'Must be positive' },
          { loc: [], message: 'Unknown column' },
          { message: '' },
        ],
        node_2: ['Plain text problem'],
        node_3: [],
      },
    }),
    { status: 422 },
  );

  await expect(readNodeErrors(refusal)).resolves.toEqual({
    node_1: ['dataBinding.rowLimit: Must be positive', 'Unknown column'],
    node_2: ['Plain text problem'],
  });
  // Reading it did not consume the response for whoever reads it next.
  await expect(refusal.json()).resolves.toMatchObject({
    message: 'Widget props failed validation.',
  });
});

test('a refusal that is not about widgets has no node errors', async () => {
  await expect(
    readNodeErrors(new Response('{"message":"no"}', { status: 403 })),
  ).resolves.toEqual({});
  await expect(
    readNodeErrors(new Response('not json', { status: 500 })),
  ).resolves.toEqual({});
  await expect(
    readNodeErrors(new Response('{"errors":["a","b"]}', { status: 422 })),
  ).resolves.toEqual({});
  await expect(readNodeErrors(new Error('offline'))).resolves.toEqual({});
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

test('a null layout, props or style on a node is the same as none, as the server stores it', () => {
  const sent = {
    root: { type: 'grid', children: ['a'] },
    a: { type: 'markdown', layout: null, props: null, style: null },
  } as unknown as Record<string, DocumentNode>;
  const stored: Record<string, DocumentNode> = {
    root: { type: 'grid', children: ['a'] },
    a: { type: 'markdown' },
  };

  expect(sameDocumentNodes(sent, stored)).toBe(true);
  expect(sameDocumentNodes(stored, sent)).toBe(true);
  // Only at the top of a node: a null inside props is content.
  expect(
    sameDocumentNodes(
      { ...stored, a: { type: 'markdown', props: { content: null } } },
      { ...stored, a: { type: 'markdown', props: {} } },
    ),
  ).toBe(false);
});

test('a refusal with 403 that names widgets is read like any other', async () => {
  // Written out as text: an object literal cannot carry `__proto__` as a key.
  const refusal = new Response(
    '{"message":"Forbidden","errors":{' +
      '"a":[{"loc":["dataBinding","datasetId"],"message":"No access"}],' +
      '"__proto__":["Reserved id"]}}',
    { status: 403 },
  );

  const errors = await readNodeErrors(refusal);
  expect(errors.a).toEqual(['dataBinding.datasetId: No access']);
  expect(Object.keys(errors).sort()).toEqual(['__proto__', 'a']);
  expect(Object.getOwnPropertyDescriptor(errors, '__proto__')?.value).toEqual([
    'Reserved id',
  ]);
  expect(isAmbiguousSaveFailure(refusal)).toBe(false);
});

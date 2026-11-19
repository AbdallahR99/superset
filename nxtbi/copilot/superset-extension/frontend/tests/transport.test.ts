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
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createSessionTransport } from '../src/transport.ts';

test('the session transport obtains CSRF then passes through the streaming response', async ({
  mock,
}) => {
  const result = new Response('data: {}\n\n', {
    headers: { 'Content-Type': 'text/event-stream' },
  });
  const fetchMock = mock.method(globalThis, 'fetch', async (url: string) =>
    url.endsWith('/csrf_token/')
      ? new Response(JSON.stringify({ result: 'fixture-csrf-token' }))
      : result,
  );
  const signal = new AbortController().signal;
  const transport = createSessionTransport('https://example.test/bi');
  const input = {
    threadId: 'thread-1',
    runId: 'run-1',
    state: {},
    messages: [],
    tools: [],
    context: [],
    forwardedProps: {},
  };
  assert.equal(await transport.run(input, signal), result);
  const calls = fetchMock.mock.calls.map(
    call => call.arguments as [string, RequestInit],
  );
  assert.deepEqual(
    calls.map(([url]) => url),
    [
      'https://example.test/bi/api/v1/security/csrf_token/',
      'https://example.test/bi/api/v1/nxtbi_copilot/run',
    ],
  );
  const [, post] = calls[1];
  assert.equal(post.credentials, 'same-origin');
  assert.equal(post.redirect, 'error');
  assert.equal(post.signal, signal);
  assert.equal(
    new Headers(post.headers).get('X-CSRFToken'),
    'fixture-csrf-token',
  );
  assert.deepEqual(JSON.parse(String(post.body)), input);
});

test('the session transport returns a protected approval reference', async ({
  mock,
}) => {
  mock.method(globalThis, 'fetch', async (url: string) =>
    url.endsWith('/csrf_token/')
      ? new Response(JSON.stringify({ result: 'fixture-csrf-token' }))
      : new Response(JSON.stringify({ id: 8, url: '/dashboard/v2/8/' }), {
          status: 201,
        }),
  );
  const transport = createSessionTransport('https://example.test');
  const proposal = {
    title: 'Draft',
    approvalToken: 'fixture-approval-token',
    widgets: [],
  };
  assert.deepEqual(
    await transport.approve(proposal, new AbortController().signal),
    {
      id: 8,
      url: '/dashboard/v2/8/',
    },
  );
});

test('Copilot history reads and writes transcripts through the authenticated Superset route', async ({
  mock,
}) => {
  const transcript = {
    threadId: 'thread-1',
    messages: [
      { id: 'message-1', role: 'user' as const, content: 'Show sales' },
    ],
    updatedAt: '2026-11-18T09:00:00.000Z',
    savedDashboard: { id: 8, url: '/dashboard/v2/8/' },
  };
  const fetchMock = mock.method(
    globalThis,
    'fetch',
    async (url: string, init: RequestInit) => {
      if (url.endsWith('/csrf_token/')) {
        return new Response(JSON.stringify({ result: 'fixture-csrf-token' }));
      }
      if (init.method === 'PUT') return new Response(null, { status: 204 });
      return new Response(JSON.stringify({ result: [transcript, null] }));
    },
  );
  const base = 'https://example.test/bi';
  const { history } = createSessionTransport(base);
  const signal = new AbortController().signal;
  assert.deepEqual(await history.list(signal), [transcript]);
  await history.save(transcript, signal);
  const calls = fetchMock.mock.calls.map(
    call => call.arguments as [string, RequestInit],
  );
  assert.deepEqual(
    calls.map(([url]) => url),
    [
      `${base}/api/v1/nxtbi_copilot/history`,
      `${base}/api/v1/security/csrf_token/`,
      `${base}/api/v1/nxtbi_copilot/history`,
    ],
  );
  assert.equal(calls[0][1].cache, 'no-store');
  const [, put] = calls[2];
  assert.equal(put.method, 'PUT');
  assert.equal(put.credentials, 'same-origin');
  assert.equal(put.signal, signal);
  assert.equal(
    new Headers(put.headers).get('X-CSRFToken'),
    'fixture-csrf-token',
  );
  assert.deepEqual(JSON.parse(String(put.body)), transcript);
});

test('approval rejects a link that does not match the saved dashboard ID', async ({
  mock,
}) => {
  mock.method(globalThis, 'fetch', async (url: string) =>
    url.endsWith('/csrf_token/')
      ? new Response(JSON.stringify({ result: 'fixture-csrf-token' }))
      : new Response(JSON.stringify({ id: 8, url: '/dashboard/test/' }), {
          status: 201,
        }),
  );
  const transport = createSessionTransport('https://example.test');
  await assert.rejects(
    transport.approve(
      { title: 'Draft', approvalToken: 'fixture-approval-token', widgets: [] },
      new AbortController().signal,
    ),
    /invalid dashboard response/,
  );
});

test('CSV import sends a protected multipart request and reuses its ID on retry', async ({
  mock,
}) => {
  const fetchMock = mock.method(globalThis, 'fetch', async (url: string) =>
    url.endsWith('/csrf_token/')
      ? new Response(JSON.stringify({ result: 'fixture-csrf-token' }))
      : new Response(JSON.stringify({ id: 12, name: 'Orders' }), {
          status: 201,
        }),
  );
  const { uploadDataset } = createSessionTransport('https://example.test/bi');
  const file = new File(['total\n42\n'], 'orders.csv', { type: 'text/csv' });
  const signal = new AbortController().signal;
  assert.deepEqual(await uploadDataset(file, signal), {
    id: 12,
    name: 'Orders',
  });
  await uploadDataset(file, signal);

  const requests = fetchMock.mock.calls
    .map(call => call.arguments as [string, RequestInit])
    .filter(([url]) => url.endsWith('/upload/'));
  assert.equal(requests.length, 2);
  const ids = [];
  for (const [url, request] of requests) {
    assert.equal(url, 'https://example.test/bi/api/v1/nxtbi_copilot/upload/');
    assert.equal(request.credentials, 'same-origin');
    assert.equal(request.redirect, 'error');
    assert.equal(request.signal, signal);
    const headers = new Headers(request.headers);
    assert.equal(headers.get('X-CSRFToken'), 'fixture-csrf-token');
    assert.equal(headers.has('Content-Type'), false);
    assert.ok(request.body instanceof FormData);
    const uploaded = request.body.get('file');
    assert.ok(uploaded instanceof File);
    assert.equal(uploaded.name, 'orders.csv');
    assert.equal(await uploaded.text(), 'total\n42\n');
    ids.push(request.body.get('upload_id'));
  }
  assert.ok(typeof ids[0] === 'string' && /^[a-f0-9-]{36}$/.test(ids[0]));
  assert.equal(ids[0], ids[1]);
});

test('CSV import reports unavailable destinations without returning a dataset', async ({
  mock,
}) => {
  mock.method(globalThis, 'fetch', async (url: string) =>
    url.endsWith('/csrf_token/')
      ? new Response(JSON.stringify({ result: 'fixture-csrf-token' }))
      : new Response(null, { status: 503 }),
  );
  const { uploadDataset } = createSessionTransport('https://example.test');
  await assert.rejects(
    uploadDataset(
      new File(['total\n42'], 'orders.csv'),
      new AbortController().signal,
    ),
    /upload destination is available/,
  );
});

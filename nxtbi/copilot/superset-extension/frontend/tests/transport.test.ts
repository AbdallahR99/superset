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

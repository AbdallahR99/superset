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
import { createSemanticTransport } from '../src/semanticTransport.ts';
import { createSessionWriter } from '../src/transport.ts';

const base = 'https://example.test/bi';
const prefix = `${base}/api/v1/nxtbi_copilot/semantic_catalog`;
const csrfEndpoint = `${base}/api/v1/security/csrf_token/`;
const metric = {
  metricId: 'weighted_price_per_sqm',
  label: 'السعر لكل متر مربع',
  definition: 'إجمالي الأسعار على إجمالي المساحة',
  unit: 'AED/m²',
};
const options = [
  {
    metricId: 'average_transaction_price',
    label: 'متوسط سعر المعاملة',
    definition: 'إجمالي الأسعار على عدد المعاملات',
    unit: 'AED',
  },
  metric,
];
const draft = {
  status: 'draft',
  metric,
  title: 'أسعار سوق العقارات',
  value: 3737.7049,
  rows: [
    { label: 'Villa', value: 2714.2857 },
    { label: 'Unknown', value: null },
  ],
  approvalToken: 'fixture-approval-token',
};

function transport() {
  return createSemanticTransport(base, createSessionWriter(base));
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status });
}

test('checks semantic catalog availability with the authenticated app prefix', async ({
  mock,
}) => {
  const fetchMock = mock.method(globalThis, 'fetch', async () =>
    json({ available: true }),
  );
  const { signal } = new AbortController();
  assert.equal(await transport().available(signal), true);

  const [url, request] = fetchMock.mock.calls[0].arguments as [
    string,
    RequestInit,
  ];
  assert.equal(url, prefix);
  assert.equal(request.mode, 'same-origin');
  assert.equal(request.credentials, 'same-origin');
  assert.equal(request.redirect, 'error');
  assert.equal(request.cache, 'no-store');
  assert.equal(request.signal, signal);
});

test('an unavailable lab capability is optional', async ({ mock }) => {
  mock.method(globalThis, 'fetch', async () => json({}, 404));
  assert.equal(await transport().available(), false);
});

test('sends a CSRF-authenticated Arabic request and locks the chosen metric', async ({
  mock,
}) => {
  const input = { phrase: 'متوسط سعر العقار', locale: 'ar' as const };
  const selected = { ...input, metricId: metric.metricId };
  const fetchMock = mock.method(
    globalThis,
    'fetch',
    async (url: string, request: RequestInit) => {
      if (url === csrfEndpoint) return json({ result: 'fixture-csrf' });
      return JSON.parse(String(request.body)).metricId
        ? json(draft)
        : json({ status: 'ambiguous', candidates: options });
    },
  );
  const { signal } = new AbortController();
  const session = transport();
  assert.deepEqual(await session.draft(input, signal), {
    status: 'ambiguous',
    candidates: options,
  });
  assert.deepEqual(await session.draft(selected, signal), draft);

  const calls = fetchMock.mock.calls.map(
    call => call.arguments as [string, RequestInit],
  );
  assert.deepEqual(
    calls.map(([url]) => url),
    [csrfEndpoint, `${prefix}/draft`, csrfEndpoint, `${prefix}/draft`],
  );
  for (const [index, payload] of [input, selected].entries()) {
    const [, request] = calls[index * 2 + 1];
    assert.equal(request.mode, 'same-origin');
    assert.equal(request.credentials, 'same-origin');
    assert.equal(request.redirect, 'error');
    assert.equal(request.method, 'POST');
    assert.equal(request.signal, signal);
    assert.equal(
      new Headers(request.headers).get('X-CSRFToken'),
      'fixture-csrf',
    );
    assert.deepEqual(JSON.parse(String(request.body)), payload);
  }
});

test('rejects a semantic preview containing non-numeric results', async ({
  mock,
}) => {
  mock.method(globalThis, 'fetch', async (url: string) =>
    url === csrfEndpoint
      ? json({ result: 'fixture-csrf' })
      : json({ ...draft, rows: [{ label: 'Villa', value: '2714.2857' }] }),
  );
  await assert.rejects(
    transport().draft({ phrase: 'Price', locale: 'en' }),
    /invalid semantic dashboard draft/i,
  );
});

test('approves a semantic dashboard and returns the matching Classic path', async ({
  mock,
}) => {
  const saved = { id: 8, url: '/dashboard/8/' };
  const fetchMock = mock.method(globalThis, 'fetch', async (url: string) =>
    url === csrfEndpoint ? json({ result: 'fixture-csrf' }) : json(saved, 201),
  );
  assert.deepEqual(await transport().approve(draft.approvalToken), saved);
  const [url, options] = fetchMock.mock.calls[1].arguments as [
    string,
    RequestInit,
  ];
  assert.equal(url, `${prefix}/approve`);
  assert.deepEqual(JSON.parse(String(options.body)), {
    approvalToken: draft.approvalToken,
  });
});

test('accepts only the approved Classic dashboard path after save', async ({
  mock,
}) => {
  const invalidPaths = [
    '/dashboard/9/',
    '/dashboard/v2/8/',
    '/dashboard/8/?standalone=1',
  ];
  const paths = invalidPaths.values();
  mock.method(globalThis, 'fetch', async (url: string) =>
    url === csrfEndpoint
      ? json({ result: 'fixture-csrf' })
      : json({ id: 8, url: paths.next().value }, 200),
  );
  for (const _ of invalidPaths) {
    await assert.rejects(
      transport().approve(draft.approvalToken),
      /invalid semantic dashboard response/i,
    );
  }
});

test('reports approval errors using a fixed error message', async ({
  mock,
}) => {
  mock.method(globalThis, 'fetch', async (url: string) =>
    url === csrfEndpoint
      ? json({ result: 'fixture-csrf' })
      : new Response('<p>Internal lab details</p>', { status: 403 }),
  );
  await assert.rejects(transport().approve(draft.approvalToken), {
    message: 'Superset rejected the semantic dashboard approval.',
  });
});

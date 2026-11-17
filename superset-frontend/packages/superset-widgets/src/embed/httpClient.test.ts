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
import { WidgetApiError } from '../errors';
import { createGuestTokenSource, guestTokenExpiry } from './guestToken';
import { createHttpWidgetClient, createUnconfiguredClient } from './httpClient';

const DOMAIN = 'https://superset.example.com/';
const BASE = 'https://superset.example.com';

const jsonResponse = (status: number, body: unknown): Response => {
  const response = {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: async () => body,
    clone: () => response,
  };
  return response as unknown as Response;
};

const tokenWithExp = (exp: number) =>
  `header.${btoa(JSON.stringify({ exp })).replace(/=+$/, '')}.signature`;

type Call = [string, RequestInit & { headers: Record<string, string> }];

let fetchMock: jest.Mock;
const originalFetch = global.fetch;
const calls = () => fetchMock.mock.calls as Call[];

/** Routes by path, so a test reads as what the server answers. */
function serve(routes: Record<string, (init: Call[1]) => Response>) {
  fetchMock.mockImplementation(async (url: string, init: Call[1]) => {
    const path = url.replace(BASE, '');
    const route = routes[path];
    if (!route) throw new Error(`unexpected request to ${path}`);
    return route(init);
  });
}

const csrfRoute = (token: string) => () => jsonResponse(200, { result: token });

async function waitForCalls(count: number): Promise<void> {
  for (let turn = 0; turn < 50 && calls().length < count; turn += 1) {
    // eslint-disable-next-line no-await-in-loop
    await Promise.resolve();
  }
}

beforeEach(() => {
  fetchMock = jest.fn();
  global.fetch = fetchMock;
});

afterAll(() => {
  global.fetch = originalFetch;
});

const inlineRequest = {
  instanceId: 'a',
  widget: { type: 'metric-tile', props: { dataBinding: { datasetId: 17 } } },
  filters: [
    { column: 'state', operator: 'IN' as const, value: ['CA'], datasource: 17 },
  ],
};

test('an inline widget posts its type and props with the guest token and no cookies', async () => {
  fetchMock.mockResolvedValue(
    jsonResponse(200, { result: { columns: ['n'], rows: [{ n: 1 }] } }),
  );
  const client = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'token-1',
  });

  const result = await client.fetchData(inlineRequest);

  expect(result).toEqual({ columns: ['n'], rows: [{ n: 1 }] });
  expect(calls()).toHaveLength(1);
  const [url, init] = calls()[0];
  expect(url).toBe(`${BASE}/api/v1/widget/data`);
  expect(init.method).toBe('POST');
  expect(init.mode).toBe('cors');
  expect(init.credentials).toBe('omit');
  expect(init.headers['X-GuestToken']).toBe('token-1');
  expect(init.headers['Content-Type']).toBe('application/json');
  // A guest token is the whole credential: no CSRF round trip, no CSRF header.
  expect(init.headers).not.toHaveProperty('X-CSRFToken');
  expect(JSON.parse(init.body as string)).toEqual({
    widget: { type: 'metric-tile', props: { dataBinding: { datasetId: 17 } } },
    filters: [{ column: 'state', operator: 'IN', value: ['CA'] }],
  });
});

test('the guest token header name can be changed to match the deployment', async () => {
  fetchMock.mockResolvedValue(jsonResponse(200, { result: [] }));
  const client = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'token-1',
    guestTokenHeaderName: 'X-Embed-Token',
  });

  await client.fetchValues({
    instanceId: 'a',
    widget: { type: 'filter.select', props: {} },
  });

  const [, init] = calls()[0];
  expect(init.headers['X-Embed-Token']).toBe('token-1');
  expect(init.headers).not.toHaveProperty('X-GuestToken');
});

test('session mode sends cookies and the CSRF token, fetched once per client', async () => {
  serve({
    '/api/v1/security/csrf_token/': csrfRoute('csrf-1'),
    '/api/v1/widget/values': () =>
      jsonResponse(200, { result: ['boy', 'girl'] }),
    '/api/v1/widget/data': () =>
      jsonResponse(200, { result: { columns: [], rows: [] } }),
  });
  const client = createHttpWidgetClient({ supersetDomain: DOMAIN });

  const values = await client.fetchValues({
    instanceId: 'a',
    widget: { id: 'uuid-1', type: 'filter.select', props: { column: 'x' } },
  });
  await client.fetchData(inlineRequest);

  expect(values).toEqual(['boy', 'girl']);
  const paths = calls().map(([url]) => url.replace(BASE, ''));
  expect(paths).toEqual([
    '/api/v1/security/csrf_token/',
    '/api/v1/widget/values',
    '/api/v1/widget/data',
  ]);
  calls().forEach(([, init]) => {
    expect(init.credentials).toBe('include');
    expect(init.headers).not.toHaveProperty('X-GuestToken');
  });
  const [, valuesInit] = calls()[1];
  expect(valuesInit.headers['X-CSRFToken']).toBe('csrf-1');
  // A saved widget is selected by id only: its stored definition runs.
  expect(JSON.parse(valuesInit.body as string)).toEqual({ id: 'uuid-1' });
  expect(calls()[2][1].headers['X-CSRFToken']).toBe('csrf-1');
});

test('a read needs no CSRF token, and it can be turned off for posts', async () => {
  serve({
    '/api/v1/widget/uuid-1': () =>
      jsonResponse(200, { result: { uuid: 'uuid-1' } }),
    '/api/v1/widget/values': () => jsonResponse(200, { result: [] }),
  });
  const client = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    csrf: false,
  });

  await client.getSavedWidget!('uuid-1');
  await client.fetchValues({
    instanceId: 'a',
    widget: { type: 'filter.select', props: {} },
  });

  expect(calls()).toHaveLength(2);
  const [, readInit] = calls()[0];
  expect(readInit.method).toBe('GET');
  expect(readInit.credentials).toBe('include');
  // No body, so no content type and no CORS preflight for a simple read.
  expect(readInit.headers).not.toHaveProperty('Content-Type');
  expect(calls()[1][1].headers).not.toHaveProperty('X-CSRFToken');
});

test('a CSRF token the server no longer accepts is fetched again, once', async () => {
  const csrfTokens = ['stale', 'fresh'];
  serve({
    '/api/v1/security/csrf_token/': () =>
      jsonResponse(200, { result: csrfTokens.shift() }),
    '/api/v1/widget/data': init =>
      init.headers['X-CSRFToken'] === 'fresh'
        ? jsonResponse(200, { result: { columns: ['n'], rows: [] } })
        : jsonResponse(400, { message: 'The CSRF token is invalid.' }),
  });
  const client = createHttpWidgetClient({ supersetDomain: DOMAIN });

  await expect(client.fetchData(inlineRequest)).resolves.toEqual({
    columns: ['n'],
    rows: [],
  });
  expect(calls()).toHaveLength(4);
});

test('a guest token Superset refuses is replaced through the host and the call retried once', async () => {
  const fetchToken = jest
    .fn()
    .mockResolvedValueOnce('expired')
    .mockResolvedValueOnce('renewed');
  const tokens = createGuestTokenSource(fetchToken);
  fetchMock.mockImplementation(async (_url: string, init: Call[1]) =>
    init.headers['X-GuestToken'] === 'renewed'
      ? jsonResponse(200, { result: { columns: ['n'], rows: [{ n: 2 }] } })
      : jsonResponse(401, { message: 'Token expired' }),
  );
  const client = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: () => tokens.get(),
    invalidateGuestToken: rejected => tokens.invalidate(rejected),
  });

  await expect(client.fetchData(inlineRequest)).resolves.toEqual({
    columns: ['n'],
    rows: [{ n: 2 }],
  });
  expect(fetchToken).toHaveBeenCalledTimes(2);
  expect(calls()).toHaveLength(2);

  // Still refused after a fresh token: reported, not retried forever.
  fetchMock.mockResolvedValue(jsonResponse(401, { message: 'Token revoked' }));
  fetchToken.mockResolvedValue('another');
  await expect(client.fetchData(inlineRequest)).rejects.toMatchObject({
    kind: 'unauthorized',
    status: 401,
    message: 'Superset rejected the guest token (401): Token revoked',
  });
  expect(calls()).toHaveLength(4);
});

test.each([
  [401, 'unauthorized', 'Superset rejected the guest token (401): nope'],
  [
    403,
    'forbidden',
    'The guest token does not grant access to this widget or its data (403): nope',
  ],
  [
    404,
    'not_found',
    'Superset could not find what this widget refers to (404): nope',
  ],
  [409, 'conflict', 'Superset reported a conflict (409): nope'],
  [400, 'invalid', '400: nope'],
  [500, 'unknown', '500: nope'],
])(
  'with a guest token, a %i is a %s error carrying the server message',
  async (status, kind, message) => {
    fetchMock.mockResolvedValue(jsonResponse(status, { message: 'nope' }));
    const client = createHttpWidgetClient({
      supersetDomain: DOMAIN,
      getGuestToken: async () => 'token-1',
    });

    const failure = await client.getSavedWidget!('uuid-1').catch(
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(WidgetApiError);
    expect(failure).toMatchObject({ status, kind, message });
    expect(calls()[0][0]).toBe(`${BASE}/api/v1/widget/uuid-1`);
  },
);

test('without a guest token, a 401 asks the viewer to sign in and a 403 names the account', async () => {
  const client = createHttpWidgetClient({ supersetDomain: DOMAIN });

  fetchMock.mockResolvedValue(jsonResponse(401, { msg: 'Not authorized' }));
  await expect(client.getSavedWidget!('uuid-1')).rejects.toMatchObject({
    kind: 'unauthorized',
    message:
      'Sign in to Superset at https://superset.example.com to see this widget.',
  });

  fetchMock.mockResolvedValue(jsonResponse(403, { message: 'Forbidden' }));
  await expect(client.getSavedWidget!('uuid-1')).rejects.toMatchObject({
    kind: 'forbidden',
    message: 'Your Superset account cannot access this data (403): Forbidden',
  });
});

test('validation errors and error lists are readable', async () => {
  const client = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'token-1',
  });

  fetchMock.mockResolvedValue(
    jsonResponse(400, { message: { filters: ['Unknown column'] } }),
  );
  await expect(client.fetchData(inlineRequest)).rejects.toThrow(
    '400: {"filters":["Unknown column"]}',
  );

  fetchMock.mockResolvedValue(
    jsonResponse(422, { errors: [{ message: 'one' }, { message: 'two' }] }),
  );
  await expect(client.fetchData(inlineRequest)).rejects.toThrow(
    '422: one; two',
  );
});

test('props the server refuses are reported with the reason, not only the verdict', async () => {
  const client = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'token-1',
  });

  // The control model's refusal of an ECharts option: the message is only
  // the verdict, and what to fix is in `errors`.
  fetchMock.mockResolvedValue(
    jsonResponse(422, {
      message: 'Widget props failed validation.',
      errors: [
        {
          loc: ['echartsOptions'],
          message:
            'Value error, echartsOptions.tooltip.formatter contains HTML markup',
        },
        {
          loc: ['dataBinding', 'rowLimit'],
          message: 'Input should be greater than 0',
        },
      ],
    }),
  );
  const refused = await client.fetchData(inlineRequest).catch(error => error);
  expect(refused).toBeInstanceOf(WidgetApiError);
  expect(refused).toMatchObject({ kind: 'invalid', status: 422 });
  expect(refused.message).toBe(
    '422: Widget props failed validation: ' +
      'echartsOptions: Value error, echartsOptions.tooltip.formatter contains HTML markup; ' +
      'dataBinding.rowLimit: Input should be greater than 0',
  );

  // A request that failed its schema: the message already is the first
  // problem, and is not said twice.
  fetchMock.mockResolvedValue(
    jsonResponse(400, {
      message: 'filters.0.operator: Must be one of: IN, NOT IN.',
      errors: [
        {
          loc: ['filters', '0', 'operator'],
          message: 'Must be one of: IN, NOT IN.',
        },
        { loc: ['widget'], message: 'Missing data for required field.' },
      ],
    }),
  );
  await expect(client.fetchData(inlineRequest)).rejects.toThrow(
    '400: filters.0.operator: Must be one of: IN, NOT IN.; widget: Missing data for required field.',
  );
});

test('a widget whose dataset was deleted says so, for data and for values', async () => {
  const client = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'token-1',
  });
  fetchMock.mockResolvedValue(
    jsonResponse(404, {
      message: 'The dataset this widget reads no longer exists.',
    }),
  );
  const expected =
    'Superset could not find what this widget refers to (404): The dataset this widget reads no longer exists.';

  const data = await client.fetchData(inlineRequest).catch(error => error);
  expect(data).toMatchObject({ kind: 'not_found', status: 404 });
  expect(data.message).toBe(expected);

  const values = await client
    .fetchValues({ instanceId: 'a', widget: inlineRequest.widget })
    .catch(error => error);
  expect(values).toMatchObject({ kind: 'not_found', status: 404 });
  expect(values.message).toBe(expected);
});

test('a network failure is its own kind of error, and a cancelled request stays a cancellation', async () => {
  const client = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'token-1',
  });

  fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
  await expect(client.fetchData(inlineRequest)).rejects.toMatchObject({
    kind: 'network',
    message:
      'Could not reach Superset at https://superset.example.com (network failure or CORS refusal): Failed to fetch',
  });

  const controller = new AbortController();
  fetchMock.mockImplementationOnce(
    (_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () =>
          reject(new DOMException('The operation was aborted.', 'AbortError')),
        );
      }),
  );
  const pending = client.fetchData({
    ...inlineRequest,
    signal: controller.signal,
  });
  // Once the request is on the wire, as when a widget unmounts mid-flight.
  await waitForCalls(2);
  controller.abort();

  await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
});

test('two clients on one origin keep their credentials apart', async () => {
  const seen: Record<string, string[]> = { alice: [], bob: [] };
  fetchMock.mockImplementation(async (_url: string, init: Call[1]) => {
    const token = init.headers['X-GuestToken'];
    seen[token === 'alice-token' ? 'alice' : 'bob'].push(token);
    return jsonResponse(200, { result: { columns: [], rows: [] } });
  });
  const alice = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'alice-token',
  });
  const bob = createHttpWidgetClient({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'bob-token',
  });

  await Promise.all([
    alice.fetchData(inlineRequest),
    bob.fetchData(inlineRequest),
    alice.fetchData(inlineRequest),
  ]);

  expect(seen).toEqual({
    alice: ['alice-token', 'alice-token'],
    bob: ['bob-token'],
  });
});

test('a provider with nothing to talk to fails each request with one explanation', async () => {
  const client = createUnconfiguredClient('needs a domain');

  await expect(client.fetchData(inlineRequest)).rejects.toMatchObject({
    kind: 'config',
    message: 'needs a domain',
  });
  await expect(client.getSavedWidget!('uuid-1')).rejects.toThrow(
    'needs a domain',
  );
  expect(fetchMock).not.toHaveBeenCalled();
});

test('guest tokens are reused until close to expiry, with one fetch for concurrent callers', async () => {
  const inAnHour = Math.floor(Date.now() / 1000) + 3600;
  const almostExpired = Math.floor(Date.now() / 1000) + 30;
  const fetchToken = jest
    .fn()
    .mockResolvedValueOnce(tokenWithExp(almostExpired))
    .mockResolvedValueOnce(tokenWithExp(inAnHour));
  const source = createGuestTokenSource(fetchToken);

  const [first, second] = await Promise.all([source.get(), source.get()]);
  expect(first).toBe(second);
  expect(fetchToken).toHaveBeenCalledTimes(1);

  // Inside the refresh margin, so the next call fetches a fresh token.
  const refreshed = await source.get();
  expect(refreshed).toBe(tokenWithExp(inAnHour));
  await source.get();
  expect(fetchToken).toHaveBeenCalledTimes(2);
  expect(guestTokenExpiry(refreshed)).toBe(inAnHour * 1000);
});

test('invalidating forgets only the token that was refused', async () => {
  const inAnHour = Math.floor(Date.now() / 1000) + 3600;
  const first = tokenWithExp(inAnHour);
  const second = tokenWithExp(inAnHour + 1);
  const fetchToken = jest
    .fn()
    .mockResolvedValueOnce(first)
    .mockResolvedValueOnce(second);
  const source = createGuestTokenSource(fetchToken);

  expect(await source.get()).toBe(first);
  // Two widgets were refused with the same token; the second report arrives
  // after the replacement and must not throw that away too.
  source.invalidate(first);
  expect(await source.get()).toBe(second);
  source.invalidate(first);
  expect(await source.get()).toBe(second);
  expect(fetchToken).toHaveBeenCalledTimes(2);
});

test('a broker that throws, times out or returns nothing rejects instead of escaping', async () => {
  const throwing = createGuestTokenSource(() => {
    throw new Error('broker down');
  });
  await expect(throwing.get()).rejects.toThrow('broker down');

  const empty = createGuestTokenSource(async () => '');
  await expect(empty.get()).rejects.toThrow(
    'fetchGuestToken did not return a token.',
  );

  jest.useFakeTimers();
  try {
    const slow = createGuestTokenSource(
      () => new Promise<string>(() => {}),
      50,
    );
    const pending = slow.get();
    jest.advanceTimersByTime(60);
    await expect(pending).rejects.toThrow(
      'fetchGuestToken timed out after 50ms',
    );
  } finally {
    jest.useRealTimers();
  }
});

/*
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

// Local-only guest-token broker: the piece of a host application's backend
// that asks Superset for a guest token on behalf of the page.
//
// What it does that a real broker must also do:
//   - keeps the Superset service account's credentials on the server, read
//     from the environment only;
//   - decides by itself what each token may read: the browser names an
//     audience, never a resource;
//   - grants exactly what the page renders (see `resourcesFor`);
//   - never logs or caches a token, and listens on the loopback interface.
//
// What it skips, and a real broker must add: authenticating the host
// application's own user before minting anything, and `rls` rules derived
// from that user (here they come from the environment, if at all).
import http from 'node:http';

try {
  // Loaded into the process environment; nothing below reads the file.
  process.loadEnvFile(new URL('.env', import.meta.url));
} catch {
  // No .env file: use the process environment as-is.
}

function required(name) {
  const value = process.env[name];
  if (!value) {
    console.error(
      `${name} is not set. Set it in the environment or in .env (see .env.example).`,
    );
    process.exit(1);
  }
  return value;
}

const list = value =>
  (value ?? '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean);

function datasetId(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw.trim() === '') return fallback;
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) {
    console.error(`${name} must be a dataset id (a positive whole number).`);
    process.exit(1);
  }
  return id;
}

const SUPERSET_URL = (
  process.env.SUPERSET_URL ?? 'http://localhost:8088'
).replace(/\/+$/, '');
const USERNAME = required('SUPERSET_USERNAME');
const PASSWORD = required('SUPERSET_PASSWORD');
const PORT = Number(process.env.BROKER_PORT ?? 3001);
const ALLOWED_ORIGIN =
  process.env.BROKER_ALLOWED_ORIGIN ?? 'http://localhost:5173';

const DATASET_A = datasetId('FILTER_DATASET_ID', 17);
const DATASET_B = datasetId('EMBED_B_DATASET_ID', DATASET_A);

/**
 * The grant for inline widget definitions against one dataset.
 *
 * Superset serves an inline, SQL-free definition (a widget whose props the
 * page itself wrote) only to a token that carries this explicit resource. A
 * `dashboard` or `widget` resource never implies it, and the `datasets`
 * claim does not grant it either: that claim only narrows a dashboard token.
 * Superset checks at mint time that the service account can read the dataset.
 */
function inlineDatasetGrant(id) {
  return { type: 'dataset', id: String(id) };
}

/** The grant for one saved widget, by uuid, and the dataset it binds when the token is minted. */
function savedWidgetGrant(uuid) {
  return { type: 'widget', id: uuid };
}

/**
 * What a token for each audience may read. Two audiences stand in for two
 * users or tenants of the host application: the page's two independent
 * providers each ask for their own, and neither token opens the other's data
 * unless both happen to be configured with the same dataset.
 */
const AUDIENCES = {
  a: {
    username: 'widgets-demo-a',
    resources: () => [
      ...list(process.env.EMBED_WIDGET_IDS).map(savedWidgetGrant),
      inlineDatasetGrant(DATASET_A),
    ],
    rls: () => rlsFor(DATASET_A, process.env.BROKER_RLS_A),
  },
  b: {
    username: 'widgets-demo-b',
    resources: () => [inlineDatasetGrant(DATASET_B)],
    rls: () => rlsFor(DATASET_B, process.env.BROKER_RLS_B),
  },
};

/**
 * Row-level rules for the token. A real broker derives the clause from its
 * own authenticated user (never from the request). Superset refuses a
 * `widget` or `dataset` grant on a dataset that carries RLS rules unless a
 * token rule covers that dataset, or the deployment installs
 * `GUEST_TOKEN_VALIDATOR_HOOK`.
 */
function rlsFor(dataset, clause) {
  return clause && clause.trim() ? [{ dataset, clause: clause.trim() }] : [];
}

async function supersetJson(path, init, what) {
  const response = await fetch(`${SUPERSET_URL}${path}`, init);
  const text = await response.text();
  if (!response.ok) {
    // An error body carries Superset's reason, never a token.
    throw new Error(`${what} failed: ${response.status} ${text.slice(0, 300)}`);
  }
  return { response, body: text ? JSON.parse(text) : {} };
}

async function mintGuestToken(audience) {
  const { body: login } = await supersetJson(
    '/api/v1/security/login',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: USERNAME,
        password: PASSWORD,
        provider: 'db',
        refresh: false,
      }),
    },
    'Superset login',
  );
  const headers = {
    Authorization: `Bearer ${login.access_token}`,
    'Content-Type': 'application/json',
    Referer: SUPERSET_URL,
  };

  // guest_token is CSRF-protected unless WTF_CSRF_ENABLED is off; the CSRF
  // token is bound to the session cookie issued with it.
  try {
    const { response, body } = await supersetJson(
      '/api/v1/security/csrf_token/',
      { headers: { Authorization: headers.Authorization } },
      'CSRF token',
    );
    headers['X-CSRFToken'] = body.result;
    const cookies = response.headers
      .getSetCookie()
      .map(cookie => cookie.split(';')[0]);
    if (cookies.length > 0) headers.Cookie = cookies.join('; ');
  } catch {
    console.warn(
      'Continuing without a CSRF token (the request for one failed).',
    );
  }

  const { body } = await supersetJson(
    '/api/v1/security/guest_token/',
    {
      method: 'POST',
      headers,
      body: JSON.stringify({
        user: {
          username: audience.username,
          first_name: 'Widgets',
          last_name: 'Demo',
        },
        resources: audience.resources(),
        rls: audience.rls(),
      }),
    },
    'Guest token',
  );
  if (typeof body.token !== 'string' || body.token === '') {
    throw new Error('Guest token failed: Superset answered without a token');
  }
  return body.token;
}

const NO_STORE = {
  'Cache-Control': 'no-store',
  'Content-Type': 'text/plain; charset=utf-8',
};

http
  .createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    if (req.method !== 'POST' || url.pathname !== '/api/guest-token') {
      res.writeHead(404, NO_STORE).end();
      return;
    }
    // Browsers send Origin on a cross-site POST; a page other than the host
    // app has no business asking for its tokens.
    const { origin } = req.headers;
    if (origin && origin !== ALLOWED_ORIGIN) {
      res.writeHead(403, NO_STORE).end('Origin not allowed');
      return;
    }
    const name = url.searchParams.get('audience') ?? 'a';
    const audience = Object.hasOwn(AUDIENCES, name)
      ? AUDIENCES[name]
      : undefined;
    if (!audience) {
      res.writeHead(400, NO_STORE).end('Unknown audience');
      return;
    }
    try {
      const token = await mintGuestToken(audience);
      // The token goes to the caller and nowhere else: not to the log.
      console.log(
        `Minted a guest token for audience "${name}" (${audience.resources().length} resource(s)).`,
      );
      res.writeHead(200, NO_STORE).end(token);
    } catch (err) {
      console.error(`Audience "${name}": ${err.message}`);
      // The browser learns that it failed; the reason stays in this log.
      res
        .writeHead(502, NO_STORE)
        .end('The token broker could not get a guest token; see its log.');
    }
  })
  .listen(PORT, '127.0.0.1', () => {
    console.log(
      `Guest-token broker on http://127.0.0.1:${PORT} (Superset: ${SUPERSET_URL})`,
    );
  });

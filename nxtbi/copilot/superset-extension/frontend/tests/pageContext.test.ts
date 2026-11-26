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
import {
  dashboardActionLink,
  dashboardDestination,
  deploymentBase,
  readPageContext,
  resolveDashboardLink,
} from '../src/pageContext.ts';

const base = 'https://analytics.example.test/bi';

test('derives app-root from the same-origin Superset extension directory', () => {
  assert.equal(
    deploymentBase(
      'https://analytics.example.test',
      `${base}/api/v1/extensions/nxtbi/ai-copilot/`,
    ),
    base,
  );
  assert.equal(
    deploymentBase(
      'https://analytics.example.test',
      'https://cdn.example.test/',
    ),
    'https://analytics.example.test',
  );
});

test('captures a dashboard draft or saved ID without sharing the URL', () => {
  assert.deepEqual(
    readPageContext(
      base,
      'dashboard_v2',
      new URL(`${base}/dashboard/v2/75/?secret=example`),
    ),
    { page: 'dashboard_v2', dashboardId: 75 },
  );
  assert.deepEqual(
    readPageContext(base, 'dashboard_v2', new URL(`${base}/dashboard/v2/new/`)),
    { page: 'dashboard_v2' },
  );
});

test('captures only allowlisted entity references from Explore and dataset routes', () => {
  assert.deepEqual(
    readPageContext(
      base,
      'explore',
      new URL(
        `${base}/explore/?slice_id=21&datasource_type=table&datasource_id=8&form_data=private`,
      ),
    ),
    { page: 'explore', chartId: 21, datasetId: 8 },
  );
  assert.deepEqual(
    readPageContext(base, 'dataset', new URL(`${base}/dataset/23`)),
    { page: 'dataset', datasetId: 23 },
  );
  assert.deepEqual(
    readPageContext(
      base,
      'explore',
      new URL(`${base}/explore/p/private-key?form_data=private`),
    ),
    { page: 'explore' },
  );
});

test('uses SQL Lab database ID while keeping user SQL and schema names local', () => {
  assert.deepEqual(
    readPageContext(base, 'sqllab', new URL(`${base}/sqllab/?sql=private`), {
      databaseId: 5,
    }),
    { page: 'sqllab', databaseId: 5 },
  );
});

test('keeps exact app-relative post-approval navigation on the current deployment', () => {
  assert.equal(
    resolveDashboardLink(base, '/dashboard/v2/8/'),
    `${base}/dashboard/v2/8/`,
  );
  assert.equal(
    resolveDashboardLink(base, '/bi/dashboard/v2/8/'),
    `${base}/dashboard/v2/8/`,
  );
  assert.equal(
    resolveDashboardLink(base, '/dashboard/8/'),
    `${base}/dashboard/8/`,
  );
  assert.equal(resolveDashboardLink(base, '/dashboard/sales/'), undefined);
  assert.equal(
    resolveDashboardLink(base, '/dashboard/8/?edit=true'),
    undefined,
  );
  assert.equal(
    resolveDashboardLink(base, 'https://other.example.test/dashboard/v2/8/'),
    undefined,
  );
});

test('constructs the user-requested dashboard destination from its numeric ID', () => {
  assert.equal(
    dashboardActionLink(base, { dashboardId: 8 }),
    `${base}/dashboard/v2/8/`,
  );
  assert.equal(
    dashboardActionLink(base, { dashboardId: 8 }, 'classic'),
    `${base}/dashboard/8/`,
  );
  assert.equal(dashboardActionLink(base, { dashboardId: '8' }), undefined);
  assert.equal(
    dashboardActionLink(base, { url: '/dashboard/v2/8/' }),
    undefined,
  );
});

test('resolves Dashboard V2 first and uses the classic route only for HTTP 404', async ({
  mock,
}) => {
  const statuses = [200, 404, 403];
  const request = mock.method(
    globalThis,
    'fetch',
    async () => new Response(null, { status: statuses.shift() }),
  );
  const id = { dashboardId: 8 };
  assert.equal(await dashboardDestination(base, id), `${base}/dashboard/v2/8/`);
  assert.equal(await dashboardDestination(base, id), `${base}/dashboard/8/`);
  assert.equal(await dashboardDestination(base, id), undefined);
  assert.equal(
    await dashboardDestination(base, { dashboardId: '8' }),
    undefined,
  );
  assert.equal(request.mock.calls.length, 3);
});

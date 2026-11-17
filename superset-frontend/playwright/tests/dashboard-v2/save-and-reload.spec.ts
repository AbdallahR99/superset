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

/**
 * Dashboard v2 — saving, loading, and what happens when two copies of one
 * dashboard are saved.
 *
 * These need a real server: what is under test is the agreement between the
 * builder and the API about which revision a save is based on, and a mocked
 * API would only ever agree with the mock. Each test creates its own
 * dashboard and deletes it afterwards.
 *
 * Requires the DASHBOARD_V2 feature flag on the server under test (the tests
 * skip themselves when it is off); run with:
 *   npm run playwright:test \
 *     playwright/tests/dashboard-v2/save-and-reload.spec.ts
 */
import { Page, test, expect } from '@playwright/test';
import { DashboardV2Page } from '../../pages/DashboardV2Page';
import { apiDeleteDashboard } from '../../helpers/api/dashboard';
import { apiGet, apiPut } from '../../helpers/api/requests';
import { skipUnlessFeatureEnabled } from '../../helpers/featureFlags';
import { gotoWithRetry } from '../../helpers/navigation';

const API = 'api/v1/dashboard_v2/';

interface StoredNode {
  type: string;
  children?: string[];
  props?: Record<string, unknown>;
}

interface StoredDashboard {
  id: number;
  revision: number;
  dashboard_title: string;
  document: { version: number; nodes: Record<string, StoredNode> };
}

/** A name no other run of these tests has used. */
const uniqueName = (label: string): string =>
  `pw-dashboard-v2-${label}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

/** Every write the builder sends to the Dashboard v2 API, in order. */
function captureWrites(
  page: Page,
): { method: string; body: Record<string, unknown>; ifMatch: string | null }[] {
  const writes: {
    method: string;
    body: Record<string, unknown>;
    ifMatch: string | null;
  }[] = [];
  page.on('request', request => {
    const method = request.method();
    if (
      request.url().includes(`/${API}`) &&
      (method === 'POST' || method === 'PUT')
    ) {
      writes.push({
        method,
        body: request.postDataJSON() ?? {},
        ifMatch: request.headers()['if-match'] ?? null,
      });
    }
  });
  return writes;
}

async function readDashboard(page: Page, id: number): Promise<StoredDashboard> {
  const response = await apiGet(page, `${API}${id}`);
  return (await response.json()).result as StoredDashboard;
}

/**
 * Saves a change to the dashboard from outside the page under test: the
 * other editor, in the other tab. Adds one markdown node and returns its id.
 */
async function saveFromElsewhere(page: Page, id: number): Promise<string> {
  const current = await readDashboard(page, id);
  const addedId = `elsewhere_${Date.now()}`;
  const { nodes } = current.document;
  await apiPut(page, `${API}${id}`, {
    dashboard_title: current.dashboard_title,
    base_revision: current.revision,
    document: {
      version: current.document.version,
      nodes: {
        ...nodes,
        root: {
          ...nodes.root,
          children: [...(nodes.root.children ?? []), addedId],
        },
        [addedId]: { type: 'markdown', props: { content: 'From elsewhere' } },
      },
    },
  });
  return addedId;
}

async function removeDashboard(page: Page, id: number | undefined) {
  if (id === undefined) return;
  await apiDeleteDashboard(page, id, { failOnStatusCode: false });
}

/** A new dashboard with one widget on it, saved; returns its id. */
async function createSavedDashboard(
  dashboard: DashboardV2Page,
  name: string,
): Promise<number> {
  await dashboard.goto();
  await dashboard.rename(name);
  await dashboard.placeBlockByClick('markdown');
  return dashboard.saveNew();
}

test('a first save creates the dashboard once, moves to its route, and keeps what is on screen', async ({
  page,
}) => {
  const dashboard = new DashboardV2Page(page);
  const name = uniqueName('create');
  let id: number | undefined;
  try {
    await dashboard.goto();
    const writes = captureWrites(page);
    await dashboard.rename(name);
    await dashboard.placeBlockByClick('markdown');
    await expect(dashboard.unsavedIndicator).toBeVisible();

    id = await dashboard.saveNew();

    // One create, and nothing after it: moving to the saved route is the
    // same dashboard under its id, not a second save and not a reload.
    expect(writes.map(write => write.method)).toEqual(['POST']);
    await expect(dashboard.gridItems()).toHaveCount(1);
    await expect(dashboard.unsavedIndicator).toHaveCount(0);

    const stored = await readDashboard(page, id);
    expect(stored.dashboard_title).toBe(name);
    expect(stored.document.nodes.root.children).toHaveLength(1);
  } finally {
    await removeDashboard(page, id);
  }
});

test('a saved dashboard comes back as it was saved after a full reload', async ({
  page,
}) => {
  const dashboard = new DashboardV2Page(page);
  const name = uniqueName('reload');
  let id: number | undefined;
  try {
    id = await createSavedDashboard(dashboard, name);

    await page.reload();
    await dashboard.canvas.waitFor();

    await expect(dashboard.gridItems()).toHaveCount(1);
    await expect(dashboard.title).toHaveValue(name);
    await expect(dashboard.unsavedIndicator).toHaveCount(0);
  } finally {
    await removeDashboard(page, id);
  }
});

test('a later save updates the same dashboard, based on the revision it holds', async ({
  page,
}) => {
  const dashboard = new DashboardV2Page(page);
  let id: number | undefined;
  try {
    id = await createSavedDashboard(dashboard, uniqueName('update'));
    const before = await readDashboard(page, id);
    const writes = captureWrites(page);

    await dashboard.showPalette();
    await dashboard.palette('markdown').click();
    await expect(dashboard.gridItems()).toHaveCount(2);
    await expect(dashboard.unsavedIndicator).toBeVisible();
    await dashboard.saveButton.click();
    await expect(dashboard.unsavedIndicator).toHaveCount(0);

    expect(writes).toHaveLength(1);
    expect(writes[0].method).toBe('PUT');
    expect(writes[0].body.base_revision).toBe(before.revision);
    expect(writes[0].ifMatch).toBe(`"${before.revision}"`);

    const after = await readDashboard(page, id);
    expect(after.revision).toBeGreaterThan(before.revision);
    expect(after.document.nodes.root.children).toHaveLength(2);
  } finally {
    await removeDashboard(page, id);
  }
});

test('a save based on a copy someone else replaced is refused, and reloading shows their copy', async ({
  page,
}) => {
  const dashboard = new DashboardV2Page(page);
  let id: number | undefined;
  try {
    id = await createSavedDashboard(dashboard, uniqueName('conflict-reload'));
    await saveFromElsewhere(page, id);
    const theirs = await readDashboard(page, id);

    await dashboard.showPalette();
    await dashboard.palette('markdown').click();
    await expect(dashboard.gridItems()).toHaveCount(2);
    await dashboard.saveButton.click();

    await expect(dashboard.conflictDialog).toBeVisible();
    // Refused means refused: the server still holds exactly their copy.
    expect((await readDashboard(page, id)).revision).toBe(theirs.revision);

    await dashboard.conflictReload.click();

    await expect(dashboard.conflictDialog).toHaveCount(0);
    await expect(dashboard.unsavedIndicator).toHaveCount(0);
    // Their two widgets, not the one added here.
    await expect(dashboard.gridItems()).toHaveCount(2);
    expect((await readDashboard(page, id)).revision).toBe(theirs.revision);
  } finally {
    await removeDashboard(page, id);
  }
});

test('overwriting after a conflict replaces their copy with the one on screen, on purpose', async ({
  page,
}) => {
  const dashboard = new DashboardV2Page(page);
  let id: number | undefined;
  try {
    id = await createSavedDashboard(
      dashboard,
      uniqueName('conflict-overwrite'),
    );
    const theirNodeId = await saveFromElsewhere(page, id);
    const theirs = await readDashboard(page, id);

    await dashboard.showPalette();
    await dashboard.palette('markdown').click();
    await dashboard.saveButton.click();
    await expect(dashboard.conflictDialog).toBeVisible();

    await dashboard.conflictOverwrite.click();

    await expect(dashboard.conflictDialog).toHaveCount(0);
    await expect(dashboard.unsavedIndicator).toHaveCount(0);
    const mine = await readDashboard(page, id);
    expect(mine.revision).toBeGreaterThan(theirs.revision);
    expect(Object.keys(mine.document.nodes)).not.toContain(theirNodeId);
    expect(mine.document.nodes.root.children).toHaveLength(2);
  } finally {
    await removeDashboard(page, id);
  }
});

test('carrying on editing after a conflict writes nothing and keeps the edits', async ({
  page,
}) => {
  const dashboard = new DashboardV2Page(page);
  let id: number | undefined;
  try {
    id = await createSavedDashboard(dashboard, uniqueName('conflict-keep'));
    await saveFromElsewhere(page, id);
    const theirs = await readDashboard(page, id);

    await dashboard.showPalette();
    await dashboard.palette('markdown').click();
    await dashboard.saveButton.click();
    await expect(dashboard.conflictDialog).toBeVisible();

    await dashboard.conflictKeepEditing.click();

    await expect(dashboard.conflictDialog).toHaveCount(0);
    await expect(dashboard.unsavedIndicator).toBeVisible();
    await expect(dashboard.gridItems()).toHaveCount(2);
    expect((await readDashboard(page, id)).revision).toBe(theirs.revision);

    // Nothing was resolved, so saving again is refused again.
    await dashboard.saveButton.click();
    await expect(dashboard.conflictDialog).toBeVisible();
    expect((await readDashboard(page, id)).revision).toBe(theirs.revision);
  } finally {
    await removeDashboard(page, id);
  }
});

test('a dashboard that does not exist says so and offers nothing to save', async ({
  page,
}) => {
  await skipUnlessFeatureEnabled(page, 'DASHBOARD_V2');

  await gotoWithRetry(page, 'dashboard/v2/2147483000/');

  await expect(page.getByTestId('dashboard-load-error')).toBeVisible();
  await expect(page.getByTestId('canvas')).toHaveCount(0);
  await expect(page.getByTestId('header-save')).toBeDisabled();
});

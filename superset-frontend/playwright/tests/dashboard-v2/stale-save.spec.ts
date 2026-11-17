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
 * Dashboard v2 — two editors, one dashboard.
 *
 * Two browser contexts open the same saved dashboard, each with its own
 * builder, its own in-memory tree and its own idea of which revision that
 * tree is based on. The first to save wins; the second is told so, and what
 * it sees after choosing to reload is the first one's work.
 *
 * Unlike the conflict tests in `save-and-reload.spec.ts`, the "other editor"
 * here is a second real builder rather than an API call, so both halves of
 * the agreement (what a save sends, what a refusal shows) are the product's.
 *
 * Needs a server with the DASHBOARD_V2 feature flag on (the test skips
 * itself where it is off) and a user who may write dashboards. It signs in
 * with a username and a password, the ones the global setup uses:
 *
 *   PLAYWRIGHT_BASE_URL=http://localhost:8088 \
 *   PLAYWRIGHT_ADMIN_USERNAME=admin PLAYWRIGHT_ADMIN_PASSWORD=general \
 *   npx playwright test --project=chromium \
 *     playwright/tests/dashboard-v2/stale-save.spec.ts
 *
 * No dataset is needed: the widgets placed are markdown.
 */
import {
  Browser,
  BrowserContext,
  Page,
  TestInfo,
  expect,
  test,
} from '@playwright/test';
import { AuthPage } from '../../pages/AuthPage';
import { DashboardV2Page } from '../../pages/DashboardV2Page';
import { apiDeleteDashboard } from '../../helpers/api/dashboard';
import { apiGet } from '../../helpers/api/requests';
import { TIMEOUT } from '../../utils/constants';

const API = 'api/v1/dashboard_v2/';

interface StoredDashboard {
  id: number;
  revision: number;
  dashboard_title: string;
  document: { nodes: Record<string, { children?: string[] }> };
}

const uniqueName = (label: string): string =>
  `pw-dashboard-v2-${label}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

async function readDashboard(page: Page, id: number): Promise<StoredDashboard> {
  const response = await apiGet(page, `${API}${id}`);
  return (await response.json()).result as StoredDashboard;
}

/**
 * A browser context of its own for one editor: separate cookies, separate
 * page, separate JavaScript heap, so nothing the two builders hold is shared
 * but the server.
 *
 * It starts from the session the global setup signed in with. Where a
 * project carries no saved session, it signs in here with the same username
 * and password instead, so the spec does not depend on which project runs it.
 */
async function openEditorContext(
  browser: Browser,
  testInfo: TestInfo,
): Promise<{ context: BrowserContext; page: Page }> {
  const { baseURL, storageState, viewport } = testInfo.project.use;
  const context = await browser.newContext({
    baseURL,
    storageState,
    viewport: viewport ?? undefined,
  });
  const page = await context.newPage();
  if (storageState === undefined) {
    const auth = new AuthPage(page);
    await auth.goto();
    await auth.waitForLoginForm();
    await auth.loginWithCredentials(
      process.env.PLAYWRIGHT_ADMIN_USERNAME || 'admin',
      process.env.PLAYWRIGHT_ADMIN_PASSWORD || 'general',
    );
    await auth.waitForLoginSuccess({ timeout: TIMEOUT.GLOBAL_SETUP });
  }
  return { context, page };
}

test('the second of two editors to save is refused, and reloading shows the first one’s change', async ({
  browser,
}, testInfo) => {
  // Two full builders are loaded and each saves; allow for both.
  test.slow();

  const a = await openEditorContext(browser, testInfo);
  const b = await openEditorContext(browser, testInfo);
  const editorA = new DashboardV2Page(a.page);
  const editorB = new DashboardV2Page(b.page);
  const name = uniqueName('two-editors');
  const renamedByA = `${name} (edited by A)`;
  let id: number | undefined;

  try {
    // A creates the dashboard with one widget. `goto` is also what stands
    // the test down where the feature flag is off.
    await editorA.goto();
    await editorA.rename(name);
    await editorA.placeBlockByClick('markdown');
    id = await editorA.saveNew();
    const base = await readDashboard(a.page, id);

    // Both editors hold the same copy: one widget, the base revision.
    await editorA.gotoSaved(id);
    await editorB.gotoSaved(id);
    await expect(editorA.gridItems()).toHaveCount(1);
    await expect(editorB.gridItems()).toHaveCount(1);

    // A adds two widgets and renames the dashboard, then saves. Nobody has
    // written since A loaded, so the save is accepted.
    await editorA.showPalette();
    await editorA.palette('markdown').click();
    await editorA.palette('markdown').click();
    await expect(editorA.gridItems()).toHaveCount(3);
    await editorA.rename(renamedByA);
    await editorA.saveButton.click();
    await expect(editorA.unsavedIndicator).toHaveCount(0);
    await expect(editorA.conflictDialog).toHaveCount(0);
    const afterA = await readDashboard(a.page, id);
    expect(afterA.revision).toBe(base.revision + 1);
    expect(afterA.document.nodes.root.children).toHaveLength(3);

    // B, still on the copy from before A's save, adds one widget and saves.
    await editorB.showPalette();
    await editorB.palette('markdown').click();
    await expect(editorB.gridItems()).toHaveCount(2);
    await editorB.saveButton.click();

    // Refused, and said so. The server still holds exactly A's copy.
    await expect(editorB.conflictDialog).toBeVisible();
    const afterRefusal = await readDashboard(b.page, id);
    expect(afterRefusal.revision).toBe(afterA.revision);
    expect(afterRefusal.document.nodes.root.children).toHaveLength(3);

    // B gives up its own copy for the one on the server.
    await editorB.conflictReload.click();

    await expect(editorB.conflictDialog).toHaveCount(0);
    await expect(editorB.unsavedIndicator).toHaveCount(0);
    // A's three widgets and A's name, not B's two.
    await expect(editorB.gridItems()).toHaveCount(3);
    await expect(editorB.title).toHaveValue(renamedByA);

    // And B is on A's revision: a save made from here is accepted.
    await editorB.showPalette();
    await editorB.palette('markdown').click();
    await expect(editorB.gridItems()).toHaveCount(4);
    await editorB.saveButton.click();
    await expect(editorB.unsavedIndicator).toHaveCount(0);
    await expect(editorB.conflictDialog).toHaveCount(0);
    const afterB = await readDashboard(b.page, id);
    expect(afterB.revision).toBe(afterA.revision + 1);
    expect(afterB.document.nodes.root.children).toHaveLength(4);
  } finally {
    if (id !== undefined) {
      await apiDeleteDashboard(a.page, id, { failOnStatusCode: false });
    }
    await a.context.close();
    await b.context.close();
  }
});

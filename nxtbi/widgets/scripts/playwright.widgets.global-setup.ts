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
 * Signs in once before the upstream specs run against the Widget Framework
 * stack, and stores the session where the upstream projects read it
 * (`superset-frontend/playwright/.auth/user.json`).
 *
 * It does what `superset-frontend/playwright/global-setup.ts` does, with one
 * difference: the session cookie is looked up under the name the stack gives
 * it (`PLAYWRIGHT_SESSION_COOKIE_NAME`, set by the runner script from the
 * stack's configuration) instead of `session`.
 *
 * Nothing is imported from `superset-frontend/playwright`: this file is loaded
 * as a module of another package than the specs are, and a page object loaded
 * here would be loaded a second time, in the other module format, for them.
 */
import { mkdir } from 'fs/promises';
import { createRequire } from 'module';
import { dirname, resolve } from 'path';
import type { FullConfig } from '@playwright/test';

const frontend = resolve(__dirname, '../../../superset-frontend');
// Playwright is installed for the frontend only; resolve it from there.
const { chromium } = createRequire(resolve(frontend, 'package.json'))(
  '@playwright/test',
) as typeof import('@playwright/test');

const sessionCookieName =
  process.env.PLAYWRIGHT_SESSION_COOKIE_NAME || 'session';
const LOGIN_TIMEOUT_MS = 60_000;

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use?.baseURL;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ baseURL });
    const page = await context.newPage();
    // The same form, by the same `data-test` hooks, as the upstream `AuthPage`.
    await page.goto('login/', { waitUntil: 'domcontentloaded' });
    const form = page.locator('[data-test="login-form"]');
    await form.waitFor({ state: 'visible', timeout: LOGIN_TIMEOUT_MS });
    await form
      .locator('[data-test="username-input"]')
      .fill(process.env.PLAYWRIGHT_ADMIN_USERNAME || 'admin');
    await form
      .locator('[data-test="password-input"]')
      .fill(process.env.PLAYWRIGHT_ADMIN_PASSWORD || 'general');
    await form.locator('[data-test="login-button"]').click();

    const deadline = Date.now() + LOGIN_TIMEOUT_MS;
    const signedIn = async (): Promise<boolean> =>
      (await context.cookies()).some(
        cookie => cookie.name === sessionCookieName && cookie.value !== '',
      ) && !new URL(page.url()).pathname.startsWith('/login');
    while (!(await signedIn())) {
      if (Date.now() > deadline) {
        throw new Error(
          `sign-in did not finish within ${LOGIN_TIMEOUT_MS}ms: no cookie ` +
            `"${sessionCookieName}" away from the login page (at ${page.url()})`,
        );
      }
      await page.waitForTimeout(250);
    }

    const authState = resolve(frontend, 'playwright/.auth/user.json');
    await mkdir(dirname(authState), { recursive: true });
    await context.storageState({ path: authState });
    console.log(
      `[Global Setup] signed in; session cookie "${sessionCookieName}" stored`,
    );
  } finally {
    await browser.close();
  }
}

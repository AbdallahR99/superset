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
 * The upstream Playwright configuration, pointed at the Widget Framework
 * stack. Used by `run_upstream_playwright.sh`; the specs and page objects are
 * the upstream ones, unchanged.
 *
 * One thing differs: the sign-in that runs before the specs. The upstream
 * global setup decides that a login succeeded by looking for a cookie named
 * `session`, and this stack names its session cookie differently
 * (`SESSION_COOKIE_NAME` in `nxtbi/widgets/config/superset_config.py`), so it
 * would wait for a cookie that never comes. `playwright.widgets.global-setup.ts`
 * signs in the same way and looks for the cookie under the stack's name.
 *
 * Every path is absolute: Playwright resolves relative ones against the
 * directory of the configuration file, which is not `superset-frontend` here.
 */
import { resolve } from 'path';
import upstream from '../../../superset-frontend/playwright.config';

const frontend = resolve(__dirname, '../../../superset-frontend');
const authState = resolve(frontend, 'playwright/.auth/user.json');

export default {
  ...upstream,
  testDir: resolve(frontend, 'playwright/tests'),
  outputDir: resolve(frontend, 'test-results'),
  globalSetup: resolve(__dirname, 'playwright.widgets.global-setup.ts'),
  // The stack is started by docker compose; the runner script checks /health.
  webServer: undefined,
  projects: (upstream.projects ?? []).map(project => ({
    ...project,
    use: {
      ...project.use,
      ...(project.use?.storageState ? { storageState: authState } : {}),
    },
  })),
};

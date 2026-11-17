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
import { matchPath } from 'react-router-dom';
import { FeatureFlag } from '@superset-ui/core';

jest.mock('src/pages/Home', () => () => <div data-test="mock-home" />);

const V2_NEW = '/dashboard/v2/new/';
const V2_SAVED = '/dashboard/v2/:dashboardId/';
const CLASSIC = '/dashboard/:idOrSlug/';

/**
 * The route table as it is built with the given flags on. The table is built
 * once, when the module is first evaluated, so each case evaluates a fresh
 * copy of it against its own flags.
 */
const loadRoutes = async (...enabled: FeatureFlag[]) => {
  jest.resetModules();
  jest.doMock('@superset-ui/core', () => ({
    ...jest.requireActual('@superset-ui/core'),
    isFeatureEnabled: (flag: FeatureFlag) => enabled.includes(flag),
  }));
  return import('./routes');
};

/** The path of the first route a `Switch` would render for `pathname`. */
const firstMatch = (
  routes: { path: string }[],
  pathname: string,
): string | undefined =>
  routes.find(route => matchPath(pathname, { path: route.path }))?.path;

afterEach(() => {
  jest.dontMock('@superset-ui/core');
  jest.resetModules();
});

test('with the flag off the Dashboard v2 routes are not registered', async () => {
  const { routes, isFrontendRoute } = await loadRoutes();
  const paths = routes.map(route => route.path);

  expect(paths).not.toContain(V2_NEW);
  expect(paths).not.toContain(V2_SAVED);
  expect(isFrontendRoute(V2_NEW)).toBe(false);
});

test('with the flag off a Dashboard v2 URL is handled like any other dashboard path', async () => {
  const { routes } = await loadRoutes();

  // Nothing of the builder is reached: the URL falls to the classic
  // dashboard route, which reports a dashboard it cannot find.
  expect(firstMatch(routes, V2_NEW)).toBe(CLASSIC);
  expect(firstMatch(routes, '/dashboard/v2/5/')).toBe(CLASSIC);
});

test('with the flag on both Dashboard v2 routes are registered ahead of the classic dashboard route', async () => {
  const { routes, isFrontendRoute } = await loadRoutes(FeatureFlag.DashboardV2);
  const paths = routes.map(route => route.path);

  expect(paths).toContain(V2_NEW);
  expect(paths).toContain(V2_SAVED);
  expect(paths.indexOf(V2_NEW)).toBeLessThan(paths.indexOf(V2_SAVED));
  expect(paths.indexOf(V2_SAVED)).toBeLessThan(paths.indexOf(CLASSIC));
  expect(isFrontendRoute(V2_NEW)).toBe(true);
  expect(firstMatch(routes, V2_NEW)).toBe(V2_NEW);
  expect(firstMatch(routes, '/dashboard/v2/5/')).toBe(V2_SAVED);
  // The classic route is still the one a classic dashboard reaches.
  expect(firstMatch(routes, '/dashboard/5/')).toBe(CLASSIC);
});

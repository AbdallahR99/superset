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
import type { navigation } from '@apache-superset/core';

const EXTENSION_PATH = '/api/v1/extensions/nxtbi/ai-copilot/';
const APPROVED_DASHBOARD_PATH = /^\/dashboard\/v2\/[1-9]\d*\/$/;

type Page = navigation.Page;

interface ActiveEntity {
  dashboardId?: number;
  databaseId?: number;
}

interface PageContext {
  page: Page;
  dashboardId?: number;
  datasetId?: number;
  chartId?: number;
  databaseId?: number;
}

function positiveId(
  value: string | number | null | undefined,
): number | undefined {
  if (
    value === null ||
    value === undefined ||
    !/^[1-9]\d*$/.test(String(value))
  ) {
    return undefined;
  }
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : undefined;
}

export function deploymentBase(origin: string, assetDirectory: string): string {
  const assetBase = new URL(assetDirectory, origin);
  if (
    assetBase.origin === origin &&
    assetBase.pathname.endsWith(EXTENSION_PATH)
  ) {
    return `${origin}${assetBase.pathname.slice(0, -EXTENSION_PATH.length)}`;
  }
  return origin;
}

export function readPageContext(
  base: string,
  page: Page,
  location: URL,
  active: ActiveEntity = {},
): PageContext {
  const app = new URL(base);
  const prefix = app.pathname.replace(/\/$/, '');
  const context: PageContext = { page };
  if (
    location.origin !== app.origin ||
    !location.pathname.startsWith(`${prefix}/`)
  ) {
    return context;
  }
  const path = location.pathname.slice(prefix.length);

  if (page === 'dashboard' && /^\/dashboard\/[^/]+\/?$/.test(path)) {
    const slug = /^\/dashboard\/([^/]+)\/?$/.exec(path)?.[1];
    const dashboardId = positiveId(slug) ?? positiveId(active.dashboardId);
    if (dashboardId !== undefined) context.dashboardId = dashboardId;
  } else if (page === 'dashboard_v2') {
    const id = positiveId(/^\/dashboard\/v2\/(\d+)\/?$/.exec(path)?.[1]);
    if (id !== undefined) context.dashboardId = id;
  } else if (page === 'dataset') {
    const id = positiveId(/^\/dataset\/(\d+)\/?$/.exec(path)?.[1]);
    if (id !== undefined) context.datasetId = id;
  } else if (page === 'explore' && /^\/explore\/?$/.test(path)) {
    const chartId = positiveId(location.searchParams.get('slice_id'));
    const datasetId = positiveId(location.searchParams.get('datasource_id'));
    if (chartId !== undefined) context.chartId = chartId;
    if (
      datasetId !== undefined &&
      location.searchParams.get('datasource_type') === 'table'
    ) {
      context.datasetId = datasetId;
    }
  } else if (page === 'sqllab' && /^\/sqllab\/?$/.test(path)) {
    const databaseId = positiveId(active.databaseId);
    if (databaseId !== undefined) context.databaseId = databaseId;
  }
  return context;
}

export function resolveDashboardLink(
  base: string,
  url: string,
): string | undefined {
  if (!url.startsWith('/') || url.startsWith('//')) return undefined;
  const app = new URL(base);
  const dashboard = new URL(url, app);
  if (dashboard.origin !== app.origin || dashboard.search || dashboard.hash) {
    return undefined;
  }
  const prefix = app.pathname.replace(/\/$/, '');
  const suffix =
    prefix && dashboard.pathname.startsWith(`${prefix}/`)
      ? dashboard.pathname.slice(prefix.length)
      : dashboard.pathname;
  return APPROVED_DASHBOARD_PATH.test(suffix)
    ? `${app.origin}${prefix}${suffix}`
    : undefined;
}

export function dashboardActionLink(
  base: string,
  context: Record<string, unknown>,
  version: 'v2' | 'classic' = 'v2',
): string | undefined {
  const { dashboardId } = context;
  if (
    typeof dashboardId !== 'number' ||
    positiveId(dashboardId) === undefined
  ) {
    return undefined;
  }
  const path =
    version === 'v2'
      ? `/dashboard/v2/${dashboardId}/`
      : `/dashboard/${dashboardId}/`;
  return `${base}${path}`;
}

export async function dashboardDestination(
  base: string,
  context: Record<string, unknown>,
): Promise<string | undefined> {
  const v2 = dashboardActionLink(base, context);
  if (!v2) return undefined;
  try {
    const response = await fetch(
      `${base}/api/v1/dashboard_v2/${context.dashboardId}`,
      {
        credentials: 'same-origin',
        redirect: 'error',
        headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (response.status === 200) return v2;
    if (response.status === 404)
      return dashboardActionLink(base, context, 'classic');
  } catch {
    return undefined;
  }
  return undefined;
}

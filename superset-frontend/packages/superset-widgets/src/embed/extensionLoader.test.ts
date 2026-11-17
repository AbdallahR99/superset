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
import { getWidgetComponent } from '../registry';
import { createExtensionHost, getPageCore } from './extensionHost';
import {
  createExtensionWidgetLoader,
  isExtensionWidgetType,
  parseExtensionWidgetType,
} from './extensionLoader';

const TYPE = 'extensions.acme.widgets.chart';
const TABLE_TYPE = 'extensions.acme.widgets.table';
const CONTAINER = 'acme_widgets';
const DOMAIN = 'https://superset.example.com';
const OTHER_DOMAIN = 'https://other.example.com';

type ExtensionCore = {
  views: {
    registerView: (
      view: { id: string; name: string },
      location: string,
      component: () => null,
    ) => { dispose(): void };
  };
  extensions: { getContext(): { extension: { id: string } } };
};

type ShareEntry = { get: () => Promise<() => ExtensionCore> };
type ShareScope = Record<string, Record<string, ShareEntry>>;

const StubWidget = () => null;
const globals = window as unknown as Record<string, unknown>;

/**
 * Stands in for the extension's `./index`: what it does when evaluated, with
 * the `@apache-superset/core` it imported, and what it exports.
 */
let entryModule: (imported: ExtensionCore) => unknown;
let scriptUrls: string[];
/** One entry per evaluation of the bundle. */
let evaluations: {
  imported?: ExtensionCore;
  init: jest.Mock;
  started: number;
  globalDuringStart?: unknown;
}[];
/** The page keeps a bundle by URL, so every test serves its own. */
let bundleSerial = 0;
let extension: {
  id: string;
  publisher: string;
  name: string;
  remoteEntry: string;
  moduleFederationName: string;
};

const registerChart = (core: ExtensionCore) =>
  core.views.registerView(
    { id: TYPE, name: 'Chart' },
    'dashboard.widgets',
    StubWidget,
  );

/**
 * What evaluating the remote entry does: it assigns a container, with
 * nothing started yet, to the extension's global.
 */
function evaluateBundle() {
  const evaluation: (typeof evaluations)[number] = {
    init: jest.fn(),
    started: 0,
  };
  evaluation.init.mockImplementation(async (scope: ShareScope) => {
    const [entry] = Object.values(scope['@apache-superset/core']);
    evaluation.imported = (await entry.get())();
  });
  evaluations.push(evaluation);
  globals[CONTAINER] = {
    init: evaluation.init,
    get: async () => () => {
      evaluation.started += 1;
      evaluation.globalDuringStart = globals.superset;
      return entryModule(evaluation.imported as ExtensionCore);
    },
  };
}

const respond = (result: unknown) =>
  ({ ok: true, json: async () => ({ result }) }) as unknown as Response;

beforeEach(() => {
  scriptUrls = [];
  evaluations = [];
  bundleSerial += 1;
  extension = {
    id: 'acme.widgets',
    publisher: 'acme',
    name: 'widgets',
    remoteEntry: `/api/v1/extensions/acme/widgets/remoteEntry.${bundleSerial}.js`,
    moduleFederationName: CONTAINER,
  };
  entryModule = registerChart;
  delete globals[CONTAINER];
  delete globals.superset;
  global.fetch = jest.fn(async () => respond(extension)) as typeof fetch;
  jest.spyOn(document.head, 'appendChild').mockImplementation(((
    node: HTMLScriptElement,
  ) => {
    scriptUrls.push(node.src);
    evaluateBundle();
    node.onload?.(new Event('load'));
    return node;
  }) as typeof document.head.appendChild);
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('an extension widget type names the extension that draws it', () => {
  expect(parseExtensionWidgetType(TYPE)).toEqual({
    publisher: 'acme',
    name: 'widgets',
    id: 'acme.widgets',
  });
  expect(parseExtensionWidgetType('echarts')).toBeUndefined();
  expect(parseExtensionWidgetType('extensions.acme.widgets')).toBeUndefined();
  expect(isExtensionWidgetType(TYPE)).toBe(true);
  expect(isExtensionWidgetType('markdown')).toBe(false);
});

test('loading a type fetches its extension and returns the widget it registers', async () => {
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  const component = await load(TYPE);

  expect(global.fetch).toHaveBeenCalledWith(
    `${DOMAIN}/api/v1/extensions/acme/widgets`,
    expect.anything(),
  );
  expect(scriptUrls).toEqual([`${DOMAIN}${extension.remoteEntry}`]);
  expect(component).toBeDefined();
  // It lives with the loader, not in the registry every provider reads.
  expect(getWidgetComponent(TYPE)).toBeUndefined();
});

test('a second widget from the same extension reuses the one load', async () => {
  entryModule = imported => {
    registerChart(imported);
    imported.views.registerView(
      { id: TABLE_TYPE, name: 'Table' },
      'dashboard.widgets',
      StubWidget,
    );
  };
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await Promise.all([load(TYPE), load(TABLE_TYPE)]);

  expect(evaluations).toHaveLength(1);
  expect(evaluations[0].init).toHaveBeenCalledTimes(1);
  expect(scriptUrls).toHaveLength(1);
});

test('a type the extension does not contribute says so', async () => {
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await expect(load('extensions.acme.widgets.missing')).rejects.toThrow(
    'Extension acme.widgets does not contribute the widget',
  );
});

test('a failed load is not kept, so the next widget can retry', async () => {
  (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('offline'));
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await expect(load(TYPE)).rejects.toThrow('offline');
  await expect(load(TYPE)).resolves.toBeDefined();
});

test('a bundle that registers no container is reported by name, and fetched again next time', async () => {
  (document.head.appendChild as jest.Mock).mockImplementationOnce(
    (node: HTMLScriptElement) => {
      scriptUrls.push(node.src);
      node.onload?.(new Event('load'));
      return node;
    },
  );
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await expect(load(TYPE)).rejects.toThrow(
    'Extension acme.widgets did not register the container "acme_widgets".',
  );
  await expect(load(TYPE)).resolves.toBeDefined();
  expect(scriptUrls).toHaveLength(2);
});

test('two providers load the bundle once and each start it with a core of their own', async () => {
  const requests: { url: string; token?: string }[] = [];
  global.fetch = jest.fn(async (url: string, init: RequestInit) => {
    requests.push({
      url,
      token: (init.headers as Record<string, string>)['X-GuestToken'],
    });
    return respond(extension);
  }) as unknown as typeof fetch;
  // The extension takes its core as an argument: nothing read from a global.
  const activatedWith: ExtensionCore[] = [];
  entryModule = () => ({
    activate(core: ExtensionCore) {
      activatedWith.push(core);
      registerChart(core);
    },
  });
  const leftHost = createExtensionHost();
  const rightHost = createExtensionHost();
  const loadLeft = createExtensionWidgetLoader({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'left-token',
    host: leftHost,
  });
  const loadRight = createExtensionWidgetLoader({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'right-token',
    host: rightHost,
  });

  // Started together, so their turns on the page's globals interleave if
  // anything lets them.
  const [left, right] = await Promise.all([loadLeft(TYPE), loadRight(TYPE)]);

  // Each asked Superset for the extension with its own token.
  expect(requests).toEqual(
    expect.arrayContaining([
      { url: `${DOMAIN}/api/v1/extensions/acme/widgets`, token: 'left-token' },
      { url: `${DOMAIN}/api/v1/extensions/acme/widgets`, token: 'right-token' },
    ]),
  );
  expect(requests).toHaveLength(2);

  // One script, one container, one evaluation of the entry module.
  expect(scriptUrls).toEqual([`${DOMAIN}${extension.remoteEntry}`]);
  expect(evaluations).toHaveLength(1);
  expect(evaluations[0].init).toHaveBeenCalledTimes(1);
  expect(evaluations[0].started).toBe(1);

  // Started once per provider, each with that provider's own core, and what
  // it registered went to that provider's host alone.
  expect(activatedWith).toHaveLength(2);
  expect(activatedWith[0]).not.toBe(activatedWith[1]);
  expect(activatedWith[0].views).not.toBe(activatedWith[1].views);
  expect(activatedWith).toEqual(
    expect.arrayContaining([
      leftHost.createCore(extension),
      rightHost.createCore(extension),
    ]),
  );
  expect(left).not.toBe(right);
  expect(leftHost.getComponent(TYPE)).toBe(left);
  expect(rightHost.getComponent(TYPE)).toBe(right);

  // A third widget under a provider that already started it does not start
  // it again.
  await loadLeft(TYPE);
  expect(activatedWith).toHaveLength(2);
});

test('an extension that registers when imported is recorded once and replayed per provider', async () => {
  const leftHost = createExtensionHost();
  const rightHost = createExtensionHost();
  const loadLeft = createExtensionWidgetLoader({
    supersetDomain: DOMAIN,
    host: leftHost,
  });
  const loadRight = createExtensionWidgetLoader({
    supersetDomain: DOMAIN,
    host: rightHost,
  });

  const left = await loadLeft(TYPE);
  const right = await loadRight(TYPE);

  expect(evaluations).toHaveLength(1);
  expect(evaluations[0].started).toBe(1);
  // What it imported is the page core, the same object for every provider.
  expect(evaluations[0].imported).toBe(getPageCore());
  expect(left).not.toBe(right);
  expect(leftHost.getComponent(TYPE)).toBe(left);
  expect(rightHost.getComponent(TYPE)).toBe(right);
});

test('the same extension served by two deployments is two bundles', async () => {
  const loadLeft = createExtensionWidgetLoader({ supersetDomain: DOMAIN });
  const loadRight = createExtensionWidgetLoader({
    supersetDomain: OTHER_DOMAIN,
  });

  await Promise.all([loadLeft(TYPE), loadRight(TYPE)]);

  expect(scriptUrls.sort()).toEqual(
    [
      `${DOMAIN}${extension.remoteEntry}`,
      `${OTHER_DOMAIN}${extension.remoteEntry}`,
    ].sort(),
  );
  expect(evaluations).toHaveLength(2);
  evaluations.forEach(evaluation => expect(evaluation.started).toBe(1));
});

test('the `superset` global is the page core, and stays for a build that reads it late', async () => {
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await load(TYPE);

  expect(evaluations[0].globalDuringStart).toBe(getPageCore());
  expect(globals.superset).toBe(getPageCore());
  // It is the same object whoever asks and whenever.
  await createExtensionWidgetLoader({ supersetDomain: OTHER_DOMAIN })(TYPE);
  expect(globals.superset).toBe(getPageCore());
});

test('a `superset` global the page already had is put back', async () => {
  const pageGlobal = { mine: true };
  globals.superset = pageGlobal;
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await load(TYPE);

  expect(evaluations[0].globalDuringStart).toBe(getPageCore());
  expect(globals.superset).toBe(pageGlobal);
});

test('an extension whose start fails can be started again', async () => {
  let attempts = 0;
  entryModule = () => ({
    activate(core: ExtensionCore) {
      attempts += 1;
      if (attempts === 1) throw new Error('not yet');
      registerChart(core);
    },
  });
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await expect(load(TYPE)).rejects.toThrow('not yet');
  await expect(load(TYPE)).resolves.toBeDefined();
  // The bundle itself was not fetched or evaluated a second time.
  expect(scriptUrls).toHaveLength(1);
  expect(evaluations[0].started).toBe(1);
});

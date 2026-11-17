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
import { createExtensionHost } from './extensionHost';
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

/** Stands in for the extension's `./index`: what it registers when evaluated. */
let register: (core: ExtensionCore) => void;
let scriptUrls: string[];
/** One entry per evaluation of the bundle: the core that copy was started with. */
let evaluations: {
  core?: ExtensionCore;
  init: jest.Mock;
  globalDuringStart?: unknown;
}[];

const extension = {
  id: 'acme.widgets',
  publisher: 'acme',
  name: 'widgets',
  remoteEntry: '/api/v1/extensions/acme/widgets/remoteEntry.abc.js',
  moduleFederationName: CONTAINER,
};

const registerChart = (loaded: ExtensionCore) =>
  loaded.views.registerView(
    { id: TYPE, name: 'Chart' },
    'dashboard.widgets',
    StubWidget,
  );

/**
 * What evaluating the remote entry does: it assigns a brand new container,
 * with nothing started yet, to the extension's global.
 */
function evaluateBundle() {
  const evaluation: (typeof evaluations)[number] = { init: jest.fn() };
  evaluation.init.mockImplementation(async (scope: ShareScope) => {
    const [entry] = Object.values(scope['@apache-superset/core']);
    evaluation.core = (await entry.get())();
  });
  evaluations.push(evaluation);
  globals[CONTAINER] = {
    init: evaluation.init,
    get: async () => () => {
      evaluation.globalDuringStart = globals.superset;
      register(evaluation.core as ExtensionCore);
    },
  };
}

const respond = (result: unknown) =>
  ({ ok: true, json: async () => ({ result }) }) as unknown as Response;

beforeEach(() => {
  scriptUrls = [];
  evaluations = [];
  register = registerChart;
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
  register = loaded => {
    registerChart(loaded);
    loaded.views.registerView(
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

test('a bundle that registers no container is reported by name', async () => {
  (document.head.appendChild as jest.Mock).mockImplementation(
    (node: HTMLScriptElement) => {
      node.onload?.(new Event('load'));
      return node;
    },
  );
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await expect(load(TYPE)).rejects.toThrow(
    'Extension acme.widgets did not register the container "acme_widgets".',
  );
});

test('two loaders each evaluate the extension for themselves, with their own core and credentials', async () => {
  const requests: { url: string; token?: string }[] = [];
  global.fetch = jest.fn(async (url: string, init: RequestInit) => {
    requests.push({
      url,
      token: (init.headers as Record<string, string>)['X-GuestToken'],
    });
    return respond(extension);
  }) as unknown as typeof fetch;
  const leftHost = createExtensionHost();
  const rightHost = createExtensionHost();
  const loadLeft = createExtensionWidgetLoader({
    supersetDomain: DOMAIN,
    getGuestToken: async () => 'left-token',
    host: leftHost,
  });
  const loadRight = createExtensionWidgetLoader({
    supersetDomain: OTHER_DOMAIN,
    getGuestToken: async () => 'right-token',
    host: rightHost,
  });

  // Started together, so their turns on the page's globals interleave if
  // anything lets them.
  const [left, right] = await Promise.all([loadLeft(TYPE), loadRight(TYPE)]);

  // Each fetched its own deployment with its own token, once.
  expect(requests).toEqual(
    expect.arrayContaining([
      { url: `${DOMAIN}/api/v1/extensions/acme/widgets`, token: 'left-token' },
      {
        url: `${OTHER_DOMAIN}/api/v1/extensions/acme/widgets`,
        token: 'right-token',
      },
    ]),
  );
  expect(requests).toHaveLength(2);
  expect(scriptUrls.sort()).toEqual(
    [
      `${DOMAIN}${extension.remoteEntry}`,
      `${OTHER_DOMAIN}${extension.remoteEntry}`,
    ].sort(),
  );

  // Two copies of the extension, each started exactly once with a different
  // core, and each registered with its own host.
  expect(evaluations).toHaveLength(2);
  evaluations.forEach(evaluation =>
    expect(evaluation.init).toHaveBeenCalledTimes(1),
  );
  expect(evaluations[0].core).not.toBe(evaluations[1].core);
  expect(evaluations[0].core?.views).not.toBe(evaluations[1].core?.views);
  expect(left).not.toBe(right);
  expect(leftHost.getComponent(TYPE)).toBe(left);
  expect(rightHost.getComponent(TYPE)).toBe(right);

  // The `superset` global was each copy's own core while it started, and is
  // nobody's afterwards.
  expect(evaluations[0].globalDuringStart).toBe(evaluations[0].core);
  expect(evaluations[1].globalDuringStart).toBe(evaluations[1].core);
  expect('superset' in globals).toBe(false);
});

test('a `superset` global the page already had is put back', async () => {
  const pageGlobal = { mine: true };
  globals.superset = pageGlobal;
  const load = createExtensionWidgetLoader({ supersetDomain: DOMAIN });

  await load(TYPE);

  expect(evaluations[0].globalDuringStart).toBe(evaluations[0].core);
  expect(globals.superset).toBe(pageGlobal);
});

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
 * Loads the widget types a Superset extension contributes, on demand, into a
 * host page.
 *
 * A widget type registered by an extension is namespaced by the host as
 * `extensions.<publisher>.<name>.<type>` (see `inject_widget_implementations`),
 * so the type on a node — or on a saved widget — is all the host needs to find
 * the extension that draws it. Its frontend is a Module Federation container
 * served by Superset; this loads that container and hands it a
 * `@apache-superset/core` backed by the embedded widget runtime.
 */
import * as React from 'react';
import * as ReactDOM from 'react-dom';
import { createContext, useContext, useEffect, useState } from 'react';
import { toError, useWidgetErrorReporter } from '../errors';
import type { WidgetComponent } from '../types';
import { createApiFetch, type ApiFetchOptions } from './httpClient';
import {
  createExtensionHost,
  evaluateExtension,
  getPageCore,
  isExtensionWidgetType,
  parseExtensionWidgetType,
  type ExtensionBundle,
  type ExtensionHost,
  type ExtensionInfo,
} from './extensionHost';

export { isExtensionWidgetType, parseExtensionWidgetType };

/** Resolves the component for an extension's widget type, loading it if needed. */
export type ExtensionWidgetLoader = (type: string) => Promise<WidgetComponent>;

export interface ExtensionWidgetLoaderOptions extends ApiFetchOptions {
  /**
   * Modules added to the container's share scope, beyond the `react`,
   * `react-dom`, `antd` and `@apache-superset/core` every extension declares.
   * A bundle is started once per page, so for a bundle two providers both
   * load, the `shared` of whichever loads it first is the one it sees.
   */
  shared?: Record<string, unknown>;
  /**
   * Where the loaded extensions register their widgets. Defaults to a host
   * of the loader's own, which is what keeps one provider's extension widgets
   * apart from another's.
   */
  host?: ExtensionHost;
}

/** The runtime half of a Module Federation container, as `window[name]` holds it. */
interface FederationContainer {
  init(shareScope: Record<string, unknown>): void | Promise<void>;
  get(module: string): Promise<() => unknown>;
}

function isFederationContainer(value: unknown): value is FederationContainer {
  const container = value as Partial<FederationContainer> | null;
  return (
    typeof container?.init === 'function' &&
    typeof container?.get === 'function'
  );
}

function shareEntry(module: unknown, version: string) {
  return {
    [version]: {
      get: () => Promise.resolve(() => module),
      loaded: true,
      eager: true,
      from: '@apache-superset/widgets',
    },
  };
}

const versionOf = (module: unknown): string =>
  (module as { version?: string }).version ?? '0.0.0';

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.type = 'text/javascript';
    script.async = true;
    script.onload = () => {
      script.remove();
      resolve();
    };
    script.onerror = () => {
      script.remove();
      reject(new Error(`Could not load the extension bundle at ${src}.`));
    };
    document.head.appendChild(script);
  });
}

/**
 * Loads take turns on the page's globals. A Module Federation container
 * announces itself by assigning a global named after the extension, which
 * only means something between its script finishing and the container being
 * picked up; two bundles that use the same name must not overlap there. The
 * queue orders loads and holds nothing.
 */
let containerTurn: Promise<void> = Promise.resolve();

function takeContainerTurn<T>(run: () => Promise<T>): Promise<T> {
  const result = containerTurn.then(run);
  containerTurn = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

/** Bundles the page has evaluated or is evaluating, by script URL. */
const bundles = new Map<string, Promise<ExtensionBundle>>();

/**
 * Fetches and evaluates the bundle at `src`, once per page.
 *
 * Evaluating a remote entry a second time cannot be relied on to give a
 * second, independent copy of the extension: the runtime of a Module
 * Federation bundle keeps its chunk registry in a page global and may hand a
 * later evaluation the modules of the first. So there is one evaluation, and
 * what differs per provider is the core each provider's host starts the
 * bundle with (see `ExtensionHost.activate`).
 *
 * The bundle's `@apache-superset/core` — in its share scope, and at
 * `window.superset` for a build that declares the package as an external —
 * is the page core: a stable facade that routes each call to the provider it
 * is for. It is left at `window.superset` afterwards, so a build that reads
 * the global later than its entry module still finds it. A page that had a
 * `superset` global of its own (Superset itself) gets that one back instead.
 */
function loadBundle(
  src: string,
  extension: ExtensionInfo,
  shared: Record<string, unknown> | undefined,
): Promise<ExtensionBundle> {
  const cached = bundles.get(src);
  if (cached) return cached;

  const containerName = extension.moduleFederationName || extension.id;
  const globals = window as unknown as Record<string, unknown>;
  const pending = (async () => {
    // Only a page that actually loads an extension pays for antd's full
    // surface; the widgets themselves import the components they use.
    const antd = await import('antd');
    return takeContainerTurn(async () => {
      await loadScript(src);
      const container = globals[containerName];
      if (!isFederationContainer(container)) {
        throw new Error(
          `Extension ${extension.id} did not register the container "${containerName}".`,
        );
      }
      const core = getPageCore();
      const hadOther = 'superset' in globals && globals.superset !== core;
      const other = globals.superset;
      globals.superset = core;
      try {
        await container.init({
          react: shareEntry(React, versionOf(React)),
          'react-dom': shareEntry(ReactDOM, versionOf(ReactDOM)),
          antd: shareEntry(antd, versionOf(antd)),
          '@apache-superset/core': shareEntry(core, '0.1.0'),
          ...shared,
        });
        const factory = await container.get('./index');
        // What the module registers as a side effect of this call is
        // recorded, for every provider's host to replay.
        return evaluateExtension(extension, factory);
      } finally {
        if (hadOther) globals.superset = other;
      }
    });
  })();
  bundles.set(src, pending);
  pending.catch(() => {
    // A failed load is not kept: the next widget may try again.
    if (bundles.get(src) === pending) bundles.delete(src);
  });
  return pending;
}

/**
 * Loads extension widget types from `supersetDomain`.
 *
 * The extension's code runs in the host page's JavaScript context, with the
 * host's React — the same trust boundary the widgets themselves have. Its
 * bundle must be readable by whoever the page renders as (see
 * `EMBEDDED_EXTENSION_ASSETS_PUBLIC` for guest tokens, which a `<script>` tag
 * cannot carry).
 *
 * A loader belongs to one provider, and so does its {@link ExtensionHost}:
 * what an extension registers, renders, hears and queries under one provider
 * is out of reach of another. The extension's *code* is not per provider: a
 * bundle is fetched and evaluated once per page (see {@link loadBundle}) and
 * then started once for each provider that uses it, with that provider's
 * core. Share one loader between providers only if they also share a `bus`
 * and a `client`.
 */
export function createExtensionWidgetLoader(
  options: ExtensionWidgetLoaderOptions,
): ExtensionWidgetLoader {
  const api = createApiFetch(options);
  const base = options.supersetDomain.replace(/\/+$/, '');
  const host = options.host ?? createExtensionHost();
  // In flight or done, per extension, for this loader only.
  const loading = new Map<string, Promise<void>>();

  const url = (path: string) =>
    /^https?:\/\//.test(path) ? path : `${base}${path}`;

  async function loadExtension(publisher: string, name: string): Promise<void> {
    const id = `${publisher}.${name}`;
    // Asked by every provider for itself, with its own credentials: whether
    // this provider may use the extension is Superset's answer to it, not
    // something inferred from another provider having loaded the bundle.
    const extension = await api<ExtensionInfo>(
      `/api/v1/extensions/${encodeURIComponent(publisher)}/${encodeURIComponent(name)}`,
    );
    const { remoteEntry } = extension;
    if (!remoteEntry) {
      throw new Error(`Extension ${id} has no frontend to load.`);
    }
    const bundle = await loadBundle(
      url(remoteEntry),
      extension,
      options.shared,
    );
    host.activate(extension, bundle);
  }

  return async function loadExtensionWidget(type) {
    const parsed = parseExtensionWidgetType(type);
    if (!parsed) throw new Error(`Unknown widget type "${type}".`);

    let pending = loading.get(parsed.id);
    if (!pending) {
      pending = loadExtension(parsed.publisher, parsed.name);
      loading.set(parsed.id, pending);
    }
    try {
      await pending;
    } catch (error) {
      // Keeping a rejected load would make every later widget from this
      // extension fail with the first widget's error.
      if (loading.get(parsed.id) === pending) loading.delete(parsed.id);
      throw error;
    }

    const component = host.getComponent(type);
    if (!component) {
      throw new Error(
        `Extension ${parsed.id} does not contribute the widget "${type}".`,
      );
    }
    return component;
  };
}

export const ExtensionWidgetLoaderContext = createContext<
  ExtensionWidgetLoader | undefined
>(undefined);

export interface ExtensionWidgetState {
  component?: WidgetComponent;
  error?: Error;
  loading: boolean;
}

const IDLE: ExtensionWidgetState = { loading: false };

interface LoadResult {
  loader?: ExtensionWidgetLoader;
  type?: string;
  component?: WidgetComponent;
  error?: Error;
}

/**
 * Loads `type` from the extension that contributes it. Pass `undefined` for a
 * type the registry already has (or for no widget at all): the hook then does
 * nothing. An extension type with no result yet reads as loading from the
 * first render, so nothing flashes "unknown widget type" on the way.
 *
 * A result belongs to the loader that produced it: when the provider's loader
 * changes (another deployment, another token) the component of the previous
 * one is not shown while the new one loads.
 */
export function useExtensionWidget(
  type: string | undefined,
  instanceId?: string,
): ExtensionWidgetState {
  const loader = useContext(ExtensionWidgetLoaderContext);
  const reportError = useWidgetErrorReporter();
  const [result, setResult] = useState<LoadResult>({});

  useEffect(() => {
    if (!type || !isExtensionWidgetType(type)) return undefined;
    let cancelled = false;
    const fail = (error: Error) => {
      if (cancelled) return;
      setResult({ loader, type, error });
      reportError(error, { phase: 'extension', instanceId, widgetType: type });
    };
    if (!loader) {
      fail(
        new Error(
          `"${type}" is contributed by a Superset extension, which this page cannot load.`,
        ),
      );
      return undefined;
    }
    loader(type).then(
      component => {
        if (!cancelled) setResult({ loader, type, component });
      },
      (reason: unknown) => fail(toError(reason)),
    );
    return () => {
      cancelled = true;
    };
  }, [loader, type, instanceId, reportError]);

  if (!type || !isExtensionWidgetType(type)) return IDLE;
  if (result.type !== type || result.loader !== loader) {
    return { loading: true };
  }
  return { loading: false, component: result.component, error: result.error };
}

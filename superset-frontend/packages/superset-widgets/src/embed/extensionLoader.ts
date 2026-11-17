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
  type ExtensionHost,
  type ExtensionInfo,
} from './extensionHost';

const EXTENSION_WIDGET_TYPE = /^extensions\.([^.]+)\.([^.]+)\..+$/;

/** The extension that owns `type`, or undefined if it is not an extension's. */
export function parseExtensionWidgetType(
  type: string,
): { publisher: string; name: string; id: string } | undefined {
  const match = EXTENSION_WIDGET_TYPE.exec(type);
  if (!match) return undefined;
  const [, publisher, name] = match;
  return { publisher, name, id: `${publisher}.${name}` };
}

export const isExtensionWidgetType = (type: string): boolean =>
  EXTENSION_WIDGET_TYPE.test(type);

/** Resolves the component for an extension's widget type, loading it if needed. */
export type ExtensionWidgetLoader = (type: string) => Promise<WidgetComponent>;

export interface ExtensionWidgetLoaderOptions extends ApiFetchOptions {
  /**
   * Modules added to the container's share scope, beyond the `react`,
   * `react-dom`, `antd` and `@apache-superset/core` every extension declares.
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
 * The one thing the page itself forces loaders to take turns on. A Module
 * Federation container announces itself by assigning a global named after the
 * extension, and an extension built against the `superset` global reads that
 * while its entry module is evaluated. Both globals only mean something
 * between a script finishing and its container being started, so each load
 * holds this queue for exactly that stretch. It orders loads and holds
 * nothing else: no container, no core and no credential outlives a turn.
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

/**
 * Loads extension widget types from `supersetDomain`.
 *
 * The extension's code runs in the host page's JavaScript context, with the
 * host's React — the same trust boundary the widgets themselves have. Its
 * bundle must be readable by whoever the page renders as (see
 * `EMBEDDED_EXTENSION_ASSETS_PUBLIC` for guest tokens, which a `<script>` tag
 * cannot carry).
 *
 * A loader belongs to one provider. Everything it loads is evaluated for it
 * alone and registers with its own {@link ExtensionHost}, so the same
 * extension under two providers is two independent copies: neither can read
 * the other's widgets, events, filters or data. Share one loader between
 * providers only if they also share a `bus` and a `client`.
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
    const extension = await api<ExtensionInfo>(
      `/api/v1/extensions/${encodeURIComponent(publisher)}/${encodeURIComponent(name)}`,
    );
    const { remoteEntry } = extension;
    if (!remoteEntry) {
      throw new Error(`Extension ${id} has no frontend to load.`);
    }
    // Only a page that actually loads an extension pays for antd's full
    // surface; the widgets themselves import the components they use.
    const antd = await import('antd');
    const containerName = extension.moduleFederationName || id;
    const core = host.createCore(extension);
    const globals = window as unknown as Record<string, unknown>;

    await takeContainerTurn(async () => {
      // Evaluated afresh for this loader: the script assigns a new container,
      // with a module cache of its own, to the extension's global. A page
      // with two providers therefore runs two copies of the extension, each
      // started below with its own provider's core.
      await loadScript(url(remoteEntry));
      const container = globals[containerName];
      if (!isFederationContainer(container)) {
        throw new Error(
          `Extension ${id} did not register the container "${containerName}".`,
        );
      }
      // Superset's own loader puts the platform API on `window.superset`, and
      // an extension built with `externals: {'@apache-superset/core':
      // 'superset'}` reads it from there, when its entry module is evaluated,
      // rather than from the share scope below. It is set for this
      // extension's start only and then put back, so no later extension (and
      // no other provider) is handed this one's context.
      const hadPrevious = 'superset' in globals;
      const previous = globals.superset;
      globals.superset = core;
      try {
        await container.init({
          react: shareEntry(React, versionOf(React)),
          'react-dom': shareEntry(ReactDOM, versionOf(ReactDOM)),
          antd: shareEntry(antd, versionOf(antd)),
          '@apache-superset/core': shareEntry(core, '0.1.0'),
          ...options.shared,
        });
        const factory = await container.get('./index');
        // The extension registers its widgets as a side effect of this call.
        factory();
      } finally {
        if (hadPrevious) globals.superset = previous;
        else delete globals.superset;
      }
    });
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

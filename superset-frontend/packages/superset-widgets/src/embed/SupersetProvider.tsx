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
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { dashboard as dashboardApi } from '@apache-superset/core';
import {
  Theme,
  ThemeAlgorithm,
  getDirectionForLocale,
  type AnyThemeConfig,
  type Direction,
} from '@apache-superset/core/theme';
import { HOST_SOURCE_PREFIX } from '@apache-superset/core/widgets';
import { setupAGGridModules } from '@superset-ui/core/components/ThemedAgGridReact';
import { WidgetBusContext, createWidgetBus } from '../bus';
import { WidgetDataClientContext } from '../dataClient';
import {
  WidgetApiError,
  WidgetErrorContext,
  type WidgetErrorInfo,
  type WidgetErrorReporter,
} from '../errors';
import { WidgetComponentsContext } from '../registry';
import type {
  HostFilter,
  WidgetBus,
  WidgetComponent,
  WidgetDataClient,
} from '../types';
import {
  ExtensionWidgetLoaderContext,
  createExtensionWidgetLoader,
  type ExtensionWidgetLoader,
} from './extensionLoader';
import { createGuestTokenSource } from './guestToken';
import { hostFilterPayload } from './hooks';
import { createHttpWidgetClient, createUnconfiguredClient } from './httpClient';

export type ThemeModeName = 'default' | 'dark' | 'system';

export interface SupersetProviderProps {
  /** Origin of the Superset deployment, e.g. `https://superset.example.com`. */
  supersetDomain?: string;
  /**
   * A ready data client (any `WidgetDataClient` implementation); when
   * given, `supersetDomain` and the token options are not used.
   */
  client?: WidgetDataClient;
  /** A bus shared with other providers or React roots, so their widgets cross-filter. */
  bus?: WidgetBus;
  /**
   * Fetches a guest token from the host's own backend. Called again whenever
   * the token is about to expire or Superset refuses it, so it is also the
   * refresh callback. Omit to use the browser's Superset session (same-site
   * deployments, or cross-site with credentialed CORS).
   */
  fetchGuestToken?: () => Promise<string>;
  /**
   * Who the guest token is minted for. Change it when that changes (another
   * user, another tenant): the cached token is dropped and every widget
   * fetches again with a fresh one.
   */
  guestTokenKey?: string;
  guestTokenHeaderName?: string;
  guestTokenFetchTimeoutMs?: number;
  /**
   * Session mode only: send Superset's CSRF token with requests that post.
   * On by default.
   */
  csrf?: boolean;
  /**
   * Widget types contributed by Superset extensions, loaded from
   * `supersetDomain` the first time one is rendered. `false` turns that off;
   * a loader of your own replaces it.
   */
  extensionWidgets?: boolean | ExtensionWidgetLoader;
  /** Widget types of the host's own, for the widgets under this provider only. */
  widgets?: Readonly<Record<string, WidgetComponent>>;
  /**
   * Filters the host controls, by a key of its choosing. Each is ANDed onto
   * the queries of the widgets it applies to (those on `datasetId`, or only
   * `targets`). The widgets follow this prop: change a value and they fetch
   * again, set a key to `null` or drop it and the filter is lifted.
   */
  filters?: Readonly<Record<string, HostFilter | null | undefined>>;
  /**
   * Called for every failure a widget under this provider shows — a refused
   * token (401), missing access (403), a deleted widget (404), a conflict
   * (409), a network failure, a widget that threw — and for a provider that
   * was given nothing to talk to. Nothing is thrown while rendering.
   */
  onError?: (error: Error, info: WidgetErrorInfo) => void;
  /**
   * Text direction of the widgets. Defaults to that of `locale` when given,
   * else to the enclosing Superset theme or the document (`<html dir>`).
   */
  direction?: Direction;
  /** A locale code (`ar`, `ar-SA`, `en_US`); only its direction is used. */
  locale?: string;
  themeMode?: ThemeModeName;
  themeConfig?: AnyThemeConfig;
  children?: ReactNode;
}

const DARK_QUERY = '(prefers-color-scheme: dark)';

// The server has no layout to wait for; the client applies host filters
// before any widget's own effects run.
const useIsomorphicLayoutEffect =
  typeof window === 'undefined' ? useEffect : useLayoutEffect;

function useDarkMode(mode: ThemeModeName): boolean {
  const [systemDark, setSystemDark] = useState(
    () =>
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia(DARK_QUERY).matches,
  );
  useEffect(() => {
    if (mode !== 'system' || typeof window.matchMedia !== 'function') {
      return undefined;
    }
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) =>
      setSystemDark(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [mode]);
  return mode === 'dark' || (mode === 'system' && systemDark);
}

/**
 * One `Theme` for the life of the provider, updated in place. A new `Theme`
 * would bring a new provider component with it, and swapping that unmounts
 * every widget underneath: a dark-mode toggle or an inline `themeConfig`
 * object would refetch every widget and drop every selection.
 */
function useStableTheme(
  themeConfig: AnyThemeConfig | undefined,
  dark: boolean,
): Theme {
  const config = useMemo(
    () =>
      ({
        ...themeConfig,
        algorithm: dark ? ThemeAlgorithm.DARK : ThemeAlgorithm.DEFAULT,
      }) as AnyThemeConfig,
    // The value of the config, not its identity: hosts pass object literals.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(themeConfig ?? null), dark],
  );
  const [theme] = useState(() => Theme.fromConfig(config));
  const applied = useRef(config);
  useIsomorphicLayoutEffect(() => {
    if (applied.current === config) return;
    applied.current = config;
    theme.setConfig(config);
  }, [theme, config]);
  return theme;
}

type HostFilters = SupersetProviderProps['filters'];

const hostSourceId = (key: string) => `${HOST_SOURCE_PREFIX}${key}`;

/**
 * Makes the host sources on `bus` equal to `filters`, emitting only what
 * differs from `applied` (what this provider last put there, by key).
 */
function syncHostFilters(
  bus: WidgetBus,
  filters: HostFilters,
  applied: Map<string, string>,
): void {
  const wanted = new Map<string, HostFilter>();
  Object.entries(filters ?? {}).forEach(([key, filter]) => {
    if (filter) wanted.set(key, filter);
  });
  [...applied.keys()].forEach(key => {
    if (wanted.has(key)) return;
    applied.delete(key);
    bus.emit(
      hostSourceId(key),
      dashboardApi.VALUE_CHANGED_EVENT,
      hostFilterPayload(null),
    );
  });
  wanted.forEach((filter, key) => {
    const serialized = JSON.stringify(filter);
    if (applied.get(key) === serialized) return;
    applied.set(key, serialized);
    bus.emit(
      hostSourceId(key),
      dashboardApi.VALUE_CHANGED_EVENT,
      hostFilterPayload(filter),
    );
  });
}

interface OwnBus {
  bus: WidgetBus;
  /** The host filters seeded on it, by key. */
  applied: Map<string, string>;
}

/**
 * The provider's bus with the host's `filters` on it.
 *
 * On a bus the provider creates, the first set is written while the bus is
 * created — nothing listens yet — so the very first request of every widget
 * already carries it. Every later change, and everything on a bus the host
 * passed in, is applied in a layout effect: after the render that brought the
 * new `filters`, before any widget effect, with what the latest render holds
 * rather than what an older closure saw. Unmounting lifts them all.
 */
function useBusWithHostFilters(
  providedBus: WidgetBus | undefined,
  filters: HostFilters,
): WidgetBus {
  const [own] = useState<OwnBus>(() => {
    const created: OwnBus = { bus: createWidgetBus(), applied: new Map() };
    if (!providedBus) syncHostFilters(created.bus, filters, created.applied);
    return created;
  });
  const bus = providedBus ?? own.bus;
  // What this provider has put on each bus it has been on.
  const appliedByBus = useRef<WeakMap<WidgetBus, Map<string, string>>>();
  if (!appliedByBus.current) {
    appliedByBus.current = new WeakMap([[own.bus, own.applied]]);
  }
  const appliedOn = useCallback((target: WidgetBus) => {
    const byBus = appliedByBus.current as WeakMap<
      WidgetBus,
      Map<string, string>
    >;
    let applied = byBus.get(target);
    if (!applied) {
      applied = new Map();
      byBus.set(target, applied);
    }
    return applied;
  }, []);
  const serialized = JSON.stringify(filters ?? null);
  const latestFilters = useRef(filters);
  latestFilters.current = filters;

  useIsomorphicLayoutEffect(() => {
    syncHostFilters(bus, latestFilters.current, appliedOn(bus));
    // `serialized` is the value of `filters`, which is a new object on every
    // render of a host that writes it inline.
  }, [bus, appliedOn, serialized]);

  // Declared after the effect above, and without `serialized`: this cleanup
  // runs only when the provider leaves a bus, never on a change of filters.
  useIsomorphicLayoutEffect(
    () => () => syncHostFilters(bus, undefined, appliedOn(bus)),
    [bus, appliedOn],
  );

  return bus;
}

let agGridReady = false;

/**
 * Everything widgets under it share: one event bus (so they cross-filter),
 * one authenticated data client, and the Superset theme. Nothing leaks into
 * the host page's global styles.
 *
 * And nothing is shared with any other provider. The bus, the data client,
 * the guest token, the CSRF token, the host filters, the theme and the
 * extension widgets all belong to the provider instance that created them,
 * so two providers on one page — pointed at different deployments, minting
 * tokens for different users, holding different filters — are independent
 * unless the host hands both the same `bus` or `client`.
 */
export function SupersetProvider({
  supersetDomain,
  client: providedClient,
  bus: providedBus,
  fetchGuestToken,
  guestTokenKey,
  guestTokenHeaderName,
  guestTokenFetchTimeoutMs,
  csrf,
  extensionWidgets = true,
  widgets,
  filters,
  onError,
  direction,
  locale,
  themeMode = 'default',
  themeConfig,
  children,
}: SupersetProviderProps) {
  // AG Grid keeps its module registry in the library itself: registering is
  // page-wide by nature, carries nothing of a provider, and is done once.
  if (!agGridReady) {
    setupAGGridModules();
    agGridReady = true;
  }

  const fetchRef = useRef(fetchGuestToken);
  fetchRef.current = fetchGuestToken;
  const usesGuestToken = fetchGuestToken !== undefined;

  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const reportError = useCallback<WidgetErrorReporter>((error, info) => {
    try {
      onErrorRef.current?.(error, info);
    } catch (thrown) {
      // A failing handler must not take the widget that reported down too.
      // eslint-disable-next-line no-console
      console.error('[superset-widgets] onError threw', thrown);
    }
  }, []);

  const bus = useBusWithHostFilters(providedBus, filters);

  // One token source for everything this provider fetches from Superset: the
  // data client and, when an extension's widget turns up, its bundle. It is
  // tied to the deployment and to whoever the token is for, so a token minted
  // for one of either is never sent on behalf of another.
  const tokens = useMemo(() => {
    if (!usesGuestToken) return undefined;
    return createGuestTokenSource(() => {
      const fetchToken = fetchRef.current;
      return fetchToken
        ? fetchToken()
        : Promise.reject(new Error('fetchGuestToken was removed'));
    }, guestTokenFetchTimeoutMs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usesGuestToken, guestTokenFetchTimeoutMs, supersetDomain, guestTokenKey]);

  const apiOptions = useMemo(
    () =>
      supersetDomain
        ? {
            supersetDomain,
            guestTokenHeaderName,
            csrf,
            ...(tokens
              ? {
                  getGuestToken: () => tokens.get(),
                  invalidateGuestToken: (rejected: string) =>
                    tokens.invalidate(rejected),
                }
              : {}),
          }
        : undefined,
    [supersetDomain, guestTokenHeaderName, csrf, tokens],
  );

  const configError = useMemo(
    () =>
      providedClient || supersetDomain
        ? undefined
        : new WidgetApiError(
            'SupersetProvider needs either supersetDomain or client.',
            'config',
          ),
    [providedClient, supersetDomain],
  );
  useEffect(() => {
    if (configError) reportError(configError, { phase: 'config' });
  }, [configError, reportError]);

  const client = useMemo(() => {
    if (providedClient) return providedClient;
    if (!apiOptions) {
      return createUnconfiguredClient(
        'SupersetProvider needs either supersetDomain or client.',
      );
    }
    return createHttpWidgetClient(apiOptions);
  }, [providedClient, apiOptions]);

  const extensionLoader = useMemo(() => {
    if (typeof extensionWidgets === 'function') return extensionWidgets;
    if (!extensionWidgets || !apiOptions) return undefined;
    return createExtensionWidgetLoader(apiOptions);
  }, [extensionWidgets, apiOptions]);

  const dark = useDarkMode(themeMode);
  const theme = useStableTheme(themeConfig, dark);
  const { SupersetThemeProvider } = theme;
  const resolvedDirection =
    direction ?? (locale ? getDirectionForLocale(locale) : undefined);

  return (
    <SupersetThemeProvider
      withGlobalStyles={false}
      direction={resolvedDirection}
    >
      <WidgetErrorContext.Provider value={reportError}>
        <WidgetBusContext.Provider value={bus}>
          <WidgetDataClientContext.Provider value={client}>
            <WidgetComponentsContext.Provider value={widgets}>
              <ExtensionWidgetLoaderContext.Provider value={extensionLoader}>
                {children}
              </ExtensionWidgetLoaderContext.Provider>
            </WidgetComponentsContext.Provider>
          </WidgetDataClientContext.Provider>
        </WidgetBusContext.Provider>
      </WidgetErrorContext.Provider>
    </SupersetThemeProvider>
  );
}

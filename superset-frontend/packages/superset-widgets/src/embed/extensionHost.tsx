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
 * The `@apache-superset/core` an extension's frontend gets when it runs in an
 * embedded page instead of in Superset.
 *
 * The bundle is the same one Superset loads: it registers its widget with
 * `views.registerView(view, 'dashboard.widgets', Component)` and renders from
 * a node id. Here `views` lands that registration in the host's own widget
 * table, and `dashboard` is backed by the embedded widget's bus and data
 * client rather than the builder's node tree — so an extension widget embeds
 * with no knowledge that it is embedded.
 *
 * An {@link ExtensionHost} holds every registration, every rendered instance
 * and every subscription in its own closure, and a provider creates one for
 * itself (through its extension loader). Two providers on one page therefore
 * give an extension two `dashboard` namespaces that cannot name each other's
 * widgets, hear each other's events or query with each other's credentials.
 *
 * An extension's code, however, is one copy per page: its bundle is loaded
 * and evaluated once, whatever the number of providers (a second evaluation
 * of a Module Federation remote entry is not guaranteed to produce a second,
 * independent module graph). What is per provider is the *core* it works
 * against, and there are two ways an extension reaches it:
 *
 * 1. **By argument.** An extension that exports `activate(core)` is called
 *    once per provider with that provider's core and registers its widgets
 *    on it. Nothing is read from a global, so isolation is exact.
 * 2. **By import or global.** An extension that registers as a side effect of
 *    being imported, and calls `dashboard.*` on what it imported from
 *    `@apache-superset/core` (or read from `window.superset`), talks to one
 *    page-wide {@link getPageCore facade}. Its registrations are recorded
 *    once and replayed into every provider's host, and each later call is
 *    routed to the provider it belongs to; see `resolveCore` for how, and
 *    for the one case that cannot be decided.
 *
 * The only page-level state here is what that routing needs: which widget is
 * rendering (a stack that is empty outside a render or an effect flush) and
 * which hosts have a widget on screen. No registration, credential, filter
 * or event is kept there.
 */
// eslint-disable-next-line no-restricted-syntax
import * as supersetCore from '@apache-superset/core';
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  type ComponentType,
  type ReactNode,
} from 'react';
import type {
  common,
  dashboard as dashboardApi,
  views as viewsApi,
} from '@apache-superset/core';
import { DASHBOARD_WIDGETS_LOCATION } from '@apache-superset/core/widgets';
import { getActiveResolvedFilters } from '../activeFilters';
import { useWidgetBus } from '../bus';
import { useWidgetDataClient } from '../dataClient';
import type {
  DataBindingSpec,
  Disposable,
  QueryDataResult,
  WidgetBus,
  WidgetComponent,
  WidgetDataClient,
  WidgetEvent,
  WidgetProps,
} from '../types';

/**
 * The widget type a bare `dataBinding` executes as. `DataBindingWidget`
 * server-side reads nothing but `props.dataBinding`, so an extension's
 * `fetchQueryData` runs through the same validated inline path (and the same
 * guest dataset grant) as any other embedded widget, without the widget
 * API needing a second way in.
 */
const QUERY_WIDGET_TYPE = 'echarts';

/**
 * How long a node written while rendering is kept without its render being
 * committed. React may throw a render away (a suspended sibling, an
 * interrupted transition); the node it wrote is then nobody's.
 */
export const UNCOMMITTED_NODE_TTL_MS = 10_000;

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

/** Extension metadata as `GET /api/v1/extensions/<publisher>/<name>` returns it. */
export interface ExtensionInfo {
  id: string;
  publisher?: string;
  name: string;
  version?: string;
  description?: string;
  dependencies?: string[];
  remoteEntry?: string;
  moduleFederationName?: string;
}

/** The module an extension's `import ... from '@apache-superset/core'` resolves to. */
export type ExtensionCore = typeof supersetCore;

type ExtensionView = ComponentType<{ nodeId: string }>;

/**
 * An extension's code as the page holds it: what its entry module exports,
 * and what that module registered as a side effect of being evaluated.
 */
export interface ExtensionBundle {
  /** The entry module's exports; `activate(core)` is looked for here. */
  exports: unknown;
  views: { view: viewsApi.View; location: string; component: ExtensionView }[];
  listeners: { eventType: string; listener: (event: WidgetEvent) => void }[];
}

/**
 * Where one provider's extension widgets live. See the file overview for
 * what is and is not shared between hosts.
 */
export interface ExtensionHost {
  /**
   * The core of `extension` under this host: scoped to that extension the
   * way Superset's own loader scopes it, and to this host. One per extension
   * id; asking again returns the same object.
   */
  createCore(extension: ExtensionInfo): ExtensionCore;
  /**
   * Starts `bundle` for this host: replays what its module registered when
   * it was evaluated, then calls its `activate(core)` export, if it has one,
   * with this host's core. Once per extension and host.
   */
  activate(extension: ExtensionInfo, bundle: ExtensionBundle): void;
  /** Wraps an extension's widget view as a widget component of this host. */
  adaptWidget(type: string, View: ExtensionView): WidgetComponent;
  /** The component an extension registered for `type` with this host. */
  getComponent(type: string): WidgetComponent | undefined;
  /** Drops every registration, instance and subscription the host holds. */
  dispose(): void;
}

class EmbeddedDisposable {
  constructor(private readonly callOnDispose: () => void) {}

  static from(...disposables: { dispose: () => unknown }[]) {
    return new EmbeddedDisposable(() =>
      disposables.forEach(disposable => disposable.dispose()),
    );
  }

  dispose(): void {
    this.callOnDispose();
  }
}

const disposable = (callOnDispose: () => void = () => {}) =>
  new EmbeddedDisposable(callOnDispose) as unknown as common.Disposable;

const notAvailable = (api: string) => () => {
  throw new Error(`${api} is not available to an embedded widget.`);
};

interface ExtensionInstance {
  /** The mounted component that owns this entry; see `release`. */
  owner: object;
  type: string;
  /** What the host passed; it wins over `overrides` on every render. */
  props: Record<string, unknown>;
  /** Props the extension wrote with `updateProps`, for this session only. */
  overrides: Record<string, unknown>;
  bus: WidgetBus;
  client: WidgetDataClient;
  rerender: () => void;
}

interface Subscription {
  eventType: string;
  listener: (event: WidgetEvent) => void;
  attached: Map<WidgetBus, Disposable>;
}

/** What the page-level routing may ask of a host. */
interface HostRouting {
  hasInstance(id: string): boolean;
  /** The core of the extension that draws `instanceId`, or any core of the host. */
  coreFor(instanceId?: string): ExtensionCore | undefined;
}

/**
 * Whose code is running: a widget being rendered (or having its effects
 * flushed) under `host`, or an extension being started against `core`.
 */
interface Frame {
  host?: HostRouting;
  instanceId?: string;
  core?: ExtensionCore;
}

/**
 * Frames are pushed and popped synchronously around a render, an effect
 * flush or an extension's start, so this is empty whenever no such code is
 * on the stack: in an event handler, a timer, or after an `await`.
 */
const frames: Frame[] = [];
/** Hosts with at least one widget on screen. */
const liveHosts = new Set<HostRouting>();

const currentFrame = (): Frame | undefined => frames[frames.length - 1];

function dropFrame(frame: Frame, every = false): void {
  let index = frames.lastIndexOf(frame);
  while (index !== -1) {
    frames.splice(index, 1);
    index = every ? frames.lastIndexOf(frame) : -1;
  }
}

function runInFrame<T>(frame: Frame, run: () => T): T {
  frames.push(frame);
  try {
    return run();
  } finally {
    dropFrame(frame);
  }
}

function enterFrame(frame: Frame): void {
  frames.push(frame);
  // An effect that throws can keep the matching `leaveFrame` from running.
  // Effects are flushed synchronously, so by the next microtask none of this
  // frame's code is running any more.
  Promise.resolve().then(() => dropFrame(frame, true));
}

const leaveFrame = (frame: Frame): void => dropFrame(frame);

// The server has no layout to wait for.
const useIsomorphicLayoutEffect =
  typeof window === 'undefined' ? useEffect : useLayoutEffect;

/**
 * Brackets the effects that run between an `enter` and a `leave` edge of the
 * same frame, in both effect phases. React runs the effects of one commit in
 * tree order, hooks in call order, synchronously: whatever is declared (or
 * rendered) between the two edges runs with the frame current.
 */
function useFrameEdge(edge: 'enter' | 'leave', frame: Frame): void {
  const run = edge === 'enter' ? enterFrame : leaveFrame;
  // Deliberately every commit: the bracket has to surround every flush.
  useIsomorphicLayoutEffect(() => run(frame));
  useEffect(() => run(frame));
}

function FrameEdge({ edge, frame }: { edge: 'enter' | 'leave'; frame: Frame }) {
  useFrameEdge(edge, frame);
  return null;
}

const isFunctionComponent = (
  View: ExtensionView,
): View is (props: { nodeId: string }) => ReactNode =>
  typeof View === 'function' &&
  !(View.prototype as { isReactComponent?: unknown } | undefined)
    ?.isReactComponent;

/**
 * Stands in for a namespace an embedded page has no implementation of: what
 * registers something does nothing and returns a disposable, anything else
 * says it is not available.
 */
function embeddedStub<T extends object>(namespace: string, real: T): T {
  return new Proxy(
    { ...real },
    {
      get(target, property, receiver) {
        const value = Reflect.get(target, property, receiver);
        if (value !== undefined || typeof property !== 'string') return value;
        if (property.startsWith('register') || property.startsWith('onDid')) {
          return () => disposable();
        }
        return notAvailable(`${namespace}.${property}`);
      },
    },
  ) as T;
}

let sharedStaticCore: ExtensionCore | undefined;

/** The part of a core that is the same for every host and every extension. */
function staticCore(): ExtensionCore {
  sharedStaticCore ??= {
    ...supersetCore,
    common: { ...supersetCore.common, Disposable: EmbeddedDisposable },
    authentication: embeddedStub('authentication', supersetCore.authentication),
    chat: embeddedStub('chat', supersetCore.chat),
    commands: embeddedStub('commands', supersetCore.commands),
    editors: embeddedStub('editors', supersetCore.editors),
    menus: embeddedStub('menus', supersetCore.menus),
    navigation: embeddedStub('navigation', supersetCore.navigation),
    sqlLab: embeddedStub('sqlLab', supersetCore.sqlLab),
  } as unknown as ExtensionCore;
  return sharedStaticCore;
}

function extensionsNamespace(
  extension: ExtensionInfo,
): ExtensionCore['extensions'] {
  const context = {
    extension,
    get storage(): never {
      throw new Error(
        'Extension storage is not available to an embedded widget.',
      );
    },
  };
  return {
    ...supersetCore.extensions,
    getContext: () => context,
    getExtension: (id: string) => (id === extension.id ? extension : undefined),
    getAllExtensions: () => [extension],
  } as unknown as ExtensionCore['extensions'];
}

/**
 * Evaluates an extension's entry module (`start` is the Module Federation
 * factory) and returns what the page keeps of it. While `start` runs, the
 * page core records instead of acting: an extension that registers as a
 * side effect of being imported does so exactly once per page, and every
 * host replays the record for itself in {@link ExtensionHost.activate}.
 */
export function evaluateExtension(
  extension: ExtensionInfo,
  start: () => unknown,
): ExtensionBundle {
  const bundle: ExtensionBundle = {
    exports: undefined,
    views: [],
    listeners: [],
  };
  const recording = {
    ...staticCore(),
    extensions: extensionsNamespace(extension),
    views: {
      ...supersetCore.views,
      registerView: (
        view: viewsApi.View,
        location: string,
        component: ExtensionView,
      ) => {
        bundle.views.push({ view, location, component });
        return disposable();
      },
      getViews: () => undefined,
      onDidRegisterView: () => disposable(),
      onDidUnregisterView: () => disposable(),
    },
    dashboard: {
      ...embeddedStub('dashboard', supersetCore.dashboard),
      on: (eventType: string, listener: (event: WidgetEvent) => void) => {
        bundle.listeners.push({ eventType, listener });
        return disposable();
      },
    },
  } as unknown as ExtensionCore;
  bundle.exports = runInFrame({ core: recording }, start);
  return bundle;
}

type Activate = (core: ExtensionCore) => unknown;

/** The `activate(core)` an extension exports, by name or on its default export. */
function findActivate(exports: unknown): Activate | undefined {
  const named = (exports as { activate?: unknown } | null | undefined)
    ?.activate;
  if (typeof named === 'function') return named as Activate;
  const onDefault = (
    exports as { default?: { activate?: unknown } } | null | undefined
  )?.default?.activate;
  return typeof onDefault === 'function' ? (onDefault as Activate) : undefined;
}

/** `dashboard` functions whose first argument is the node they act on. */
const NODE_FIRST = new Set([
  'getNode',
  'updateProps',
  'emit',
  'getValue',
  'removeWidget',
  'moveWidget',
  'updateLayout',
]);

function namedNode(
  namespace: string,
  method: string,
  args: unknown[],
): string | undefined {
  if (namespace !== 'dashboard') return undefined;
  if (method === 'fetchQueryData') {
    const nodeId = (args[1] as { nodeId?: unknown } | undefined)?.nodeId;
    return typeof nodeId === 'string' ? nodeId : undefined;
  }
  return NODE_FIRST.has(method) && typeof args[0] === 'string'
    ? args[0]
    : undefined;
}

/**
 * The core a call on the page facade is for, in order:
 *
 * 1. the core of whatever is running — an extension being started, or the
 *    widget being rendered or having its effects flushed;
 * 2. the host that has the node the call names on screen, when exactly one
 *    host has it;
 * 3. the only host with a widget on screen.
 *
 * What is left cannot be decided and fails loudly rather than reach the wrong
 * provider: a call with no node id (or with an id two providers both use),
 * made from an event handler, a timer or after an `await`, while two
 * providers have widgets on screen. An extension avoids it altogether by
 * exporting `activate(core)` and using the core it is handed.
 */
function resolveCore(nodeId: string | undefined, api: string): ExtensionCore {
  const frame = currentFrame();
  let core = frame?.core ?? frame?.host?.coreFor(frame.instanceId);
  if (!core && !frame && nodeId !== undefined) {
    const owners = [...liveHosts].filter(host => host.hasInstance(nodeId));
    if (owners.length === 1) core = owners[0].coreFor(nodeId);
  }
  if (!core && !frame && liveHosts.size === 1) {
    const [only] = liveHosts;
    core = only.coreFor(nodeId);
  }
  if (core) return core;
  throw new Error(
    liveHosts.size === 0
      ? `${api} is only available to a rendered widget.`
      : `${api} cannot tell which SupersetProvider it is for: this extension ` +
          'reads the page-wide core while several providers have widgets on ' +
          'screen. Export activate(core) from the extension and use that core, ' +
          'or call from the widget while it renders.',
  );
}

type RoutedNamespace = 'dashboard' | 'views' | 'extensions';

/** `namespace` of the page facade: constants as they are, calls routed. */
function routedNamespace<K extends RoutedNamespace>(
  namespace: K,
): ExtensionCore[K] {
  const constants = supersetCore[namespace] as unknown as Record<
    string,
    unknown
  >;
  const routed = new Map<string, (...args: unknown[]) => unknown>();
  return new Proxy(
    {},
    {
      get(_target, property) {
        // Not thenable, and nothing behind a symbol.
        if (typeof property !== 'string' || property === 'then') {
          return undefined;
        }
        const constant = constants[property];
        if (constant !== undefined && typeof constant !== 'function') {
          return constant;
        }
        let call = routed.get(property);
        if (!call) {
          const api = `${namespace}.${property}`;
          call = (...args: unknown[]) => {
            const core = resolveCore(namedNode(namespace, property, args), api);
            const target = core[namespace] as unknown as Record<
              string,
              unknown
            >;
            const method = target[property];
            if (typeof method !== 'function') return notAvailable(api)();
            return method.apply(target, args);
          };
          routed.set(property, call);
        }
        return call;
      },
    },
  ) as ExtensionCore[K];
}

let pageCore: ExtensionCore | undefined;

/**
 * The one core every extension on the page imports (and finds at
 * `window.superset`): a stable object, safe to keep a reference to, that
 * holds nothing itself and routes each call to the provider it is for. See
 * the file overview and `resolveCore`.
 */
export function getPageCore(): ExtensionCore {
  pageCore ??= {
    ...staticCore(),
    dashboard: routedNamespace('dashboard'),
    views: routedNamespace('views'),
    extensions: routedNamespace('extensions'),
  } as ExtensionCore;
  return pageCore;
}

/** Holds the host's subscriptions on `bus` for as long as it is mounted. */
function BusLease({
  bus,
  retain,
  release,
}: {
  bus: WidgetBus;
  retain: (bus: WidgetBus) => void;
  release: (bus: WidgetBus) => void;
}) {
  useEffect(() => {
    retain(bus);
    return () => release(bus);
  }, [bus, retain, release]);
  return null;
}

/**
 * Makes the node of a committed render the host's, and takes it back when
 * its widget unmounts. It is the first child of the widget, so its effects
 * run before any effect of the extension's view.
 */
function NodeLease({
  instanceId,
  commit,
  release,
}: {
  instanceId: string;
  commit: () => void;
  release: (instanceId: string) => void;
}) {
  const releaseRef = useRef(release);
  releaseRef.current = release;
  // Deliberately every commit: it is cheap and idempotent, and it puts the
  // node back after a cleanup that was not followed by a render (strict
  // mode, or a fast refresh).
  useIsomorphicLayoutEffect(commit);
  useIsomorphicLayoutEffect(
    () => () => releaseRef.current(instanceId),
    [instanceId],
  );
  return null;
}

/** A host of its own; see {@link ExtensionHost}. */
export function createExtensionHost(): ExtensionHost {
  /** Nodes of committed widgets: what is on screen. */
  const instances = new Map<string, ExtensionInstance>();
  /**
   * Nodes written while rendering, until that render commits. The view reads
   * its node while it renders, which is before any effect can have run, so
   * the node has to exist by then; but a render is not a mount, and one that
   * React throws away must not leave a node behind. See `sweepUncommitted`.
   */
  const uncommitted = new Map<
    string,
    { instance: ExtensionInstance; renderedAt: number }
  >();
  let sweepTimer: ReturnType<typeof setTimeout> | undefined;
  const components = new Map<string, WidgetComponent>();
  const registeredViews = new Map<string, viewsApi.View>();
  const subscriptions = new Set<Subscription>();
  /** Buses with at least one mounted instance, and how many. */
  const buses = new Map<WidgetBus, number>();
  const cores = new Map<string, ExtensionCore>();
  const activated = new Set<string>();

  const lookup = (id: string): ExtensionInstance | undefined =>
    instances.get(id) ?? uncommitted.get(id)?.instance;

  /** Drops the nodes of renders that were never committed. */
  function scheduleSweep(): void {
    if (sweepTimer !== undefined) return;
    sweepTimer = setTimeout(() => {
      sweepTimer = undefined;
      const cutoff = Date.now() - UNCOMMITTED_NODE_TTL_MS;
      uncommitted.forEach((entry, id) => {
        if (entry.renderedAt <= cutoff) uncommitted.delete(id);
      });
      if (uncommitted.size > 0) scheduleSweep();
    }, UNCOMMITTED_NODE_TTL_MS);
    // A render on a server never commits; it must not hold the process open.
    (sweepTimer as { unref?: () => void }).unref?.();
  }

  const routing: HostRouting = {
    hasInstance: id => instances.has(id),
    coreFor(instanceId) {
      const type =
        instanceId === undefined ? undefined : lookup(instanceId)?.type;
      const owner = type ? parseExtensionWidgetType(type)?.id : undefined;
      const [first] = cores.values();
      return (owner ? cores.get(owner) : undefined) ?? first;
    },
  };

  /**
   * A listener an extension registered follows the buses its widgets are
   * mounted under — one, for a host owned by a provider — and lets go of a
   * bus when the last of those widgets unmounts.
   */
  function retainBus(bus: WidgetBus): void {
    const count = buses.get(bus) ?? 0;
    buses.set(bus, count + 1);
    if (count > 0) return;
    subscriptions.forEach(subscription =>
      subscription.attached.set(
        bus,
        bus.on(subscription.eventType, subscription.listener),
      ),
    );
  }

  function releaseBus(bus: WidgetBus): void {
    const count = buses.get(bus) ?? 0;
    if (count > 1) {
      buses.set(bus, count - 1);
      return;
    }
    buses.delete(bus);
    subscriptions.forEach(subscription => {
      subscription.attached.get(bus)?.dispose();
      subscription.attached.delete(bus);
    });
  }

  function getNode(id: string): dashboardApi.DashboardNode | undefined {
    const instance = lookup(id);
    if (!instance) return undefined;
    return {
      id,
      type: instance.type,
      props: { ...instance.props, ...instance.overrides },
    };
  }

  function updateProps(id: string, props: Record<string, unknown>): void {
    const instance = instances.get(id);
    if (!instance) return;
    instance.overrides = { ...instance.overrides, ...props };
    instance.rerender();
  }

  /**
   * Who a query is for. With a node id there is no doubt. Without one —
   * `fetchQueryData(binding)` as it was first specified — it is the widget
   * of this host that is rendering or having its effects flushed, which is
   * where a widget asks for its data. A call made later than that (an event
   * handler, a timer, after an `await`) carries no such context: it is then
   * attributed to the host's only widget if there is exactly one, and to no
   * widget in particular otherwise. It is never guessed to be whichever
   * widget rendered last.
   */
  function resolveCaller(nodeId: string | undefined): {
    consumerId: string;
    bus: WidgetBus;
    client: WidgetDataClient;
  } {
    const frame = currentFrame();
    const callerId =
      nodeId ?? (frame?.host === routing ? frame.instanceId : undefined);
    if (callerId !== undefined) {
      const instance = lookup(callerId);
      if (!instance) {
        throw new Error(
          `dashboard.fetchQueryData: "${callerId}" is not a rendered widget.`,
        );
      }
      return {
        consumerId: callerId,
        bus: instance.bus,
        client: instance.client,
      };
    }
    const rendered = [...instances.entries()];
    if (rendered.length === 0) {
      throw new Error(
        'dashboard.fetchQueryData is only available to a rendered widget.',
      );
    }
    const [[firstId, first]] = rendered;
    const shared = rendered.every(
      ([, instance]) =>
        instance.bus === first.bus && instance.client === first.client,
    );
    if (!shared) {
      throw new Error(
        'dashboard.fetchQueryData needs options.nodeId here: this extension has widgets under more than one provider.',
      );
    }
    return {
      consumerId: rendered.length === 1 ? firstId : '',
      bus: first.bus,
      client: first.client,
    };
  }

  async function fetchQueryData(
    binding: DataBindingSpec,
    options: dashboardApi.FetchQueryDataOptions = {},
  ): Promise<QueryDataResult> {
    const { consumerId, bus, client } = resolveCaller(options.nodeId);
    return client.fetchData({
      instanceId: consumerId,
      widget: { type: QUERY_WIDGET_TYPE, props: { dataBinding: binding } },
      filters: getActiveResolvedFilters(bus, binding.datasetId, consumerId),
      signal: options.signal,
    });
  }

  const dashboard = {
    ...supersetCore.dashboard,
    getDashboardId: () => undefined,
    getRoot: () => ({
      id: 'root',
      type: 'grid',
      children: [...instances.keys()],
    }),
    getNode,
    // The host page owns where a widget sits and what it holds; an embedded
    // widget cannot place or resize itself.
    addWidget: notAvailable('dashboard.addWidget'),
    removeWidget: notAvailable('dashboard.removeWidget'),
    moveWidget: notAvailable('dashboard.moveWidget'),
    updateLayout: notAvailable('dashboard.updateLayout'),
    updateProps,
    onDidLayoutChange: () => disposable(),
    emit: (nodeId: string, eventType: string, payload: unknown) =>
      lookup(nodeId)?.bus.emit(nodeId, eventType, payload),
    getValue: (nodeId: string, eventType: string) =>
      lookup(nodeId)?.bus.getValue(nodeId, eventType),
    on: (eventType: string, listener: (event: WidgetEvent) => void) => {
      const subscription: Subscription = {
        eventType,
        listener,
        attached: new Map(),
      };
      subscriptions.add(subscription);
      buses.forEach((_count, bus) =>
        subscription.attached.set(bus, bus.on(eventType, listener)),
      );
      return disposable(() => {
        subscriptions.delete(subscription);
        subscription.attached.forEach(attached => attached.dispose());
        subscription.attached.clear();
      });
    },
    fetchQueryData,
  } as unknown as ExtensionCore['dashboard'];

  /**
   * Renders an extension's widget view from the embedded widget's props: the
   * instance id is the node id the view is handed, so every `dashboard.*`
   * call it makes with that id resolves against this instance, on the bus and
   * client of the provider it is rendered under.
   */
  function adaptWidget(type: string, View: ExtensionView): WidgetComponent {
    const inline = isFunctionComponent(View);

    function ExtensionWidget({ instanceId, props }: WidgetProps) {
      const bus = useWidgetBus();
      const client = useWidgetDataClient();
      const [, rerender] = useReducer((tick: number) => tick + 1, 0);
      const owner = useRef({}).current;
      const frame = useMemo<Frame>(
        () => ({ host: routing, instanceId }),
        [instanceId],
      );

      const existing = lookup(instanceId);
      const entry: ExtensionInstance = {
        owner,
        type,
        props,
        overrides: existing?.owner === owner ? existing.overrides : {},
        bus,
        client,
        rerender,
      };
      // Visible to this render only until it commits; see `uncommitted`.
      uncommitted.set(instanceId, { instance: entry, renderedAt: Date.now() });
      scheduleSweep();
      const latest = useRef(entry);
      latest.current = entry;

      // A function view is called here rather than handed to React, so that
      // this component's own effects bracket the view's: a view that fetches
      // in an effect of its own is then known to be the caller on every
      // render of it, including one its own state caused.
      useFrameEdge('enter', frame);
      const view = inline ? (
        runInFrame(frame, () => View({ nodeId: instanceId }))
      ) : (
        <View nodeId={instanceId} />
      );
      useFrameEdge('leave', frame);

      return (
        <>
          <NodeLease
            instanceId={instanceId}
            commit={() => {
              const rendered = latest.current;
              instances.set(instanceId, rendered);
              if (uncommitted.get(instanceId)?.instance.owner === owner) {
                uncommitted.delete(instanceId);
              }
              liveHosts.add(routing);
            }}
            release={id => {
              // Only its own entry: another widget may have taken the id.
              if (instances.get(id)?.owner === owner) instances.delete(id);
              if (uncommitted.get(id)?.instance.owner === owner) {
                uncommitted.delete(id);
              }
              if (instances.size === 0) liveHosts.delete(routing);
            }}
          />
          <BusLease bus={bus} retain={retainBus} release={releaseBus} />
          <FrameEdge edge="enter" frame={frame} />
          {view}
          <FrameEdge edge="leave" frame={frame} />
        </>
      );
    }
    ExtensionWidget.displayName = `ExtensionWidget(${type})`;
    return ExtensionWidget;
  }

  const views = {
    ...supersetCore.views,
    registerView: (
      view: viewsApi.View,
      location: string,
      component: ExtensionView,
    ) => {
      // An embedded page renders widgets and nothing else, so a contribution
      // to any other location is accepted and ignored rather than failing the
      // load.
      if (location !== DASHBOARD_WIDGETS_LOCATION) return disposable();
      const adapted = adaptWidget(view.id, component);
      components.set(view.id, adapted);
      registeredViews.set(view.id, view);
      return disposable(() => {
        if (components.get(view.id) === adapted) components.delete(view.id);
        if (registeredViews.get(view.id) === view) {
          registeredViews.delete(view.id);
        }
      });
    },
    getViews: (location: string) =>
      location === DASHBOARD_WIDGETS_LOCATION
        ? [...registeredViews.values()]
        : undefined,
    onDidRegisterView: () => disposable(),
    onDidUnregisterView: () => disposable(),
  } as unknown as ExtensionCore['views'];

  function createCore(extension: ExtensionInfo): ExtensionCore {
    const existing = cores.get(extension.id);
    if (existing) return existing;
    const core = {
      ...staticCore(),
      views,
      dashboard,
      extensions: extensionsNamespace(extension),
    } as ExtensionCore;
    cores.set(extension.id, core);
    return core;
  }

  function activate(extension: ExtensionInfo, bundle: ExtensionBundle): void {
    if (activated.has(extension.id)) return;
    activated.add(extension.id);
    const core = createCore(extension);
    try {
      runInFrame({ host: routing, core }, () => {
        bundle.views.forEach(({ view, location, component }) =>
          core.views.registerView(view, location, component),
        );
        bundle.listeners.forEach(({ eventType, listener }) =>
          core.dashboard.on(eventType, listener),
        );
        findActivate(bundle.exports)?.(core);
      });
    } catch (error) {
      // Not started: the next widget of this extension may try again.
      activated.delete(extension.id);
      throw error;
    }
  }

  return {
    createCore,
    activate,
    adaptWidget,
    getComponent: type => components.get(type),
    dispose() {
      subscriptions.forEach(subscription =>
        subscription.attached.forEach(attached => attached.dispose()),
      );
      subscriptions.clear();
      buses.clear();
      instances.clear();
      uncommitted.clear();
      if (sweepTimer !== undefined) clearTimeout(sweepTimer);
      sweepTimer = undefined;
      liveHosts.delete(routing);
      components.clear();
      registeredViews.clear();
      cores.clear();
      activated.clear();
    },
  };
}

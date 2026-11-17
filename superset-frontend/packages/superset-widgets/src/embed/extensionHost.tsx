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
 * Nothing in this module is shared. An {@link ExtensionHost} holds every
 * registration, every rendered instance and every subscription in its own
 * closure, and a provider creates one for itself (through its extension
 * loader). Two providers on one page therefore give an extension two
 * `dashboard` namespaces that cannot name each other's widgets, hear each
 * other's events or query with each other's credentials.
 */
// eslint-disable-next-line no-restricted-syntax
import * as supersetCore from '@apache-superset/core';
import { useEffect, useReducer, useRef, type ComponentType } from 'react';
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
 * guest dataset allowlist) as any other embedded widget, without the widget
 * API needing a second way in.
 */
const QUERY_WIDGET_TYPE = 'echarts';

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

/**
 * Where one provider's extension widgets live: the widget types its
 * extensions registered and the instances rendered from them.
 */
export interface ExtensionHost {
  /**
   * The module an extension's `import ... from '@apache-superset/core'`
   * resolves to, scoped to that extension the way Superset's own loader
   * scopes it, and to this host.
   */
  createCore(extension: ExtensionInfo): typeof supersetCore;
  /** Wraps an extension's widget view as a widget component of this host. */
  adaptWidget(
    type: string,
    View: ComponentType<{ nodeId: string }>,
  ): WidgetComponent;
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

/**
 * Runs `run` in an effect. Placed before an extension's view so the effect
 * runs before any of the view's own: React runs the effects of siblings in
 * order, children first.
 */
function BeforeView({ run }: { run: () => void }) {
  // Deliberately every commit: the callback is cheap and idempotent.
  useEffect(run);
  return null;
}

/**
 * Anything the embedded host has no implementation for. Registrations are
 * tolerated — an extension that also contributes a command or a menu item
 * must still be able to load its widget — and every other call names itself
 * in the error it throws.
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
 * Removes the instance when it unmounts. Placed after the view, so on an
 * unmount the view's own cleanups — which may still emit or read its node —
 * run first.
 */
function AfterView({
  instanceId,
  release,
}: {
  instanceId: string;
  release: (instanceId: string) => void;
}) {
  const releaseRef = useRef(release);
  releaseRef.current = release;
  useEffect(() => () => releaseRef.current(instanceId), [instanceId]);
  return null;
}

/** A host of its own; see {@link ExtensionHost}. */
export function createExtensionHost(): ExtensionHost {
  const instances = new Map<string, ExtensionInstance>();
  const components = new Map<string, WidgetComponent>();
  const registeredViews = new Map<string, viewsApi.View>();
  const subscriptions = new Set<Subscription>();
  /** Buses with at least one mounted instance, and how many. */
  const buses = new Map<WidgetBus, number>();

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
    const instance = instances.get(id);
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
   * `fetchQueryData(binding)` as it was first specified — the host answers
   * only when every rendered instance shares one bus and one client, and
   * then attributes the query to no widget in particular unless there is
   * exactly one: it never guesses that the caller is whichever widget
   * rendered last.
   */
  function resolveCaller(nodeId: string | undefined): {
    consumerId: string;
    bus: WidgetBus;
    client: WidgetDataClient;
  } {
    if (nodeId !== undefined) {
      const instance = instances.get(nodeId);
      if (!instance) {
        throw new Error(
          `dashboard.fetchQueryData: "${nodeId}" is not a rendered widget.`,
        );
      }
      return { consumerId: nodeId, bus: instance.bus, client: instance.client };
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
      instances.get(nodeId)?.bus.emit(nodeId, eventType, payload),
    getValue: (nodeId: string, eventType: string) =>
      instances.get(nodeId)?.bus.getValue(nodeId, eventType),
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
  } as unknown as typeof supersetCore.dashboard;

  /**
   * Renders an extension's widget view from the embedded widget's props: the
   * instance id is the node id the view is handed, so every `dashboard.*`
   * call it makes with that id resolves against this instance, on the bus and
   * client of the provider it is rendered under.
   */
  function adaptWidget(
    type: string,
    View: ComponentType<{ nodeId: string }>,
  ): WidgetComponent {
    function ExtensionWidget({ instanceId, props }: WidgetProps) {
      const bus = useWidgetBus();
      const client = useWidgetDataClient();
      const [, rerender] = useReducer((tick: number) => tick + 1, 0);
      const owner = useRef({}).current;

      // Written during render, not in an effect: the view reads its node
      // while it renders, which happens before any effect would have run.
      const existing = instances.get(instanceId);
      const entry: ExtensionInstance = {
        owner,
        type,
        props,
        overrides: existing?.owner === owner ? existing.overrides : {},
        bus,
        client,
        rerender,
      };
      instances.set(instanceId, entry);
      const latest = useRef(entry);
      latest.current = entry;

      return (
        <>
          <BeforeView
            run={() => {
              // After a cleanup that was not followed by a render (strict
              // mode, or a fast refresh), the node has to be put back before
              // the view's own effects ask for it.
              instances.set(instanceId, latest.current);
            }}
          />
          <BusLease bus={bus} retain={retainBus} release={releaseBus} />
          <View nodeId={instanceId} />
          <AfterView
            instanceId={instanceId}
            release={id => {
              // Only its own entry: another widget may have taken the id.
              if (instances.get(id)?.owner === owner) instances.delete(id);
            }}
          />
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
      component: ComponentType<{ nodeId: string }>,
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
  } as unknown as typeof supersetCore.views;

  function createCore(extension: ExtensionInfo): typeof supersetCore {
    const context = {
      extension,
      get storage(): never {
        throw new Error(
          'Extension storage is not available to an embedded widget.',
        );
      },
    };
    return {
      ...supersetCore,
      common: { ...supersetCore.common, Disposable: EmbeddedDisposable },
      views,
      dashboard,
      extensions: {
        ...supersetCore.extensions,
        getContext: () => context,
        getExtension: (id: string) =>
          id === extension.id ? extension : undefined,
        getAllExtensions: () => [extension],
      },
      authentication: embeddedStub(
        'authentication',
        supersetCore.authentication,
      ),
      chat: embeddedStub('chat', supersetCore.chat),
      commands: embeddedStub('commands', supersetCore.commands),
      editors: embeddedStub('editors', supersetCore.editors),
      menus: embeddedStub('menus', supersetCore.menus),
      navigation: embeddedStub('navigation', supersetCore.navigation),
      sqlLab: embeddedStub('sqlLab', supersetCore.sqlLab),
    } as unknown as typeof supersetCore;
  }

  return {
    createCore,
    adaptWidget,
    getComponent: type => components.get(type),
    dispose() {
      subscriptions.forEach(subscription =>
        subscription.attached.forEach(attached => attached.dispose()),
      );
      subscriptions.clear();
      buses.clear();
      instances.clear();
      components.clear();
      registeredViews.clear();
    },
  };
}

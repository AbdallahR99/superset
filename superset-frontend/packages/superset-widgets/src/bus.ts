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
import { createContext, useContext, useSyncExternalStore } from 'react';
import type { WidgetBus, WidgetEvent } from './types';

const valueKey = (sourceId: string, eventType: string): string =>
  JSON.stringify([sourceId, eventType]);

/**
 * One listener failing must not keep the others from hearing an event, nor
 * leave the emitting widget with an exception from code it does not own.
 */
function callSafely(callback: () => void): void {
  try {
    callback();
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error('[superset-widgets] a bus listener threw', error);
  }
}

/**
 * How many buses the page has created. It only makes the ids two buses hand
 * out differ, so that a widget id names one widget on the page, not one per
 * provider; nothing a bus holds is reachable through it.
 */
let busesCreated = 0;

/**
 * A bus of its own: every value, source and listener lives in this closure, so
 * two buses on one page share nothing. A provider creates one per instance.
 */
export function createWidgetBus(): WidgetBus {
  const values = new Map<string, unknown>();
  const sources = new Map<string, Set<string>>();
  const listeners = new Map<string, Set<(event: WidgetEvent) => void>>();
  const subscribers = new Set<() => void>();
  let revision = 0;
  let allocated = 0;
  busesCreated += 1;
  const ordinal = busesCreated;

  const tick = () => {
    revision += 1;
    // Copied first: a subscriber may unsubscribe (or subscribe) while called.
    [...subscribers].forEach(subscriber => callSafely(subscriber));
  };

  return {
    emit(sourceId, eventType, payload) {
      values.set(valueKey(sourceId, eventType), payload);
      let emitted = sources.get(eventType);
      if (!emitted) {
        emitted = new Set();
        sources.set(eventType, emitted);
      }
      emitted.add(sourceId);
      const event: WidgetEvent = { nodeId: sourceId, eventType, payload };
      [...(listeners.get(eventType) ?? [])].forEach(listener =>
        callSafely(() => listener(event)),
      );
      tick();
    },
    forget(sourceId) {
      let changed = false;
      sources.forEach((emitted, eventType) => {
        if (!emitted.delete(sourceId)) return;
        values.delete(valueKey(sourceId, eventType));
        if (emitted.size === 0) sources.delete(eventType);
        changed = true;
      });
      if (changed) tick();
    },
    createSourceId() {
      allocated += 1;
      return `widget-${ordinal}-${allocated}`;
    },
    on(eventType, listener) {
      let registered = listeners.get(eventType);
      if (!registered) {
        registered = new Set();
        listeners.set(eventType, registered);
      }
      registered.add(listener);
      return {
        dispose: () => {
          const remaining = listeners.get(eventType);
          remaining?.delete(listener);
          if (remaining?.size === 0) listeners.delete(eventType);
        },
      };
    },
    getValue: (sourceId, eventType) =>
      values.get(valueKey(sourceId, eventType)),
    getSourceIds: eventType => [...(sources.get(eventType) ?? [])],
    getScopeTargets: () => undefined,
    subscribe(subscriber) {
      subscribers.add(subscriber);
      return () => {
        subscribers.delete(subscriber);
      };
    },
    getRevision: () => revision,
  };
}

export const WidgetBusContext = createContext<WidgetBus | undefined>(undefined);

export function useWidgetBus(): WidgetBus {
  const bus = useContext(WidgetBusContext);
  if (!bus) {
    throw new Error(
      'Superset widgets must be rendered inside <SupersetProvider> (or a WidgetBusContext provider).',
    );
  }
  return bus;
}

/** Re-renders the caller on every emit on `bus`. */
export const useWidgetBusRevision = (bus: WidgetBus): number =>
  useSyncExternalStore(bus.subscribe, bus.getRevision);

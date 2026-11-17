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

import type {
  common as core,
  dashboard as dashboardApi,
} from '@apache-superset/core';
import { createEventEmitter, type EventEmitter } from '../utils';
import { DEFAULT_COLUMNS } from './layoutStyle';
import { resolveExplicitCollisions } from './gridPacking';
import { HOST_SOURCE_PREFIX } from '@apache-superset/core/widgets';
import type { WidgetBus } from '@apache-superset/core/widgets';
import {
  MAX_DOCUMENT_DEPTH,
  MAX_DOCUMENT_NODES,
  collectSubtreeIds,
  depthOf,
  isInSubtree,
  sanitizeDocument,
  subtreeHeight,
} from './documentTree';
import type { DocumentIssue } from './documentTree';

type DashboardNode = dashboardApi.DashboardNode;
type WidgetSpec = dashboardApi.WidgetSpec;
type LayoutProps = dashboardApi.LayoutProps;
type WidgetEvent = dashboardApi.WidgetEvent;

/** Groups a node id and an event type into one lookup key for `eventValues`. */
const eventValueKey = (nodeId: string, eventType: string): string =>
  `${nodeId}\u0000${eventType}`;

/** Node data as stored internally — same as the public `DashboardNode`, minus `id` (the map key already is the id). */
type StoredNode = Omit<DashboardNode, 'id'>;

const ROOT_ID = 'root';

/**
 * The root's own type — the one container every dashboard always has,
 * whether or not anything has registered itself as one. Named here because
 * two things need to agree on it and neither should learn it by string
 * comparison of its own: this provider, deciding whether a new node gets a
 * `children` array at all, and the palette, deciding that placing this
 * specific type is not an authored feature (it's reserved for the root).
 * Rendered by `Grid` — see `WidgetView`, which resolves the root's
 * renderer to it directly rather than through the widget registry.
 */
export const GRID_TYPE = 'grid';

/**
 * Container types beyond the root's own — each registered by whatever adds
 * that widget (see `registerBuiltInWidgets`), the same way a
 * type registers its renderer. A container's own arrangement of its
 * children is that type's business, not this provider's (see the
 * composition/layout design doc) — this set only ever answers the one
 * question the provider itself needs: whether a freshly added node of this
 * type gets a `children` array to hold them in.
 */
const registeredContainerTypes = new Set<string>();

/** Marks `type` as a container, alongside the root's own `grid`. */
export function registerContainerType(type: string): void {
  registeredContainerTypes.add(type);
}

/** Whether placing this type produces something other nodes can go inside. */
export const isContainerType = (type: string): boolean =>
  type === GRID_TYPE || registeredContainerTypes.has(type);

function createBlankNodes(): Record<string, StoredNode> {
  return {
    [ROOT_ID]: {
      type: GRID_TYPE,
      // No total height is set here, and none is needed — the root grid's
      // rows are created on demand (see resolveContainerGridStyle), so the
      // grid is always exactly as tall as its content.
      layout: { columns: DEFAULT_COLUMNS, gap: 16 },
      children: [],
    },
  };
}

let nextNodeId = 0;
function generateNodeId(): string {
  nextNodeId += 1;
  return `node_${nextNodeId}`;
}

/** Keeps generated ids clear of the ids a loaded document already uses. */
function reserveNodeIds(ids: string[]): void {
  ids.forEach(id => {
    const match = /^node_(\d+)$/.exec(id);
    if (match) nextNodeId = Math.max(nextNodeId, Number(match[1]));
  });
}

export { HOST_SOURCE_PREFIX };

/** A node as a saved document holds it — the stored shape, keyed by id in the document. */
export type DocumentNode = StoredNode;

/**
 * In-memory store for one Dashboard v2 node tree, and the {@link WidgetBus}
 * its widgets share. The builder uses the singleton (`getInstance`), which
 * the public `dashboard.*` API and the chat tools act on.
 * Deliberately granular (mirroring `sqlLab`'s own accessor style) rather
 * than exposing a single "get everything" snapshot: callers walk the tree
 * from {@link getRoot} via {@link getNode}.
 *
 * `getRevision()` is host-internal only (not part of the public API) — a
 * cheap invalidation counter the prototype's own canvas renderer subscribes
 * to via `useSyncExternalStore`, re-reading whatever nodes it needs through
 * the same granular accessors extensions use.
 */
class DashboardProvider implements WidgetBus {
  private static instance: DashboardProvider;

  private nodes: Record<string, StoredNode> = createBlankNodes();

  private revision = 0;

  /**
   * Counts changes to the document alone. `revision` also ticks for a
   * selection and for every bus emit, neither of which is something to save;
   * this is the counter "has anything been edited since it was loaded or
   * saved" is answered from.
   */
  private documentVersion = 0;

  /**
   * Which node the author is working on.
   *
   * Host-internal, exactly like {@link getRevision} and for the same reason:
   * it is a property of one person looking at one screen, not of the
   * dashboard. Two people opening the same tree select different things, and
   * nothing about a selection belongs in a document or in the public API an
   * extension calls.
   *
   * It lives here rather than in page state because the canvas draws it and
   * the editor panel reads it, and those sit in different layers — putting it
   * in the one place both already subscribe to beats threading it through the
   * render tree that `WidgetView` deliberately keeps ignorant.
   */
  private selection: string | undefined;

  private layoutChangeEmitter = createEventEmitter<void>();

  private stateSubscribers = new Set<() => void>();

  /**
   * The runtime widget event bus backing `dashboard.emit`/`on`/`getValue` —
   * a viewer's live interaction (a filter's current selection, a chart's
   * cross-filter) rather than authored document state, so it lives here
   * alongside `selection`/`revision` and never touches `nodes`/`props`. See
   * the design note on `updateProps` in `@apache-superset/core`'s `dashboard`
   * namespace for why.
   */
  private eventValues: Record<string, unknown> = {};

  private eventEmitters = new Map<string, EventEmitter<WidgetEvent>>();

  private eventSources = new Map<string, Set<string>>();

  public static getInstance(): DashboardProvider {
    if (!DashboardProvider.instance) {
      DashboardProvider.instance = new DashboardProvider();
    }
    return DashboardProvider.instance;
  }

  public subscribe = (listener: () => void): (() => void) => {
    this.stateSubscribers.add(listener);
    return () => this.stateSubscribers.delete(listener);
  };

  public getRevision = (): number => this.revision;

  /** Host-internal. Ticks once per change to the document; see `documentVersion`. */
  public getDocumentVersion = (): number => this.documentVersion;

  public getSelection = (): string | undefined => this.selection;

  /**
   * Selects a node, or clears the selection with `undefined`.
   *
   * Ticks the same revision every mutation does, so everything already
   * subscribed re-reads without needing a second subscription of its own.
   */
  public setSelection = (id: string | undefined): void => {
    if (this.selection === id) {
      return;
    }
    this.selection = id;
    this.revision += 1;
    this.stateSubscribers.forEach(fn => fn());
  };

  private commit(nodes: Record<string, StoredNode>): void {
    // A selection is a reference to a node, and a node that is gone cannot be
    // the thing being edited. Clearing it here — rather than at each removal
    // site — covers a subtree deletion too, where the node that vanished was
    // a descendant of the one actually removed.
    if (this.selection !== undefined && !nodes[this.selection]) {
      this.selection = undefined;
    }
    this.nodes = nodes;
    this.revision += 1;
    this.documentVersion += 1;
    this.layoutChangeEmitter.fire();
    this.stateSubscribers.forEach(fn => fn());
  }

  private toNode(id: string): DashboardNode | undefined {
    const data = this.nodes[id];
    return data ? { id, ...data } : undefined;
  }

  public getRoot = (): DashboardNode => this.toNode(ROOT_ID)!;

  public getNode = (id: string): DashboardNode | undefined => this.toNode(id);

  /**
   * The container a node sits in, or `undefined` for the root and for a
   * node that is not in the tree.
   *
   * {@link moveWidget} takes the destination parent as an argument, so
   * every caller that moves a node already has to know which parent it is in
   * — a caller reordering a node within its own container most of all. The
   * walk itself is one line, and leaving it out meant each caller wrote that
   * line again over a `nodes` map only this class is supposed to hold.
   */
  public getParentId = (id: string): string | undefined =>
    this.findParentId(id, this.nodes);

  /**
   * Every node in the subtree under `id`, itself included, parents before
   * their children. Bounded and cycle-safe (see `documentTree`), so a caller
   * that needs to walk a subtree does not write a recursion of its own.
   */
  public getSubtreeIds = (id: string): string[] =>
    collectSubtreeIds(this.nodes, id);

  /**
   * Refuses a change that would take the document past the limits a loaded
   * one is held to (see `sanitizeDocument`), so the store cannot be grown
   * into something it would itself refuse to load back.
   */
  private assertWithinLimits(
    parentId: string,
    addedNodes: number,
    addedHeight: number,
  ): void {
    if (Object.keys(this.nodes).length + addedNodes > MAX_DOCUMENT_NODES) {
      throw new Error(
        `[dashboard] A dashboard may hold at most ${MAX_DOCUMENT_NODES} widgets`,
      );
    }
    const parentDepth = depthOf(this.nodes, ROOT_ID, parentId) ?? 0;
    if (parentDepth + 1 + addedHeight > MAX_DOCUMENT_DEPTH) {
      throw new Error(
        `[dashboard] Widgets may nest at most ${MAX_DOCUMENT_DEPTH} levels deep`,
      );
    }
  }

  private findParentId(
    id: string,
    nodes: Record<string, StoredNode>,
  ): string | undefined {
    return Object.entries(nodes).find(([, node]) =>
      node.children?.includes(id),
    )?.[0];
  }

  /**
   * Displaces any of `parentId`'s explicitly placed children that now
   * collide with one another (see {@link resolveExplicitCollisions}) and
   * folds the result into `nodes`. `addWidget`/`updateLayout` are the
   * two ways an extension's AI tools place a node without going through
   * `RootGrid`'s interactive drag/resize at all — this gives that
   * programmatic path the same "nothing ends up stuck overlapping"
   * guarantee a mouse-driven resize gets for free from the grid engine
   * itself, rather than leaving it to whatever the renderer happens to
   * paper over on screen without ever writing the correction back to the
   * store.
   */
  private resolveParentCollisions(
    parentId: string,
    nodes: Record<string, StoredNode>,
  ): Record<string, StoredNode> {
    const parent = nodes[parentId];
    if (!parent?.children) return nodes;

    const columns = parent.layout?.columns ?? DEFAULT_COLUMNS;
    const getNode = (nodeId: string): DashboardNode | undefined => {
      const data = nodes[nodeId];
      return data ? { id: nodeId, ...data } : undefined;
    };
    const adjustments = resolveExplicitCollisions(
      parent.children,
      columns,
      getNode,
    );
    if (Object.keys(adjustments).length === 0) return nodes;

    const result = { ...nodes };
    Object.entries(adjustments).forEach(([id, layout]) => {
      const node = result[id];
      if (node) result[id] = { ...node, layout: { ...node.layout, ...layout } };
    });
    return result;
  }

  public addWidget(parentId: string, index: number, spec: WidgetSpec): string {
    if (spec.type === GRID_TYPE) {
      throw new Error(
        `[dashboard] Cannot add a "${GRID_TYPE}" node — it is reserved for the dashboard root, not a Widget`,
      );
    }

    const parent = this.nodes[parentId];
    if (!parent) {
      throw new Error(`[dashboard] Unknown parent node "${parentId}"`);
    }
    if (!parent.children) {
      throw new Error(
        `[dashboard] Node "${parentId}" cannot hold children (not a container)`,
      );
    }

    this.assertWithinLimits(parentId, 1, 0);

    const id = generateNodeId();
    const node: StoredNode = {
      type: spec.type,
      layout: spec.layout,
      props: spec.props,
      style: spec.style,
      ...(isContainerType(spec.type) ? { children: [] } : {}),
    };

    const children = [...parent.children];
    const clampedIndex = Math.max(0, Math.min(index, children.length));
    children.splice(clampedIndex, 0, id);

    const nodes = {
      ...this.nodes,
      [parentId]: { ...parent, children },
      [id]: node,
    };

    this.commit(this.resolveParentCollisions(parentId, nodes));

    return id;
  }

  public removeWidget(id: string): void {
    if (id === ROOT_ID) {
      throw new Error('[dashboard] Cannot remove the root node');
    }
    if (!this.nodes[id]) return;

    const nodes = { ...this.nodes };
    collectSubtreeIds(this.nodes, id).forEach(nodeId => {
      // The root survives whatever a malformed subtree claims to contain.
      if (nodeId !== ROOT_ID) delete nodes[nodeId];
    });

    Object.entries(nodes).forEach(([parentId, parent]) => {
      if (parent.children?.includes(id)) {
        nodes[parentId] = {
          ...parent,
          children: parent.children.filter(childId => childId !== id),
        };
      }
    });

    this.commit(nodes);
  }

  public moveWidget(id: string, newParentId: string, newIndex: number): void {
    if (id === ROOT_ID) {
      throw new Error('[dashboard] Cannot move the root node');
    }
    if (!this.nodes[id]) {
      throw new Error(`[dashboard] Unknown node "${id}"`);
    }
    if (!this.nodes[newParentId]?.children) {
      throw new Error(
        `[dashboard] Node "${newParentId}" cannot hold children (not a container)`,
      );
    }
    if (isInSubtree(this.nodes, id, newParentId)) {
      throw new Error(
        `[dashboard] Cannot move node "${id}" into itself or one of its own descendants`,
      );
    }
    this.assertWithinLimits(newParentId, 0, subtreeHeight(this.nodes, id));

    const oldParentId = this.findParentId(id, this.nodes);

    const nodes = { ...this.nodes };
    Object.entries(nodes).forEach(([parentId, parent]) => {
      if (parent.children?.includes(id)) {
        nodes[parentId] = {
          ...parent,
          children: parent.children.filter(childId => childId !== id),
        };
      }
    });

    const targetParent = nodes[newParentId];
    const children = [...(targetParent.children ?? [])];
    const clampedIndex = Math.max(0, Math.min(newIndex, children.length));
    children.splice(clampedIndex, 0, id);
    nodes[newParentId] = { ...targetParent, children };

    // An explicit col/row (or a colSpan wider than the new parent's own
    // column count) was only ever meaningful in the *old* parent's grid —
    // carrying it over verbatim into the new one is how a moved node ends
    // up silently overlapping or overflowing its new siblings. Interactive
    // drag-based reparenting (see `RootGrid`'s `handleDragStop`) already
    // resets exactly these two things on drop; this is that same reset,
    // applied here so the programmatic path gives the same guarantee.
    //
    // None of which is true when the parent has not changed. A move within
    // one container is a reorder of reading/DOM/tab order alone, and the
    // position it keeps is the one the author placed it at. Resetting it
    // would teleport the widget to auto-placement as the price of a reorder.
    if (oldParentId !== newParentId) {
      const node = nodes[id];
      const destColumns = targetParent.layout?.columns ?? DEFAULT_COLUMNS;
      nodes[id] = {
        ...node,
        layout: {
          ...node.layout,
          col: undefined,
          row: undefined,
          colSpan:
            node.layout?.colSpan != null
              ? Math.min(node.layout.colSpan, destColumns)
              : undefined,
          // `rowSpan` is unit-dependent on the container type — row tracks in
          // the root grid, pixels in a flow container (see `flowContent`). A
          // value meaningful in the old parent would be misread in the new one
          // (e.g. `8` tracks becoming 8px), so drop it and let the destination
          // apply its own default.
          rowSpan: undefined,
        },
      };
    }

    this.commit(nodes);
  }

  public updateLayout(id: string, layout: Partial<LayoutProps>): void {
    const node = this.nodes[id];
    if (!node) {
      throw new Error(`[dashboard] Unknown node "${id}"`);
    }

    const nodes = {
      ...this.nodes,
      [id]: { ...node, layout: { ...node.layout, ...layout } },
    };

    const parentId = this.findParentId(id, nodes);
    this.commit(
      parentId ? this.resolveParentCollisions(parentId, nodes) : nodes,
    );
  }

  /**
   * Merges a `layout` update into each of several nodes at once, in a single
   * commit. A drag or resize that displaces siblings (see `RootGrid`)
   * resolves *all* of their new positions together — committing them one
   * {@link updateLayout} call at a time would tick the revision counter, and
   * so re-render every subscriber, once per displaced sibling instead of
   * once for the whole gesture.
   */
  public updateLayouts(updates: Record<string, Partial<LayoutProps>>): void {
    const nodes = { ...this.nodes };
    Object.entries(updates).forEach(([id, layout]) => {
      const node = nodes[id];
      if (!node) return;
      nodes[id] = { ...node, layout: { ...node.layout, ...layout } };
    });

    this.commit(nodes);
  }

  /**
   * Shallow-merges `props` into a node's existing props — the content-side
   * counterpart to {@link updateLayout}. Lets a chart's `echartsOptions`
   * (or a markdown widget's `content`) be edited in place, instead of the
   * only alternative being remove + re-add, which loses the node's
   * position, layout, and identity just to change what it renders.
   */
  public updateProps(id: string, props: Record<string, unknown>): void {
    const node = this.nodes[id];
    if (!node) {
      throw new Error(`[dashboard] Unknown node "${id}"`);
    }

    this.commit({
      ...this.nodes,
      [id]: { ...node, props: { ...node.props, ...props } },
    });
  }

  /**
   * Host-internal. Replaces the whole tree with a saved document and drops
   * the previous document's session state (selection, emitted values).
   *
   * A document is input (see `documentTree`): it is repaired into a strict
   * tree before anything renders it, and what had to be repaired is returned
   * so the caller can say so. One that is too large or too deep is refused
   * with a `DocumentLimitError` and leaves the current tree untouched.
   */
  public loadDocument(nodes: Record<string, DocumentNode>): DocumentIssue[] {
    const { nodes: tree, issues } = sanitizeDocument(nodes, ROOT_ID);
    const root = tree[ROOT_ID];
    // Everything that places a widget asks the root for its `children`, so a
    // stored root without the array would be a dashboard nothing can be
    // added to.
    if (!Array.isArray(root.children)) {
      tree[ROOT_ID] = { ...root, children: [] };
    }
    reserveNodeIds(Object.keys(tree));
    this.selection = undefined;
    this.eventValues = {};
    this.eventSources.clear();
    this.commit(tree);
    return issues;
  }

  /** Host-internal. Replaces the whole tree with a blank dashboard. */
  public newDocument(): void {
    this.loadDocument(createBlankNodes());
  }

  /**
   * Host-internal. The tree as a saveable document: exactly the nodes
   * reachable from the root, so nothing detached is ever written back.
   */
  public getDocument(): Record<string, DocumentNode> {
    const document: Record<string, DocumentNode> = {};
    collectSubtreeIds(this.nodes, ROOT_ID).forEach(id => {
      document[id] = this.nodes[id];
    });
    return document;
  }

  /** Every id that emitted `eventType` and is still a node in the tree, plus host sources. */
  public getSourceIds = (eventType: string): string[] =>
    [...(this.eventSources.get(eventType) ?? [])].filter(
      id => id.startsWith(HOST_SOURCE_PREFIX) || this.nodes[id] !== undefined,
    );

  /** A node's authored `props.scope.targets`; host sources carry theirs in the payload. */
  public getScopeTargets = (sourceId: string): string[] | undefined =>
    (this.nodes[sourceId]?.props?.scope as { targets?: string[] } | undefined)
      ?.targets;

  public get onDidLayoutChange() {
    return this.layoutChangeEmitter.subscribe;
  }

  private emitterFor(eventType: string): EventEmitter<WidgetEvent> {
    let emitter = this.eventEmitters.get(eventType);
    if (!emitter) {
      emitter = createEventEmitter<WidgetEvent>();
      this.eventEmitters.set(eventType, emitter);
    }
    return emitter;
  }

  public getValue = (nodeId: string, eventType: string): unknown =>
    this.eventValues[eventValueKey(nodeId, eventType)];

  /**
   * Emits `eventType` from `nodeId`, retains `payload` for later
   * `getValue` calls, and ticks `revision` so subscribers re-render — but
   * deliberately does not fire `layoutChangeEmitter`/`onDidLayoutChange`:
   * a viewer's selection is not a structural or layout change.
   */
  public emit = (nodeId: string, eventType: string, payload: unknown): void => {
    this.eventValues[eventValueKey(nodeId, eventType)] = payload;
    let sources = this.eventSources.get(eventType);
    if (!sources) {
      sources = new Set();
      this.eventSources.set(eventType, sources);
    }
    sources.add(nodeId);
    this.revision += 1;
    this.emitterFor(eventType).fire({ nodeId, eventType, payload });
    this.stateSubscribers.forEach(fn => fn());
  };

  public on = (
    eventType: string,
    listener: (e: WidgetEvent) => void,
  ): core.Disposable => this.emitterFor(eventType).subscribe(listener);

  /** Test/demo helper — discards all nodes back to a blank canvas. */
  public reset(): void {
    this.nodes = createBlankNodes();
    this.selection = undefined;
    this.revision = 0;
    this.documentVersion = 0;
    this.layoutChangeEmitter = createEventEmitter<void>();
    this.stateSubscribers.clear();
    this.eventValues = {};
    this.eventEmitters.clear();
    this.eventSources.clear();
  }
}

export default DashboardProvider;

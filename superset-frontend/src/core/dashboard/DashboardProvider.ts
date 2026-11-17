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
  collectSubtreeIds,
  createNodeMap,
  depthOf,
  getDocumentLimits,
  hasNode,
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
  return createNodeMap<StoredNode>({
    [ROOT_ID]: {
      type: GRID_TYPE,
      // No total height is set here, and none is needed — the root grid's
      // rows are created on demand (see resolveContainerGridStyle), so the
      // grid is always exactly as tall as its content.
      layout: { columns: DEFAULT_COLUMNS, gap: 16 },
      children: [],
    },
  });
}

/**
 * The highest counter a stored id may push the generator to. Far below 2^53,
 * where `n + 1 === n` and a counter stops counting; an id whose number is
 * larger is not one the generator needs to stay clear of, since it never
 * counts that far.
 */
const MAX_RESERVED_NODE_COUNTER = 2 ** 31;

const NODE_ID_SUFFIX_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789';
const NODE_ID_SUFFIX_LENGTH = 6;

/**
 * A short random tail for a generated node id. A counter alone repeats
 * between two people editing the same dashboard (both start from the same
 * loaded document), and two different widgets under one id is what makes a
 * filter's `scope.targets` point at the wrong one after a deliberate
 * overwrite. Not a secret: only unlikely to repeat.
 */
function randomIdSuffix(): string {
  const values = new Uint32Array(NODE_ID_SUFFIX_LENGTH);
  const source = globalThis.crypto;
  if (source?.getRandomValues) {
    source.getRandomValues(values);
  } else {
    for (let index = 0; index < values.length; index += 1) {
      values[index] = Math.floor(Math.random() * 0xffffffff);
    }
  }
  let suffix = '';
  values.forEach(value => {
    suffix += NODE_ID_SUFFIX_ALPHABET[value % NODE_ID_SUFFIX_ALPHABET.length];
  });
  return suffix;
}

/**
 * The counter a stored id occupies: `node_12` and `node_12_k3x9qa` both
 * occupy 12. `undefined` for an id of any other shape, and for one whose
 * number the generator could never reach.
 */
export function reservedCounterOf(id: string): number | undefined {
  const match = /^node_(\d{1,16})(?:_[A-Za-z0-9]+)?$/.exec(id);
  if (!match) return undefined;
  const value = Number(match[1]);
  return Number.isSafeInteger(value) && value <= MAX_RESERVED_NODE_COUNTER
    ? value
    : undefined;
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
   * The counter behind generated node ids. Held per store, so one document
   * (or one store on a page that renders several) cannot move the ids
   * another one hands out.
   */
  private nextNodeId = 0;

  /** Counts the source ids handed out by {@link createSourceId}. */
  private allocatedSourceIds = 0;

  /**
   * The source ids handed out and not yet forgotten. They name widgets that
   * are on the page without being nodes of the tree, so the tree cannot say
   * whether one of them still counts as a source; this does.
   */
  private allocatedSources = new Set<string>();

  /**
   * Which document the tree is. Ticks whenever the whole tree is replaced
   * (`loadDocument`, `newDocument`), and at no other time.
   *
   * Node ids repeat between documents, and a reloaded copy of one dashboard
   * has the very ids its previous copy had, so "a node with this id still
   * exists" does not say that it is the node an asynchronous write was
   * started for. Anything that writes after an `await` reads this before the
   * wait and writes only if it has not moved.
   */
  private documentGeneration = 0;

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

  /** Host-internal. Ticks when the whole tree is replaced; see `documentGeneration`. */
  public getDocumentGeneration = (): number => this.documentGeneration;

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
    if (this.selection !== undefined && !hasNode(nodes, this.selection)) {
      this.selection = undefined;
    }
    // Held without a prototype whatever built `nodes`: an id is looked up
    // here as a key, and a key such as `constructor` must find a node or
    // nothing, never a member every object has.
    this.nodes = createNodeMap(nodes);
    this.revision += 1;
    this.documentVersion += 1;
    this.layoutChangeEmitter.fire();
    this.stateSubscribers.forEach(fn => fn());
  }

  /** The stored node under `id`, and nothing else an object answers to. */
  private stored(id: string): StoredNode | undefined {
    return hasNode(this.nodes, id) ? this.nodes[id] : undefined;
  }

  private toNode(id: string): DashboardNode | undefined {
    const data = this.stored(id);
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
    const { maxNodes, maxDepth } = getDocumentLimits();
    if (Object.keys(this.nodes).length + addedNodes > maxNodes) {
      throw new Error(
        `[dashboard] A dashboard may hold at most ${maxNodes} widgets`,
      );
    }
    const parentDepth = depthOf(this.nodes, ROOT_ID, parentId) ?? 0;
    if (parentDepth + 1 + addedHeight > maxDepth) {
      throw new Error(
        `[dashboard] Widgets may nest at most ${maxDepth} levels deep`,
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
    const parent = hasNode(nodes, parentId) ? nodes[parentId] : undefined;
    if (!parent?.children) return nodes;

    const columns = parent.layout?.columns ?? DEFAULT_COLUMNS;
    const getNode = (nodeId: string): DashboardNode | undefined => {
      const data = hasNode(nodes, nodeId) ? nodes[nodeId] : undefined;
      return data ? { id: nodeId, ...data } : undefined;
    };
    const adjustments = resolveExplicitCollisions(
      parent.children,
      columns,
      getNode,
    );
    if (Object.keys(adjustments).length === 0) return nodes;

    const result = createNodeMap(nodes);
    Object.entries(adjustments).forEach(([id, layout]) => {
      const node = hasNode(result, id) ? result[id] : undefined;
      if (node) result[id] = { ...node, layout: { ...node.layout, ...layout } };
    });
    return result;
  }

  /**
   * An id no node in the tree has. The counter keeps ids readable and in
   * creation order, the random tail keeps two editors of one dashboard from
   * minting the same one, and the loop is what guarantees the id is free
   * here whatever the counter and the tail came to.
   */
  private generateNodeId(): string {
    for (;;) {
      this.nextNodeId += 1;
      const id = `node_${this.nextNodeId}_${randomIdSuffix()}`;
      if (!hasNode(this.nodes, id)) return id;
    }
  }

  /** Keeps the counter clear of the ids a loaded document already uses. */
  private reserveNodeIds(ids: string[]): void {
    ids.forEach(id => {
      const counter = reservedCounterOf(id);
      if (counter !== undefined && counter > this.nextNodeId) {
        this.nextNodeId = counter;
      }
    });
  }

  public addWidget(parentId: string, index: number, spec: WidgetSpec): string {
    if (spec.type === GRID_TYPE) {
      throw new Error(
        `[dashboard] Cannot add a "${GRID_TYPE}" node — it is reserved for the dashboard root, not a Widget`,
      );
    }

    const parent = this.stored(parentId);
    if (!parent) {
      throw new Error(`[dashboard] Unknown parent node "${parentId}"`);
    }
    if (!parent.children) {
      throw new Error(
        `[dashboard] Node "${parentId}" cannot hold children (not a container)`,
      );
    }

    this.assertWithinLimits(parentId, 1, 0);

    const id = this.generateNodeId();
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

    const nodes = createNodeMap(this.nodes);
    nodes[parentId] = { ...parent, children };
    nodes[id] = node;

    this.commit(this.resolveParentCollisions(parentId, nodes));

    return id;
  }

  public removeWidget(id: string): void {
    if (id === ROOT_ID) {
      throw new Error('[dashboard] Cannot remove the root node');
    }
    if (!this.stored(id)) return;

    const nodes = createNodeMap(this.nodes);
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
    if (!this.stored(id)) {
      throw new Error(`[dashboard] Unknown node "${id}"`);
    }
    if (!this.stored(newParentId)?.children) {
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

    const nodes = createNodeMap(this.nodes);
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
    const node = this.stored(id);
    if (!node) {
      throw new Error(`[dashboard] Unknown node "${id}"`);
    }

    const nodes = createNodeMap(this.nodes);
    nodes[id] = { ...node, layout: { ...node.layout, ...layout } };

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
    const nodes = createNodeMap(this.nodes);
    Object.entries(updates).forEach(([id, layout]) => {
      const node = hasNode(nodes, id) ? nodes[id] : undefined;
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
    const node = this.stored(id);
    if (!node) {
      throw new Error(`[dashboard] Unknown node "${id}"`);
    }

    const nodes = createNodeMap(this.nodes);
    nodes[id] = { ...node, props: { ...node.props, ...props } };
    this.commit(nodes);
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
    const { nodes: tree, issues, renamed } = sanitizeDocument(nodes, ROOT_ID);
    if (renamed.size > 0) {
      // A filter names the widgets it applies to by id, in its properties,
      // which the tree repair does not read.
      Object.keys(tree).forEach(id => {
        const node = tree[id];
        const scope = node.props?.scope as { targets?: unknown } | undefined;
        const targets = scope?.targets;
        if (
          Array.isArray(targets) &&
          targets.some(target => renamed.has(target))
        ) {
          tree[id] = {
            ...node,
            props: {
              ...node.props,
              scope: {
                ...scope,
                targets: targets.map(target => renamed.get(target) ?? target),
              },
            },
          };
        }
      });
    }
    const root = tree[ROOT_ID];
    // Everything that places a widget asks the root for its `children`, so a
    // stored root without the array would be a dashboard nothing can be
    // added to.
    if (!Array.isArray(root.children)) {
      tree[ROOT_ID] = { ...root, children: [] };
    }
    // Counted from this document alone: what an earlier one reserved says
    // nothing about which ids are free in this one.
    this.nextNodeId = 0;
    this.reserveNodeIds(Object.keys(tree));
    this.documentGeneration += 1;
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
    const document = createNodeMap<DocumentNode>();
    collectSubtreeIds(this.nodes, ROOT_ID).forEach(id => {
      document[id] = this.nodes[id];
    });
    return document;
  }

  /**
   * Every id that emitted `eventType` and still counts as a source: a node
   * that is still in the tree, a host source, or an identity this store
   * handed out itself (see {@link createSourceId}) and has not been told to
   * forget.
   */
  public getSourceIds = (eventType: string): string[] =>
    [...(this.eventSources.get(eventType) ?? [])].filter(
      id =>
        id.startsWith(HOST_SOURCE_PREFIX) ||
        hasNode(this.nodes, id) ||
        this.allocatedSources.has(id),
    );

  /** A node's authored `props.scope.targets`; host sources carry theirs in the payload. */
  public getScopeTargets = (sourceId: string): string[] | undefined =>
    (this.stored(sourceId)?.props?.scope as { targets?: string[] } | undefined)
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

  /**
   * Drops everything `sourceId` has emitted, so a widget that left the page
   * stops narrowing the others. A node of the tree is forgotten the same
   * way: the node stays, what it last emitted does not.
   */
  public forget = (sourceId: string): void => {
    // The widget behind a handed-out identity is gone; the id is not reused.
    this.allocatedSources.delete(sourceId);
    let changed = false;
    this.eventSources.forEach((sources, eventType) => {
      if (!sources.delete(sourceId)) return;
      delete this.eventValues[eventValueKey(sourceId, eventType)];
      if (sources.size === 0) this.eventSources.delete(eventType);
      changed = true;
    });
    if (!changed) return;
    this.revision += 1;
    this.stateSubscribers.forEach(fn => fn());
  };

  /**
   * A bus identity for a widget that is not a node of the tree (one an
   * extension renders on its own, say). Never a node id and never a host
   * source: neither of those namespaces starts with this prefix, and an id a
   * stored document happens to use is skipped.
   */
  public createSourceId = (): string => {
    for (;;) {
      this.allocatedSourceIds += 1;
      const id = `widget-${this.allocatedSourceIds}`;
      if (!hasNode(this.nodes, id)) {
        this.allocatedSources.add(id);
        return id;
      }
    }
  };

  /** Test/demo helper — discards all nodes back to a blank canvas. */
  public reset(): void {
    this.nodes = createBlankNodes();
    this.selection = undefined;
    this.revision = 0;
    this.documentVersion = 0;
    this.documentGeneration = 0;
    this.nextNodeId = 0;
    this.allocatedSourceIds = 0;
    this.allocatedSources.clear();
    this.layoutChangeEmitter = createEventEmitter<void>();
    this.stateSubscribers.clear();
    this.eventValues = {};
    this.eventEmitters.clear();
    this.eventSources.clear();
  }
}

export default DashboardProvider;

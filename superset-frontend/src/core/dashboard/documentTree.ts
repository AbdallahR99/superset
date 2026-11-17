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
 * @fileoverview Bounded, cycle-safe walks over a dashboard document.
 *
 * A document is a flat map of nodes that name their children by id, so
 * nothing about its shape stops two nodes naming each other, one node being
 * listed under two parents, or a child id pointing at nothing. A document is
 * also input: it arrives from the server, where any API client may have
 * written it. Every walk in this module is therefore iterative, remembers
 * what it has visited, and stops at a fixed budget, so that no document can
 * make a walk recurse without end or run without bound.
 *
 * `sanitizeDocument` is the gate a loaded document passes through once. What
 * it returns is a strict tree, which is the invariant every mutation on the
 * store then preserves; the walkers stay defensive regardless, because a
 * renderer must not depend on every writer having been careful.
 */

import getBootstrapData from 'src/utils/getBootstrapData';

/**
 * The most nodes one dashboard document may hold, the root included, when
 * the deployment does not say otherwise. The server's default for the same
 * limit (`DocumentLimits.max_nodes` in `superset/dashboard_v2/document.py`).
 */
export const MAX_DOCUMENT_NODES = 500;

/**
 * The deepest a node may sit below the root, when the deployment does not
 * say otherwise: the root is at 0 and its children at 1. The server's
 * default `DocumentLimits.max_depth`.
 */
export const MAX_DOCUMENT_DEPTH = 16;

/**
 * The most a deployment's own setting is taken at its word for. The limits
 * are what bound every walk in this module, so a configured value is itself
 * bounded: no setting can turn "a bounded walk" back into an unbounded one,
 * or a render recursion into a stack overflow.
 */
const HARD_MAX_DOCUMENT_NODES = 20_000;
const HARD_MAX_DOCUMENT_DEPTH = 64;

/** The config keys the server reads the same two limits from. */
export const MAX_NODES_CONF_KEY = 'DASHBOARD_V2_MAX_NODES';
export const MAX_DEPTH_CONF_KEY = 'DASHBOARD_V2_MAX_DEPTH';

export interface DocumentLimits {
  maxNodes: number;
  maxDepth: number;
}

const limitFrom = (value: unknown, fallback: number, hardMax: number): number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 1
    ? Math.min(value, hardMax)
    : fallback;

/**
 * The limits a document is held to on this deployment.
 *
 * Read from the page's bootstrap config where the server publishes them
 * (`common.conf.DASHBOARD_V2_MAX_NODES` / `DASHBOARD_V2_MAX_DEPTH`), so a
 * deployment that raised or lowered them on the server gets a builder that
 * agrees with what the server will accept. Where they are not published, or
 * are not positive integers, the server's defaults stand.
 */
export function getDocumentLimits(): DocumentLimits {
  let conf: Record<string, unknown> | undefined;
  try {
    conf = getBootstrapData()?.common?.conf as
      | Record<string, unknown>
      | undefined;
  } catch {
    conf = undefined;
  }
  return {
    maxNodes: limitFrom(
      conf?.[MAX_NODES_CONF_KEY],
      MAX_DOCUMENT_NODES,
      HARD_MAX_DOCUMENT_NODES,
    ),
    maxDepth: limitFrom(
      conf?.[MAX_DEPTH_CONF_KEY],
      MAX_DOCUMENT_DEPTH,
      HARD_MAX_DOCUMENT_DEPTH,
    ),
  };
}

/** The only part of a node these walks read. */
export interface TreeNode {
  children?: readonly string[];
}

type NodeMap<T extends TreeNode> = Readonly<Record<string, T>>;

/**
 * Whether `id` names something every plain object already answers to
 * (`__proto__`, `constructor`, `toString`, ...), or is `prototype`. Such an
 * id cannot be told from "no such node" by a property read on an ordinary
 * object, and the server refuses it as a node id (`RESERVED_NODE_IDS` in
 * `superset/dashboard_v2/document.py`).
 */
export const isReservedNodeId = (id: string): boolean =>
  id === 'prototype' || id in Object.prototype;

/**
 * A node map with no prototype, optionally filled from `source`. The keys of
 * a document are ids chosen by whoever wrote it, so the map that holds them
 * must have no members of its own: on an ordinary object, writing the key
 * `__proto__` replaces the prototype instead of storing a node.
 */
export function createNodeMap<T>(
  source?: Readonly<Record<string, T>>,
): Record<string, T> {
  const map: Record<string, T> = Object.create(null);
  if (source) {
    Object.keys(source).forEach(id => {
      map[id] = source[id];
    });
  }
  return map;
}

/** Whether `nodes` itself holds a node under `id`. */
export const hasNode = <T>(
  nodes: Readonly<Record<string, T>>,
  id: string,
): boolean => Object.hasOwn(nodes, id) && nodes[id] != null;

export type DocumentIssueKind =
  /** A node lists one of its own ancestors (or itself) as a child. */
  | 'cycle'
  /** A node is listed under more than one parent, or twice under one. */
  | 'multiple-parents'
  /** A child id that names no node. */
  | 'missing-child'
  /** The root listed as some node's child. */
  | 'root-as-child'
  /** A node nothing reachable from the root lists. */
  | 'orphan'
  /** A node stored under a reserved id; it is kept under another one. */
  | 'reserved-id';

/** One thing `sanitizeDocument` had to repair. */
export interface DocumentIssue {
  kind: DocumentIssueKind;
  /** The node the issue is about (the child, for a bad reference). */
  nodeId: string;
  /** The node that carried the bad reference, when there was one. */
  parentId?: string;
  /** The id a node stored under a reserved one was given instead. */
  renamedTo?: string;
}

/** A document too large or too deep to be worked on at all. */
export class DocumentLimitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DocumentLimitError';
  }
}

const childrenOf = <T extends TreeNode>(
  nodes: NodeMap<T>,
  id: string,
): readonly string[] => {
  const children = hasNode(nodes, id) ? nodes[id].children : undefined;
  return Array.isArray(children) ? children : [];
};

/**
 * Every id in the subtree under `startId`, itself included, parents before
 * their children. Each id appears once however many times the document
 * references it, and the walk stops after `limit` ids.
 */
export function collectSubtreeIds<T extends TreeNode>(
  nodes: NodeMap<T>,
  startId: string,
  limit: number = getDocumentLimits().maxNodes + 1,
): string[] {
  if (!hasNode(nodes, startId)) return [];
  const seen = new Set<string>([startId]);
  const order: string[] = [];
  const stack: string[] = [startId];
  while (stack.length > 0 && order.length < limit) {
    const id = stack.pop() as string;
    order.push(id);
    const children = childrenOf(nodes, id);
    // Pushed in reverse so the first child is the next one popped.
    for (let index = children.length - 1; index >= 0; index -= 1) {
      const childId = children[index];
      if (!seen.has(childId) && hasNode(nodes, childId)) {
        seen.add(childId);
        stack.push(childId);
      }
    }
  }
  return order;
}

/** Whether `targetId` is `ancestorId` itself or somewhere beneath it. */
export function isInSubtree<T extends TreeNode>(
  nodes: NodeMap<T>,
  ancestorId: string,
  targetId: string,
): boolean {
  if (ancestorId === targetId) return hasNode(nodes, ancestorId);
  return collectSubtreeIds(nodes, ancestorId).includes(targetId);
}

/**
 * How many levels of descendants sit under `id`: 0 for a leaf, 1 for a node
 * whose children are all leaves. Counting stops one past the depth limit.
 */
export function subtreeHeight<T extends TreeNode>(
  nodes: NodeMap<T>,
  id: string,
): number {
  const { maxDepth } = getDocumentLimits();
  const seen = new Set<string>([id]);
  let level: string[] = [id];
  let height = 0;
  while (height <= maxDepth) {
    const next: string[] = [];
    level.forEach(nodeId => {
      childrenOf(nodes, nodeId).forEach(childId => {
        if (!seen.has(childId) && hasNode(nodes, childId)) {
          seen.add(childId);
          next.push(childId);
        }
      });
    });
    if (next.length === 0) return height;
    height += 1;
    level = next;
  }
  return height;
}

/**
 * How far below `rootId` the node `id` sits: 0 for the root itself, and
 * `undefined` when the node cannot be reached from the root.
 */
export function depthOf<T extends TreeNode>(
  nodes: NodeMap<T>,
  rootId: string,
  id: string,
): number | undefined {
  if (!hasNode(nodes, rootId)) return undefined;
  const { maxDepth } = getDocumentLimits();
  const seen = new Set<string>([rootId]);
  let level: string[] = [rootId];
  let depth = 0;
  while (level.length > 0 && depth <= maxDepth + 1) {
    if (level.includes(id)) return depth;
    const next: string[] = [];
    level.forEach(nodeId => {
      childrenOf(nodes, nodeId).forEach(childId => {
        if (!seen.has(childId) && hasNode(nodes, childId)) {
          seen.add(childId);
          next.push(childId);
        }
      });
    });
    level = next;
    depth += 1;
  }
  return undefined;
}

/**
 * Turns whatever was stored into a strict tree rooted at `rootId`.
 *
 * The root's subtree is walked breadth first and each node is given to the
 * first parent that reaches it, which is the shallowest one. Any later
 * reference to a node already placed is dropped: that is what removes a
 * cycle (the reference points back up the tree) and a second parent alike.
 * References to nothing and to the root are dropped too, and nodes nothing
 * reaches are left out. A node stored under a reserved id (see
 * {@link isReservedNodeId}) is kept, content and children, under an id made
 * up for it, and every `children` list that named it is pointed at the new
 * one; `renamed` maps old to new for whatever else refers to nodes by id.
 * Every repair is reported so a caller can tell the author their document
 * was not what was stored.
 *
 * Size and depth are not repaired. Cutting a document down to a budget would
 * silently delete an author's work on the next save, so a document beyond
 * either limit is refused with a {@link DocumentLimitError} instead.
 */
export function sanitizeDocument<T extends TreeNode>(
  stored: NodeMap<T>,
  rootId: string,
): {
  nodes: Record<string, T>;
  issues: DocumentIssue[];
  renamed: Map<string, string>;
} {
  if (!hasNode(stored, rootId)) {
    throw new Error(`[dashboard] A document must contain a "${rootId}" node`);
  }
  const { maxNodes, maxDepth } = getDocumentLimits();
  const total = Object.keys(stored).length;
  if (total > maxNodes) {
    throw new DocumentLimitError(
      `[dashboard] A document may hold at most ${maxNodes} nodes (found ${total})`,
    );
  }

  const issues: DocumentIssue[] = [];
  const renamed = new Map<string, string>();
  let counter = 0;
  Object.keys(stored).forEach(id => {
    if (id === rootId || !isReservedNodeId(id) || stored[id] == null) return;
    let replacement: string;
    do {
      counter += 1;
      replacement = `renamed_${counter}`;
    } while (Object.hasOwn(stored, replacement));
    renamed.set(id, replacement);
    issues.push({ kind: 'reserved-id', nodeId: id, renamedTo: replacement });
  });
  const nodes = createNodeMap<T>();
  Object.keys(stored).forEach(id => {
    const node = stored[id];
    const children = node?.children;
    nodes[renamed.get(id) ?? id] =
      Array.isArray(children) && children.some(child => renamed.has(child))
        ? { ...node, children: children.map(c => renamed.get(c) ?? c) }
        : node;
  });

  const result = createNodeMap<T>();
  const parentOf = new Map<string, string>();
  const placed = new Set<string>([rootId]);

  const isAncestor = (candidateId: string, ofId: string): boolean => {
    let cursor: string | undefined = ofId;
    // Bounded by the depth limit the walk below enforces as it descends.
    for (let hops = 0; cursor !== undefined && hops <= total; hops += 1) {
      if (cursor === candidateId) return true;
      cursor = parentOf.get(cursor);
    }
    return false;
  };

  let level: string[] = [rootId];
  let depth = 0;
  while (level.length > 0) {
    if (depth > maxDepth) {
      throw new DocumentLimitError(
        `[dashboard] A document may nest at most ${maxDepth} levels deep`,
      );
    }
    const next: string[] = [];
    level.forEach(id => {
      const node = nodes[id];
      if (!Array.isArray(node.children)) {
        result[id] = node;
        return;
      }
      const kept: string[] = [];
      node.children.forEach(childId => {
        if (childId === rootId) {
          issues.push({ kind: 'root-as-child', nodeId: childId, parentId: id });
        } else if (!hasNode(nodes, childId)) {
          issues.push({ kind: 'missing-child', nodeId: childId, parentId: id });
        } else if (placed.has(childId)) {
          issues.push({
            kind: isAncestor(childId, id) ? 'cycle' : 'multiple-parents',
            nodeId: childId,
            parentId: id,
          });
        } else {
          placed.add(childId);
          parentOf.set(childId, id);
          kept.push(childId);
          next.push(childId);
        }
      });
      result[id] =
        kept.length === node.children.length
          ? node
          : { ...node, children: kept };
    });
    level = next;
    depth += 1;
  }

  Object.keys(nodes).forEach(id => {
    if (!placed.has(id)) issues.push({ kind: 'orphan', nodeId: id });
  });

  return { nodes: result, issues, renamed };
}

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
 * @fileoverview Walking a layout document without trusting it.
 *
 * A document is a flat map of nodes that name their children by id. Nothing in
 * that shape stops a node from listing itself, an ancestor, or a child another
 * node already lists — a document can arrive that way from storage or from
 * another writer. Every traversal here keeps a visited set and stops at a
 * depth and a node cap, so a malformed document costs a bounded walk and a
 * reported problem, never a stack overflow or a frozen tab.
 */

/** The only thing a walk needs from a node. */
export interface TreeNodeLike {
  children?: readonly string[];
}

export type NodeLookup<T extends TreeNodeLike = TreeNodeLike> = (
  id: string,
) => T | undefined;

export type NodeSource<T extends TreeNodeLike = TreeNodeLike> =
  | NodeLookup<T>
  | Readonly<Record<string, T | undefined>>
  | ReadonlyMap<string, T>;

export interface TreeLimits {
  /** Deepest level visited; the start node is depth 0. */
  maxDepth?: number;
  /** Most nodes visited in one walk. */
  maxNodes?: number;
}

export const DEFAULT_MAX_TREE_DEPTH = 64;
export const DEFAULT_MAX_TREE_NODES = 10_000;

export type TreeIssueKind =
  | 'missing-root'
  | 'cycle'
  | 'multiple-parents'
  | 'missing-child'
  | 'max-depth'
  | 'max-nodes'
  | 'unreachable';

export interface TreeIssue {
  kind: TreeIssueKind;
  /** The node the problem was found at. */
  id: string;
  /** The node that listed `id` as a child, when there is one. */
  parentId?: string;
}

export interface TreeVisit<T extends TreeNodeLike> {
  id: string;
  node: T;
  parentId: string | undefined;
  depth: number;
}

function toLookup<T extends TreeNodeLike>(nodes: NodeSource<T>): NodeLookup<T> {
  if (typeof nodes === 'function') return nodes;
  if (nodes instanceof Map) return id => nodes.get(id);
  const record = nodes as Readonly<Record<string, T | undefined>>;
  return id =>
    Object.prototype.hasOwnProperty.call(record, id) ? record[id] : undefined;
}

/**
 * Visits `rootId` and everything under it once, parents before children, in
 * child order. Returning `false` from `visit` skips that node's children.
 *
 * Iterative, so depth costs heap rather than call stack. A child id that was
 * already visited is not entered again: it is reported as a `cycle` when it
 * is one of the current node's ancestors and as `multiple-parents` otherwise.
 * The returned issues are everything the walk had to skip.
 */
export function walkTree<T extends TreeNodeLike>(
  nodes: NodeSource<T>,
  rootId: string,
  visit: (entry: TreeVisit<T>) => boolean | void,
  limits: TreeLimits = {},
): TreeIssue[] {
  const lookup = toLookup(nodes);
  const maxDepth = limits.maxDepth ?? DEFAULT_MAX_TREE_DEPTH;
  const maxNodes = limits.maxNodes ?? DEFAULT_MAX_TREE_NODES;
  const issues: TreeIssue[] = [];
  const visited = new Set<string>();
  // Ids on the path from the root to the node being expanded.
  const ancestors = new Set<string>();

  if (!lookup(rootId)) {
    return [{ kind: 'missing-root', id: rootId }];
  }

  interface Frame {
    id: string;
    parentId: string | undefined;
    depth: number;
    /** Set once the node's children are queued: popping it again leaves the node. */
    leaving?: boolean;
  }
  const stack: Frame[] = [{ id: rootId, parentId: undefined, depth: 0 }];

  while (stack.length > 0) {
    const frame = stack.pop() as Frame;
    const { id, parentId, depth } = frame;
    if (frame.leaving) {
      ancestors.delete(id);
      continue;
    }
    if (ancestors.has(id)) {
      issues.push({ kind: 'cycle', id, parentId });
      continue;
    }
    if (visited.has(id)) {
      issues.push({ kind: 'multiple-parents', id, parentId });
      continue;
    }
    const node = lookup(id);
    if (!node) {
      issues.push({ kind: 'missing-child', id, parentId });
      continue;
    }
    if (depth > maxDepth) {
      issues.push({ kind: 'max-depth', id, parentId });
      continue;
    }
    if (visited.size >= maxNodes) {
      issues.push({ kind: 'max-nodes', id, parentId });
      break;
    }
    visited.add(id);
    if (visit({ id, node, parentId, depth }) === false) continue;

    const children = Array.isArray(node.children) ? node.children : [];
    if (children.length === 0) continue;
    ancestors.add(id);
    stack.push({ id, parentId, depth, leaving: true });
    // Reversed so the first child is popped, and so visited, first.
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push({ id: children[index], parentId: id, depth: depth + 1 });
    }
  }
  return issues;
}

/** `rootId` and every id under it, each once, parents first. */
export function collectSubtreeIds(
  nodes: NodeSource,
  rootId: string,
  limits?: TreeLimits,
): string[] {
  const ids: string[] = [];
  walkTree(
    nodes,
    rootId,
    ({ id }) => {
      ids.push(id);
    },
    limits,
  );
  return ids;
}

/** True when `id` is `ancestorId` itself or sits anywhere under it. */
export function isNodeOrDescendant(
  nodes: NodeSource,
  ancestorId: string,
  id: string,
  limits?: TreeLimits,
): boolean {
  let found = false;
  walkTree(
    nodes,
    ancestorId,
    entry => {
      if (entry.id === id) found = true;
      return !found;
    },
    limits,
  );
  return found;
}

/**
 * The first node that lists `id` as a child. A scan of `ids`, not a walk, so
 * it cannot loop whatever the document holds.
 */
export function findParentId(
  nodes: NodeSource,
  ids: Iterable<string>,
  id: string,
): string | undefined {
  const lookup = toLookup(nodes);
  for (const candidate of ids) {
    if (lookup(candidate)?.children?.includes(id)) return candidate;
  }
  return undefined;
}

/**
 * The ids from `id` up to its topmost ancestor, nearest first. Stops at a
 * repeated id or at the depth cap rather than following a cycle.
 */
export function getAncestorIds(
  nodes: NodeSource,
  ids: Iterable<string>,
  id: string,
  limits: TreeLimits = {},
): string[] {
  const all = [...ids];
  const maxDepth = limits.maxDepth ?? DEFAULT_MAX_TREE_DEPTH;
  const seen = new Set<string>([id]);
  const path: string[] = [];
  let current = findParentId(nodes, all, id);
  while (
    current !== undefined &&
    !seen.has(current) &&
    path.length < maxDepth
  ) {
    seen.add(current);
    path.push(current);
    current = findParentId(nodes, all, current);
  }
  return path;
}

/**
 * The depth of the deepest node under `rootId` (0 for a leaf), bounded by the
 * same limits as every other walk.
 */
export function subtreeDepth(
  nodes: NodeSource,
  rootId: string,
  limits?: TreeLimits,
): number {
  let deepest = 0;
  walkTree(
    nodes,
    rootId,
    ({ depth }) => {
      if (depth > deepest) deepest = depth;
    },
    limits,
  );
  return deepest;
}

/**
 * Everything that keeps a document from being a tree rooted at `rootId`:
 * cycles, a node with two parents, a child id with no node, a branch past the
 * depth or size cap, and nodes nothing reaches. An empty result means every
 * walker can trust the document.
 */
export function validateTree(
  nodes: Readonly<Record<string, TreeNodeLike | undefined>>,
  rootId: string,
  limits?: TreeLimits,
): TreeIssue[] {
  const reached = new Set<string>();
  const issues = walkTree(
    nodes,
    rootId,
    ({ id }) => {
      reached.add(id);
    },
    limits,
  );
  if (issues.some(issue => issue.kind === 'missing-root')) return issues;
  Object.keys(nodes).forEach(id => {
    if (!reached.has(id)) issues.push({ kind: 'unreachable', id });
  });
  return issues;
}

/**
 * A copy of `nodes` that is a tree: every child reference a walk had to skip
 * is removed from its parent, and nodes nothing reaches are dropped. The
 * issues say what was cut, so a host can tell the user rather than repair in
 * silence.
 */
export function sanitizeTree<T extends TreeNodeLike>(
  nodes: Readonly<Record<string, T | undefined>>,
  rootId: string,
  limits?: TreeLimits,
): { nodes: Record<string, T>; issues: TreeIssue[] } {
  // No prototype, so an id like `constructor` is only ever a key.
  const kept = Object.create(null) as Record<string, T>;
  // The children each parent was actually entered through, in visit order.
  const entered = new Map<string, string[]>();
  const issues = walkTree(
    nodes,
    rootId,
    ({ id, node, parentId }) => {
      kept[id] = node;
      if (parentId !== undefined) {
        const siblings = entered.get(parentId);
        if (siblings) siblings.push(id);
        else entered.set(parentId, [id]);
      }
    },
    limits,
  );
  Object.keys(kept).forEach(id => {
    const node = kept[id];
    if (!Array.isArray(node.children)) return;
    const children = entered.get(id) ?? [];
    if (children.length !== node.children.length) {
      kept[id] = { ...node, children };
    }
  });
  Object.keys(nodes).forEach(id => {
    if (!(id in kept) && nodes[id]) issues.push({ kind: 'unreachable', id });
  });
  return { nodes: kept, issues };
}

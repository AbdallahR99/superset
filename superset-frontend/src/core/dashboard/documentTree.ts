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

/**
 * The most nodes one dashboard document may hold, the root included. The
 * server's default for the same limit (`DocumentLimits.max_nodes` in
 * `superset/dashboard_v2/document.py`); a deployment that raises it there
 * still gets a document the builder refuses to grow past this.
 */
export const MAX_DOCUMENT_NODES = 500;

/**
 * The deepest a node may sit below the root: the root is at 0 and its
 * children at 1. The server's default `DocumentLimits.max_depth`.
 */
export const MAX_DOCUMENT_DEPTH = 16;

/** The only part of a node these walks read. */
export interface TreeNode {
  children?: readonly string[];
}

type NodeMap<T extends TreeNode> = Readonly<Record<string, T>>;

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
  | 'orphan';

/** One thing `sanitizeDocument` had to repair. */
export interface DocumentIssue {
  kind: DocumentIssueKind;
  /** The node the issue is about (the child, for a bad reference). */
  nodeId: string;
  /** The node that carried the bad reference, when there was one. */
  parentId?: string;
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
  const children = nodes[id]?.children;
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
  limit: number = MAX_DOCUMENT_NODES + 1,
): string[] {
  if (nodes[startId] === undefined) return [];
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
      if (!seen.has(childId) && nodes[childId] !== undefined) {
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
  if (ancestorId === targetId) return nodes[ancestorId] !== undefined;
  return collectSubtreeIds(nodes, ancestorId).includes(targetId);
}

/**
 * How many levels of descendants sit under `id`: 0 for a leaf, 1 for a node
 * whose children are all leaves. Counting stops at `MAX_DOCUMENT_DEPTH + 1`.
 */
export function subtreeHeight<T extends TreeNode>(
  nodes: NodeMap<T>,
  id: string,
): number {
  const seen = new Set<string>([id]);
  let level: string[] = [id];
  let height = 0;
  while (height <= MAX_DOCUMENT_DEPTH) {
    const next: string[] = [];
    level.forEach(nodeId => {
      childrenOf(nodes, nodeId).forEach(childId => {
        if (!seen.has(childId) && nodes[childId] !== undefined) {
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
  if (nodes[rootId] === undefined) return undefined;
  const seen = new Set<string>([rootId]);
  let level: string[] = [rootId];
  let depth = 0;
  while (level.length > 0 && depth <= MAX_DOCUMENT_DEPTH + 1) {
    if (level.includes(id)) return depth;
    const next: string[] = [];
    level.forEach(nodeId => {
      childrenOf(nodes, nodeId).forEach(childId => {
        if (!seen.has(childId) && nodes[childId] !== undefined) {
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
 * reaches are left out. Every repair is reported so a caller can tell the
 * author their document was not what was stored.
 *
 * Size and depth are not repaired. Cutting a document down to a budget would
 * silently delete an author's work on the next save, so a document beyond
 * either limit is refused with a {@link DocumentLimitError} instead.
 */
export function sanitizeDocument<T extends TreeNode>(
  nodes: NodeMap<T>,
  rootId: string,
): { nodes: Record<string, T>; issues: DocumentIssue[] } {
  if (nodes[rootId] == null) {
    throw new Error(`[dashboard] A document must contain a "${rootId}" node`);
  }
  const total = Object.keys(nodes).length;
  if (total > MAX_DOCUMENT_NODES) {
    throw new DocumentLimitError(
      `[dashboard] A document may hold at most ${MAX_DOCUMENT_NODES} nodes (found ${total})`,
    );
  }

  const issues: DocumentIssue[] = [];
  const result: Record<string, T> = {};
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
    if (depth > MAX_DOCUMENT_DEPTH) {
      throw new DocumentLimitError(
        `[dashboard] A document may nest at most ${MAX_DOCUMENT_DEPTH} levels deep`,
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
        } else if (nodes[childId] == null) {
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

  return { nodes: result, issues };
}

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
  DocumentLimitError,
  MAX_DOCUMENT_DEPTH,
  MAX_DOCUMENT_NODES,
  collectSubtreeIds,
  depthOf,
  isInSubtree,
  sanitizeDocument,
  subtreeHeight,
} from './documentTree';
import type { TreeNode } from './documentTree';

type Nodes = Record<string, TreeNode>;

/** root -> a -> b -> a: the smallest tree that names an ancestor as a child. */
const CYCLE: Nodes = {
  root: { children: ['a'] },
  a: { children: ['b'] },
  b: { children: ['a'] },
};

/** A chain `root -> n1 -> n2 -> ...` with `length` nodes below the root. */
const chain = (length: number): Nodes => {
  const nodes: Nodes = { root: { children: length > 0 ? ['n1'] : [] } };
  for (let index = 1; index <= length; index += 1) {
    nodes[`n${index}`] = {
      children: index < length ? [`n${index + 1}`] : [],
    };
  }
  return nodes;
};

test('a subtree walk lists parents before children, each node once', () => {
  const nodes: Nodes = {
    root: { children: ['a', 'b'] },
    a: { children: ['c'] },
    b: {},
    c: {},
  };

  expect(collectSubtreeIds(nodes, 'root')).toEqual(['root', 'a', 'c', 'b']);
  expect(collectSubtreeIds(nodes, 'a')).toEqual(['a', 'c']);
  expect(collectSubtreeIds(nodes, 'missing')).toEqual([]);
});

test('a subtree walk over a cycle terminates', () => {
  expect(collectSubtreeIds(CYCLE, 'root')).toEqual(['root', 'a', 'b']);
  expect(collectSubtreeIds({ a: { children: ['a'] } }, 'a')).toEqual(['a']);
});

test('a subtree walk stops at its budget', () => {
  expect(collectSubtreeIds(chain(50), 'root', 10)).toHaveLength(10);
});

test('a subtree walk skips children that name no node', () => {
  expect(collectSubtreeIds({ root: { children: ['ghost'] } }, 'root')).toEqual([
    'root',
  ]);
});

test('membership of a subtree is answered on a cycle without recursing forever', () => {
  expect(isInSubtree(CYCLE, 'a', 'b')).toBe(true);
  expect(isInSubtree(CYCLE, 'b', 'a')).toBe(true);
  expect(isInSubtree(CYCLE, 'a', 'root')).toBe(false);
  expect(isInSubtree(CYCLE, 'a', 'a')).toBe(true);
});

test('height and depth are measured on a tree and bounded on a cycle', () => {
  const nodes = chain(3);

  expect(subtreeHeight(nodes, 'root')).toBe(3);
  expect(subtreeHeight(nodes, 'n3')).toBe(0);
  expect(depthOf(nodes, 'root', 'root')).toBe(0);
  expect(depthOf(nodes, 'root', 'n3')).toBe(3);
  expect(depthOf(nodes, 'root', 'nowhere')).toBeUndefined();

  expect(subtreeHeight(CYCLE, 'root')).toBe(2);
  expect(depthOf(CYCLE, 'root', 'b')).toBe(2);
});

test('a well-formed document passes through unchanged', () => {
  const nodes: Nodes = {
    root: { children: ['a', 'b'] },
    a: { children: [] },
    b: {},
  };

  const result = sanitizeDocument(nodes, 'root');

  expect(result.issues).toEqual([]);
  expect(result.nodes).toEqual(nodes);
  // Untouched nodes are the same objects, so nothing downstream re-renders
  // for a repair that did not happen.
  expect(result.nodes.a).toBe(nodes.a);
});

test('a cycle is cut where it points back up the tree', () => {
  const result = sanitizeDocument(CYCLE, 'root');

  expect(result.nodes).toEqual({
    root: { children: ['a'] },
    a: { children: ['b'] },
    b: { children: [] },
  });
  expect(result.issues).toEqual([
    { kind: 'cycle', nodeId: 'a', parentId: 'b' },
  ]);
});

test('a node that lists itself is cut loose from itself', () => {
  const result = sanitizeDocument(
    { root: { children: ['a'] }, a: { children: ['a'] } },
    'root',
  );

  expect(result.nodes.a).toEqual({ children: [] });
  expect(result.issues).toEqual([
    { kind: 'cycle', nodeId: 'a', parentId: 'a' },
  ]);
});

test('a node under two parents stays under the shallowest one', () => {
  const result = sanitizeDocument(
    {
      root: { children: ['a', 'shared'] },
      a: { children: ['shared'] },
      shared: {},
    },
    'root',
  );

  expect(result.nodes.root.children).toEqual(['a', 'shared']);
  expect(result.nodes.a.children).toEqual([]);
  expect(result.issues).toEqual([
    { kind: 'multiple-parents', nodeId: 'shared', parentId: 'a' },
  ]);
});

test('a child listed twice under one parent is listed once', () => {
  const result = sanitizeDocument(
    { root: { children: ['a', 'a'] }, a: {} },
    'root',
  );

  expect(result.nodes.root.children).toEqual(['a']);
  expect(result.issues).toEqual([
    { kind: 'multiple-parents', nodeId: 'a', parentId: 'root' },
  ]);
});

test('references to nothing and to the root are dropped, and orphans are left out', () => {
  const result = sanitizeDocument(
    {
      root: { children: ['a', 'ghost'] },
      a: { children: ['root'] },
      orphan: { children: ['orphanChild'] },
      orphanChild: {},
    },
    'root',
  );

  expect(Object.keys(result.nodes).sort()).toEqual(['a', 'root']);
  expect(result.nodes.root.children).toEqual(['a']);
  expect(result.nodes.a.children).toEqual([]);
  expect(result.issues).toEqual(
    expect.arrayContaining([
      { kind: 'missing-child', nodeId: 'ghost', parentId: 'root' },
      { kind: 'root-as-child', nodeId: 'root', parentId: 'a' },
      { kind: 'orphan', nodeId: 'orphan' },
      { kind: 'orphan', nodeId: 'orphanChild' },
    ]),
  );
  expect(result.issues).toHaveLength(4);
});

test('a document without a root is refused', () => {
  expect(() => sanitizeDocument({ a: {} }, 'root')).toThrow(/"root" node/);
});

test('a document at the depth limit loads and one past it is refused, not truncated', () => {
  expect(
    sanitizeDocument(chain(MAX_DOCUMENT_DEPTH), 'root').issues,
  ).toHaveLength(0);
  expect(() => sanitizeDocument(chain(MAX_DOCUMENT_DEPTH + 1), 'root')).toThrow(
    DocumentLimitError,
  );
});

test('a document past the node limit is refused, not truncated', () => {
  const nodes: Nodes = { root: { children: [] } };
  const children: string[] = [];
  for (let index = 0; index < MAX_DOCUMENT_NODES; index += 1) {
    nodes[`n${index}`] = {};
    children.push(`n${index}`);
  }
  nodes.root = { children };

  expect(() => sanitizeDocument(nodes, 'root')).toThrow(DocumentLimitError);
});

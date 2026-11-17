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
  collectSubtreeIds,
  findParentId,
  getAncestorIds,
  isNodeOrDescendant,
  sanitizeTree,
  subtreeDepth,
  validateTree,
  walkTree,
  type TreeNodeLike,
} from './tree';

type Nodes = Record<string, TreeNodeLike>;

const healthy: Nodes = {
  root: { children: ['a', 'b'] },
  a: { children: ['a1', 'a2'] },
  a1: {},
  a2: {},
  b: {},
};

const kinds = (issues: { kind: string; id: string }[]) =>
  issues.map(issue => `${issue.kind}:${issue.id}`);

test('a healthy tree is walked parents first, in child order, with no issues', () => {
  const seen: string[] = [];
  const issues = walkTree(healthy, 'root', ({ id, depth, parentId }) => {
    seen.push(`${id}@${depth}<${parentId ?? '-'}`);
  });

  expect(seen).toEqual([
    'root@0<-',
    'a@1<root',
    'a1@2<a',
    'a2@2<a',
    'b@1<root',
  ]);
  expect(issues).toEqual([]);
  expect(validateTree(healthy, 'root')).toEqual([]);
});

test('returning false from the visitor skips that subtree only', () => {
  const seen: string[] = [];
  walkTree(healthy, 'root', ({ id }) => {
    seen.push(id);
    return id !== 'a';
  });

  expect(seen).toEqual(['root', 'a', 'b']);
});

test('a node that lists itself is visited once and reported as a cycle', () => {
  const nodes: Nodes = { root: { children: ['a'] }, a: { children: ['a'] } };

  expect(collectSubtreeIds(nodes, 'root')).toEqual(['root', 'a']);
  expect(kinds(validateTree(nodes, 'root'))).toEqual(['cycle:a']);
});

test('a cycle through the root terminates and is reported', () => {
  const nodes: Nodes = {
    root: { children: ['a'] },
    a: { children: ['b'] },
    b: { children: ['root'] },
  };

  expect(collectSubtreeIds(nodes, 'root')).toEqual(['root', 'a', 'b']);
  expect(validateTree(nodes, 'root')).toEqual([
    { kind: 'cycle', id: 'root', parentId: 'b' },
  ]);
  // The graph does lead from a back to root; the walk finds it and stops.
  expect(isNodeOrDescendant(nodes, 'a', 'root')).toBe(true);
  expect(isNodeOrDescendant(nodes, 'a', 'elsewhere')).toBe(false);
  expect(isNodeOrDescendant(nodes, 'a', 'b')).toBe(true);
  expect(subtreeDepth(nodes, 'root')).toBe(2);
});

test('a node listed by two parents is entered once', () => {
  const nodes: Nodes = {
    root: { children: ['a', 'b'] },
    a: { children: ['shared'] },
    b: { children: ['shared'] },
    shared: {},
  };

  expect(collectSubtreeIds(nodes, 'root')).toEqual([
    'root',
    'a',
    'shared',
    'b',
  ]);
  expect(validateTree(nodes, 'root')).toEqual([
    { kind: 'multiple-parents', id: 'shared', parentId: 'b' },
  ]);
});

test('missing children, a missing root and unreachable nodes are reported', () => {
  const nodes: Nodes = {
    root: { children: ['gone'] },
    orphan: {},
  };

  expect(kinds(validateTree(nodes, 'root'))).toEqual([
    'missing-child:gone',
    'unreachable:orphan',
  ]);
  expect(validateTree(nodes, 'nope')).toEqual([
    { kind: 'missing-root', id: 'nope' },
  ]);
  expect(collectSubtreeIds(nodes, 'nope')).toEqual([]);
});

test('a chain deeper than the cap stops at the cap without overflowing the stack', () => {
  const nodes: Nodes = {};
  const length = 50_000;
  for (let index = 0; index < length; index += 1) {
    nodes[`n${index}`] =
      index + 1 < length ? { children: [`n${index + 1}`] } : {};
  }

  const withinCap = collectSubtreeIds(nodes, 'n0', { maxDepth: 10 });
  expect(withinCap).toHaveLength(11);
  expect(
    kinds(walkTree(nodes, 'n0', () => undefined, { maxDepth: 10 })),
  ).toEqual(['max-depth:n11']);
  // The whole chain, with the caps lifted: iteration, not recursion.
  expect(
    collectSubtreeIds(nodes, 'n0', { maxDepth: length, maxNodes: length }),
  ).toHaveLength(length);
});

test('a wide tree stops at the node cap', () => {
  const nodes: Nodes = { root: { children: [] } };
  const children: string[] = [];
  for (let index = 0; index < 100; index += 1) {
    children.push(`c${index}`);
    nodes[`c${index}`] = {};
  }
  nodes.root = { children };

  const issues = walkTree(nodes, 'root', () => undefined, { maxNodes: 10 });

  expect(collectSubtreeIds(nodes, 'root', { maxNodes: 10 })).toHaveLength(10);
  expect(kinds(issues)).toEqual(['max-nodes:c9']);
});

test('parents and ancestors are found by scanning, even inside a cycle', () => {
  const nodes: Nodes = {
    a: { children: ['b'] },
    b: { children: ['a'] },
  };
  const ids = Object.keys(nodes);

  expect(findParentId(healthy, Object.keys(healthy), 'a2')).toBe('a');
  expect(findParentId(healthy, Object.keys(healthy), 'root')).toBeUndefined();
  expect(getAncestorIds(healthy, Object.keys(healthy), 'a2')).toEqual([
    'a',
    'root',
  ]);
  expect(getAncestorIds(nodes, ids, 'a')).toEqual(['b']);
});

test('ids that collide with Object.prototype are just ids', () => {
  const nodes: Nodes = {
    root: { children: ['constructor', 'toString'] },
    constructor: {},
  };

  expect(kinds(validateTree(nodes, 'root'))).toEqual([
    'missing-child:toString',
  ]);
});

test('sanitizing cuts exactly the references a walk could not follow', () => {
  const nodes: Nodes = {
    root: { children: ['a', 'a', 'b', 'gone'] },
    a: { children: ['root', 'shared'] },
    b: { children: ['shared'] },
    shared: {},
    orphan: {},
  };

  const { nodes: clean, issues } = sanitizeTree(nodes, 'root');

  expect(clean).toEqual({
    root: { children: ['a', 'b'] },
    a: { children: ['shared'] },
    b: { children: [] },
    shared: {},
  });
  expect(validateTree(clean, 'root')).toEqual([]);
  expect(kinds(issues).sort()).toEqual(
    [
      'cycle:root',
      'missing-child:gone',
      'multiple-parents:a',
      'multiple-parents:shared',
      'unreachable:orphan',
    ].sort(),
  );
  // The input is left as it was.
  expect(nodes.root.children).toEqual(['a', 'a', 'b', 'gone']);
});

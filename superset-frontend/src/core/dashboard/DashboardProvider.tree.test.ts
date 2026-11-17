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
import DashboardProvider, { registerContainerType } from './DashboardProvider';
import type { DocumentNode } from './DashboardProvider';
import {
  DocumentLimitError,
  MAX_DOCUMENT_DEPTH,
  MAX_DOCUMENT_NODES,
} from './documentTree';

const provider = DashboardProvider.getInstance();

const BOX = 'test-box';

beforeAll(() => {
  registerContainerType(BOX);
});

beforeEach(() => {
  provider.reset();
});

const grid = (children: string[]): DocumentNode => ({ type: 'grid', children });
const box = (children: string[]): DocumentNode => ({ type: BOX, children });
const leaf = (): DocumentNode => ({ type: 'markdown' });

test('loading a cyclic document yields a tree and reports the repair', () => {
  const issues = provider.loadDocument({
    root: grid(['a']),
    a: box(['b']),
    b: box(['a']),
  });

  expect(issues).toEqual([{ kind: 'cycle', nodeId: 'a', parentId: 'b' }]);
  expect(provider.getNode('b')?.children).toEqual([]);
  expect(provider.getSubtreeIds('root')).toEqual(['root', 'a', 'b']);
});

test('loading drops orphans, so saving never writes a detached node back', () => {
  provider.loadDocument({
    root: grid(['a']),
    a: leaf(),
    orphan: leaf(),
  });

  expect(Object.keys(provider.getDocument()).sort()).toEqual(['a', 'root']);
  expect(provider.getNode('orphan')).toBeUndefined();
});

test('a document past the size limit is refused and the current tree is kept', () => {
  const kept = provider.addWidget('root', 0, { type: 'markdown' });
  const nodes: Record<string, DocumentNode> = {};
  const children: string[] = [];
  for (let index = 0; index < MAX_DOCUMENT_NODES; index += 1) {
    nodes[`n${index}`] = leaf();
    children.push(`n${index}`);
  }
  nodes.root = grid(children);

  expect(() => provider.loadDocument(nodes)).toThrow(DocumentLimitError);
  expect(provider.getRoot().children).toEqual([kept]);
});

test('a stored root without a children array can still be added to', () => {
  provider.loadDocument({ root: { type: 'grid' } });

  expect(provider.getRoot().children).toEqual([]);
  expect(() =>
    provider.addWidget('root', 0, { type: 'markdown' }),
  ).not.toThrow();
});

test('removing a container removes everything under it', () => {
  provider.loadDocument({
    root: grid(['a', 'keep']),
    a: box(['b']),
    b: box(['c']),
    c: leaf(),
    keep: leaf(),
  });

  provider.removeWidget('a');

  expect(Object.keys(provider.getDocument()).sort()).toEqual(['keep', 'root']);
  expect(provider.getRoot().children).toEqual(['keep']);
});

test('a node cannot be moved into its own subtree, however deep', () => {
  provider.loadDocument({
    root: grid(['a']),
    a: box(['b']),
    b: box(['c']),
    c: box([]),
  });

  expect(() => provider.moveWidget('a', 'c', 0)).toThrow(
    /into itself or one of its own descendants/,
  );
  expect(() => provider.moveWidget('a', 'a', 0)).toThrow(
    /into itself or one of its own descendants/,
  );
});

test('nesting stops at the depth a document may have', () => {
  let parentId = 'root';
  for (let depth = 1; depth <= MAX_DOCUMENT_DEPTH; depth += 1) {
    parentId = provider.addWidget(parentId, 0, { type: BOX });
  }

  expect(() => provider.addWidget(parentId, 0, { type: 'markdown' })).toThrow(
    /nest at most/,
  );
});

test('a move that would push a subtree past the depth limit is refused', () => {
  let parentId = 'root';
  for (let depth = 1; depth < MAX_DOCUMENT_DEPTH; depth += 1) {
    parentId = provider.addWidget(parentId, 0, { type: BOX });
  }
  // A two-level subtree does not fit under a parent with one level left.
  const outer = provider.addWidget('root', 1, { type: BOX });
  provider.addWidget(outer, 0, { type: 'markdown' });

  expect(() => provider.moveWidget(outer, parentId, 0)).toThrow(/nest at most/);
});

test('the dashboard stops growing at the node limit', () => {
  for (let count = 1; count < MAX_DOCUMENT_NODES; count += 1) {
    provider.addWidget('root', 0, { type: 'markdown' });
  }

  expect(() => provider.addWidget('root', 0, { type: 'markdown' })).toThrow(
    /at most/,
  );
});

test('the document version ticks for edits and not for selection or events', () => {
  const start = provider.getDocumentVersion();
  const id = provider.addWidget('root', 0, { type: 'markdown' });
  const afterEdit = provider.getDocumentVersion();

  provider.setSelection(id);
  provider.emit(id, 'value-changed', { resolved: 1 });

  expect(afterEdit).toBeGreaterThan(start);
  expect(provider.getDocumentVersion()).toBe(afterEdit);
});

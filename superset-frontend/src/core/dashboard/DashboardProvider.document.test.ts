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
import DashboardProvider, { reservedCounterOf } from './DashboardProvider';

const savedDocument = () => ({
  root: {
    type: 'grid',
    layout: { columns: 24, gap: 16 },
    children: ['node_50', 'node_7'],
  },
  node_50: {
    type: 'echarts',
    layout: { colSpan: 12 },
    props: { chartType: 'bar' },
  },
  node_7: {
    type: 'filter.select',
    props: { column: 'region', scope: { targets: ['node_50'] } },
  },
});

let provider: DashboardProvider;

beforeEach(() => {
  provider = new DashboardProvider();
});

test('a constructed store is independent of the singleton', () => {
  const singleton = DashboardProvider.getInstance();
  singleton.reset();

  provider.addWidget(provider.getRoot().id, 0, { type: 'markdown' });

  expect(singleton.getRoot().children).toEqual([]);
  expect(provider.getRoot().children).toHaveLength(1);
});

test('loadDocument replaces the tree and getDocument round-trips it', () => {
  provider.addWidget(provider.getRoot().id, 0, { type: 'markdown' });

  provider.loadDocument(savedDocument());

  expect(provider.getRoot().children).toEqual(['node_50', 'node_7']);
  expect(provider.getDocument()).toEqual(savedDocument());
});

test('loadDocument rejects a document without a root', () => {
  expect(() => provider.loadDocument({ node_1: { type: 'markdown' } })).toThrow(
    'must contain a "root" node',
  );
});

test('loadDocument clears session state from the previous document', () => {
  provider.loadDocument(savedDocument());
  provider.emit('node_50', 'valueChanged', { selection: 'x' });

  provider.loadDocument(savedDocument());

  expect(provider.getValue('node_50', 'valueChanged')).toBeUndefined();
  expect(provider.getSourceIds('valueChanged')).toEqual([]);
});

test('addWidget after loadDocument never reuses a loaded id', () => {
  provider.loadDocument(savedDocument());

  const id = provider.addWidget(provider.getRoot().id, 0, { type: 'text' });

  expect(['node_50', 'node_7']).not.toContain(id);
  expect(reservedCounterOf(id)).toBeGreaterThan(50);
});

test('a generated id is a counter and a random tail the server accepts', () => {
  provider.newDocument();

  const id = provider.addWidget(provider.getRoot().id, 0, { type: 'text' });

  expect(id).toMatch(/^node_1_[a-z0-9]{6}$/);
  // The server's own rule for a node id.
  expect(id).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
});

test('two stores starting from one document do not mint the same id', () => {
  const editorA = new DashboardProvider();
  const editorB = new DashboardProvider();
  editorA.loadDocument(savedDocument());
  editorB.loadDocument(savedDocument());

  const fromA = editorA.addWidget('root', 0, { type: 'text' });
  const fromB = editorB.addWidget('root', 0, { type: 'text' });

  // Same counter, since both count from the same document; the tail is what
  // tells the two widgets apart once both documents meet on the server.
  expect(reservedCounterOf(fromA)).toBe(reservedCounterOf(fromB));
  expect(fromA).not.toBe(fromB);
});

test('the id counter belongs to the store, so one document does not move another', () => {
  provider.loadDocument(savedDocument());
  provider.addWidget('root', 0, { type: 'text' });

  provider.newDocument();
  const id = provider.addWidget('root', 0, { type: 'text' });

  expect(reservedCounterOf(id)).toBe(1);
});

test('a stored id too large to count from is ignored, and ids stay distinct', () => {
  provider.loadDocument({
    root: { type: 'grid', children: ['node_9007199254740993', 'node_12'] },
    // 2^53 + 1: a counter raised to it would stop changing when incremented.
    node_9007199254740993: { type: 'markdown' },
    node_12: { type: 'markdown' },
  });

  const first = provider.addWidget('root', 0, { type: 'text' });
  const second = provider.addWidget('root', 0, { type: 'text' });

  expect(reservedCounterOf(first)).toBe(13);
  expect(reservedCounterOf(second)).toBe(14);
  expect(provider.getRoot().children).toHaveLength(4);
  expect(new Set(provider.getRoot().children).size).toBe(4);
  expect(provider.getNode('node_9007199254740993')).toBeDefined();
});

test('stored ids of the earlier shape and of the generated shape are both counted from', () => {
  expect(reservedCounterOf('node_12')).toBe(12);
  expect(reservedCounterOf('node_12_k3x9qa')).toBe(12);
  expect(reservedCounterOf('node_')).toBeUndefined();
  expect(reservedCounterOf('elsewhere_3')).toBeUndefined();
  expect(reservedCounterOf('node_9007199254740993')).toBeUndefined();
  expect(reservedCounterOf(`node_${'9'.repeat(40)}`)).toBeUndefined();
});

test('addWidget never returns an id the tree already holds', () => {
  const values = jest
    .spyOn(globalThis.crypto, 'getRandomValues')
    // A generator that keeps producing the same tail.
    .mockImplementation(array => {
      (array as Uint32Array).fill(0);
      return array;
    });
  try {
    provider.loadDocument({
      root: { type: 'grid', children: ['node_1_aaaaaa'] },
      node_1_aaaaaa: { type: 'markdown' },
    });
    // Put the counter back so the next id would be the one already taken.
    (provider as unknown as { nextNodeId: number }).nextNodeId = 0;

    const id = provider.addWidget('root', 0, { type: 'text' });

    expect(id).toBe('node_2_aaaaaa');
    expect(provider.getNode('node_1_aaaaaa')?.type).toBe('markdown');
  } finally {
    values.mockRestore();
  }
});

test('the document generation moves when the tree is replaced and at no other time', () => {
  const start = provider.getDocumentGeneration();

  const id = provider.addWidget('root', 0, { type: 'text' });
  provider.updateProps(id, { content: 'x' });
  provider.setSelection(id);
  provider.emit(id, 'valueChanged', {});
  expect(provider.getDocumentGeneration()).toBe(start);

  provider.loadDocument(savedDocument());
  expect(provider.getDocumentGeneration()).toBe(start + 1);
  provider.newDocument();
  expect(provider.getDocumentGeneration()).toBe(start + 2);
});

test('forget drops what a source emitted and tells subscribers', () => {
  provider.loadDocument(savedDocument());
  provider.emit('node_7', 'valueChanged', { selection: 'x' });
  provider.emit('node_7', 'filterBarApply', {});
  provider.emit('node_50', 'valueChanged', { selection: 'y' });
  const listener = jest.fn();
  const unsubscribe = provider.subscribe(listener);

  provider.forget('node_7');

  expect(provider.getSourceIds('valueChanged')).toEqual(['node_50']);
  expect(provider.getSourceIds('filterBarApply')).toEqual([]);
  expect(provider.getValue('node_7', 'valueChanged')).toBeUndefined();
  expect(provider.getValue('node_50', 'valueChanged')).toEqual({
    selection: 'y',
  });
  // The node itself is untouched: only what it emitted is gone.
  expect(provider.getNode('node_7')).toBeDefined();
  expect(listener).toHaveBeenCalledTimes(1);

  // Nothing left to forget, so nobody is told anything.
  provider.forget('node_7');
  provider.forget('never-emitted');
  expect(listener).toHaveBeenCalledTimes(1);
  unsubscribe();
});

test('createSourceId hands out ids that are neither node ids nor host sources', () => {
  provider.loadDocument({
    root: { type: 'grid', children: ['widget-1'] },
    'widget-1': { type: 'markdown' },
  });

  const first = provider.createSourceId();
  const second = provider.createSourceId();

  expect(first).toBe('widget-2');
  expect(second).toBe('widget-3');
  expect(reservedCounterOf(first)).toBeUndefined();
  expect(first.startsWith('host:')).toBe(false);
});

test('getSourceIds lists emitting nodes still in the tree and host sources', () => {
  provider.loadDocument(savedDocument());
  provider.emit('host:region', 'valueChanged', {});
  provider.emit('node_7', 'valueChanged', {});
  provider.emit('node_gone', 'valueChanged', {});
  provider.emit('node_7', 'filterBarApply', {});

  expect(provider.getSourceIds('valueChanged').sort()).toEqual([
    'host:region',
    'node_7',
  ]);
  expect(provider.getSourceIds('filterBarApply')).toEqual(['node_7']);
});

test("getScopeTargets reads a node's authored scope", () => {
  provider.loadDocument(savedDocument());

  expect(provider.getScopeTargets('node_7')).toEqual(['node_50']);
  expect(provider.getScopeTargets('node_50')).toBeUndefined();
  expect(provider.getScopeTargets('host:region')).toBeUndefined();
});

test('a stored document with a reserved node id loads with every node, reports it, and saves as a whole tree', () => {
  const stored = JSON.parse(
    '{"root":{"type":"grid","children":["__proto__","node_1"]},' +
      '"__proto__":{"type":"markdown","props":{"content":"kept"}},' +
      '"node_1":{"type":"filter.select","props":{"scope":{"targets":["__proto__","node_1"]}}}}',
  );

  const issues = provider.loadDocument(stored);

  expect(issues).toEqual([
    { kind: 'reserved-id', nodeId: '__proto__', renamedTo: 'renamed_1' },
  ]);
  expect(provider.getRoot().children).toEqual(['renamed_1', 'node_1']);
  expect(provider.getNode('renamed_1')).toMatchObject({
    type: 'markdown',
    props: { content: 'kept' },
  });
  // What pointed at the node by id still does.
  expect(provider.getScopeTargets('node_1')).toEqual(['renamed_1', 'node_1']);

  // Every child the saved document lists is a node it holds.
  const document = provider.getDocument();
  expect(Object.keys(document).sort()).toEqual(['node_1', 'renamed_1', 'root']);

  // And the content survives an edit elsewhere in the tree.
  provider.updateProps('node_1', { column: 'region' });
  expect(provider.getNode('renamed_1')?.props).toEqual({ content: 'kept' });
});

test('names every object answers to are not nodes of the store', () => {
  provider.loadDocument(savedDocument());
  const before = provider.getDocumentVersion();

  ['__proto__', 'constructor', 'toString', 'hasOwnProperty'].forEach(id => {
    expect(provider.getNode(id)).toBeUndefined();
    expect(provider.getSubtreeIds(id)).toEqual([]);
    expect(provider.getScopeTargets(id)).toBeUndefined();
    expect(() => provider.updateProps(id, { a: 1 })).toThrow(/Unknown node/);
    expect(() => provider.updateLayout(id, { colSpan: 2 })).toThrow(
      /Unknown node/,
    );
    expect(() => provider.addWidget(id, 0, { type: 'markdown' })).toThrow(
      /Unknown parent/,
    );
    expect(() => provider.moveWidget(id, 'root', 0)).toThrow(/Unknown node/);
    provider.removeWidget(id);
    provider.emit(id, 'filter.change', { value: 1 });
  });
  provider.updateLayouts({ constructor: { colSpan: 3 } });

  expect(provider.getSourceIds('filter.change')).toEqual([]);
  expect(Object.keys(provider.getDocument()).sort()).toEqual([
    'node_50',
    'node_7',
    'root',
  ]);
  // Only `updateLayouts` committed, and it wrote nothing under that name.
  expect(provider.getDocumentVersion()).toBe(before + 1);
  provider.setSelection('constructor');
  provider.updateProps('node_7', { column: 'city' });
  expect(provider.getSelection()).toBeUndefined();
});

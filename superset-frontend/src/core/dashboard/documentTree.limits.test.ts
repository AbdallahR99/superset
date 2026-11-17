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
import getBootstrapData from 'src/utils/getBootstrapData';
import DashboardProvider from './DashboardProvider';
import {
  DocumentLimitError,
  MAX_DOCUMENT_DEPTH,
  MAX_DOCUMENT_NODES,
  getDocumentLimits,
  sanitizeDocument,
} from './documentTree';
import type { TreeNode } from './documentTree';
import { isUnrenderable } from './nodePath';

jest.mock('src/utils/getBootstrapData');

const bootstrap = getBootstrapData as jest.MockedFunction<
  typeof getBootstrapData
>;

/** The bootstrap payload as the page would carry it, with this `conf`. */
const withConf = (conf: Record<string, unknown> | undefined): void => {
  bootstrap.mockReturnValue({
    common: conf === undefined ? {} : { conf },
  } as unknown as ReturnType<typeof getBootstrapData>);
};

type Nodes = Record<string, TreeNode>;

/** A root with `count` leaves under it. */
const flat = (count: number): Nodes => {
  const ids = Array.from({ length: count }, (_, index) => `n${index}`);
  return {
    root: { children: ids },
    ...Object.fromEntries(ids.map(id => [id, {}])),
  };
};

/** A chain `root -> n1 -> n2 -> ...` with `length` nodes below the root. */
const chain = (length: number): Nodes => {
  const nodes: Nodes = { root: { children: length > 0 ? ['n1'] : [] } };
  for (let index = 1; index <= length; index += 1) {
    nodes[`n${index}`] = { children: index < length ? [`n${index + 1}`] : [] };
  }
  return nodes;
};

beforeEach(() => {
  bootstrap.mockReset();
  withConf(undefined);
});

test('the limits are the server defaults when the page does not publish any', () => {
  expect(getDocumentLimits()).toEqual({
    maxNodes: MAX_DOCUMENT_NODES,
    maxDepth: MAX_DOCUMENT_DEPTH,
  });

  withConf({});
  expect(getDocumentLimits()).toEqual({ maxNodes: 500, maxDepth: 16 });
});

test('the limits follow what the deployment publishes in the bootstrap config', () => {
  withConf({ DASHBOARD_V2_MAX_NODES: 1200, DASHBOARD_V2_MAX_DEPTH: 8 });

  expect(getDocumentLimits()).toEqual({ maxNodes: 1200, maxDepth: 8 });
});

test('a published limit that is not a positive integer falls back to the default', () => {
  withConf({ DASHBOARD_V2_MAX_NODES: '900', DASHBOARD_V2_MAX_DEPTH: 0 });
  expect(getDocumentLimits()).toEqual({ maxNodes: 500, maxDepth: 16 });

  withConf({ DASHBOARD_V2_MAX_NODES: -5, DASHBOARD_V2_MAX_DEPTH: 3.5 });
  expect(getDocumentLimits()).toEqual({ maxNodes: 500, maxDepth: 16 });

  withConf({ DASHBOARD_V2_MAX_NODES: null, DASHBOARD_V2_MAX_DEPTH: NaN });
  expect(getDocumentLimits()).toEqual({ maxNodes: 500, maxDepth: 16 });
});

test('a published limit cannot make a walk unbounded', () => {
  withConf({
    DASHBOARD_V2_MAX_NODES: Number.MAX_SAFE_INTEGER,
    DASHBOARD_V2_MAX_DEPTH: 1_000_000,
  });

  const { maxNodes, maxDepth } = getDocumentLimits();

  expect(maxNodes).toBe(20_000);
  expect(maxDepth).toBe(64);
});

test('a bootstrap payload that cannot be read leaves the defaults in place', () => {
  bootstrap.mockImplementation(() => {
    throw new Error('no bootstrap');
  });

  expect(getDocumentLimits()).toEqual({ maxNodes: 500, maxDepth: 16 });
});

test('a document above the default node limit opens where the deployment raised it', () => {
  const large = flat(600);
  expect(() => sanitizeDocument(large, 'root')).toThrow(DocumentLimitError);

  withConf({ DASHBOARD_V2_MAX_NODES: 1000 });

  expect(Object.keys(sanitizeDocument(large, 'root').nodes)).toHaveLength(601);
});

test('a document within the default limits is refused where the deployment lowered them', () => {
  withConf({ DASHBOARD_V2_MAX_NODES: 10, DASHBOARD_V2_MAX_DEPTH: 2 });

  expect(() => sanitizeDocument(flat(10), 'root')).toThrow(/at most 10 nodes/);
  expect(() => sanitizeDocument(chain(3), 'root')).toThrow(
    /at most 2 levels deep/,
  );
  expect(sanitizeDocument(chain(2), 'root').issues).toEqual([]);
});

test('a deeper document opens where the deployment raised the depth limit', () => {
  const deep = chain(20);
  expect(() => sanitizeDocument(deep, 'root')).toThrow(DocumentLimitError);

  withConf({ DASHBOARD_V2_MAX_DEPTH: 24 });

  expect(sanitizeDocument(deep, 'root').issues).toEqual([]);
});

test('the store refuses to grow past the limits the deployment set', () => {
  withConf({ DASHBOARD_V2_MAX_NODES: 3 });
  const store = new DashboardProvider();
  store.addWidget('root', 0, { type: 'markdown' });
  store.addWidget('root', 0, { type: 'markdown' });

  expect(() => store.addWidget('root', 0, { type: 'markdown' })).toThrow(
    /at most 3 widgets/,
  );
});

test('rendering stops at the depth the deployment set', () => {
  const path = (length: number): string[] =>
    Array.from({ length }, (_, index) => `n${index}`);

  expect(isUnrenderable(path(16), 'leaf')).toBe(false);
  expect(isUnrenderable(path(17), 'leaf')).toBe(true);

  withConf({ DASHBOARD_V2_MAX_DEPTH: 4 });
  expect(isUnrenderable(path(4), 'leaf')).toBe(false);
  expect(isUnrenderable(path(5), 'leaf')).toBe(true);
  // A node already on the path is refused whatever the limit.
  expect(isUnrenderable(['root', 'a'], 'a')).toBe(true);
});

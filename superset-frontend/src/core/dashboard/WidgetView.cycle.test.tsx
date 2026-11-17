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
import { render, screen } from 'spec/helpers/testing-library';
import Outline from 'src/pages/DashboardBuilderV2/Outline';
import DashboardProvider from './DashboardProvider';
import type { DocumentNode } from './DashboardProvider';
import { MAX_DOCUMENT_DEPTH } from './documentTree';
import { registerBuiltInWidgets } from './registerBuiltInWidgets';
import WidgetView from './WidgetView';

const provider = DashboardProvider.getInstance();

beforeAll(() => {
  registerBuiltInWidgets();
});

beforeEach(() => {
  provider.reset();
});

/**
 * Puts a tree in the store without passing it through `loadDocument`.
 *
 * Loading repairs a malformed document, which is exactly what must not
 * happen here: the renderers are being shown the tree a careless writer
 * would have left, to see that they survive it.
 */
const forceNodes = (nodes: Record<string, DocumentNode>): void => {
  (provider as unknown as { nodes: Record<string, DocumentNode> }).nodes =
    nodes;
};

/** `root -> a -> b -> a`: collapsible containers that hold one another. */
const CYCLE: Record<string, DocumentNode> = {
  root: { type: 'grid', children: ['a'] },
  a: { type: 'collapsible', children: ['b'] },
  b: { type: 'collapsible', children: ['a'] },
};

test('a tree that contains itself renders each node once and then stops', () => {
  forceNodes(CYCLE);

  render(<WidgetView nodeId="root" />);

  expect(document.querySelectorAll('[data-node-id="a"]')).toHaveLength(1);
  expect(document.querySelectorAll('[data-node-id="b"]')).toHaveLength(1);
});

test('a node that is its own child renders once', () => {
  forceNodes({
    root: { type: 'grid', children: ['a'] },
    a: { type: 'collapsible', children: ['a'] },
  });

  render(<WidgetView nodeId="root" />);

  expect(document.querySelectorAll('[data-node-id="a"]')).toHaveLength(1);
});

test('nesting past the depth a document may have is not rendered', () => {
  const nodes: Record<string, DocumentNode> = {
    root: { type: 'grid', children: ['n1'] },
  };
  const depth = MAX_DOCUMENT_DEPTH + 3;
  for (let index = 1; index <= depth; index += 1) {
    nodes[`n${index}`] = {
      type: 'collapsible',
      children: index < depth ? [`n${index + 1}`] : [],
    };
  }
  forceNodes(nodes);

  render(<WidgetView nodeId="root" />);

  expect(
    document.querySelector(`[data-node-id="n${MAX_DOCUMENT_DEPTH}"]`),
  ).toBeInTheDocument();
  expect(
    document.querySelector(`[data-node-id="n${MAX_DOCUMENT_DEPTH + 1}"]`),
  ).not.toBeInTheDocument();
});

test('the outline of a tree that contains itself lists each node once', () => {
  forceNodes(CYCLE);

  render(<Outline />);

  expect(screen.getAllByTestId('outline-row-a')).toHaveLength(1);
  expect(screen.getAllByTestId('outline-row-b')).toHaveLength(1);
});

test('outline rows report how deep they sit', () => {
  forceNodes({
    root: { type: 'grid', children: ['a'] },
    a: { type: 'collapsible', children: ['b'] },
    b: { type: 'markdown' },
  });

  render(<Outline />);

  expect(screen.getByTestId('outline-row-a')).toHaveAttribute(
    'aria-level',
    '1',
  );
  expect(screen.getByTestId('outline-row-b')).toHaveAttribute(
    'aria-level',
    '2',
  );
});

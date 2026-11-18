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
  applyA2uiMessage,
  BASIC_A2UI_CATALOG_ID,
  initialA2uiState,
  parseA2uiMessage,
  updateA2uiData,
} from './index';

function create(components?: unknown) {
  return parseA2uiMessage({
    version: '1.0',
    createSurface: {
      surfaceId: 'demo',
      catalogId: BASIC_A2UI_CATALOG_ID,
      ...(components ? { components } : {}),
      dataModel: { filters: { regions: ['North', 'South'] } },
    },
  });
}

test('streams a forward reference, updates binding data and deletes a surface', () => {
  const empty = applyA2uiMessage(initialA2uiState, create());
  const root = applyA2uiMessage(
    empty,
    parseA2uiMessage({
      version: '1.0',
      updateComponents: {
        surfaceId: 'demo',
        components: [{ id: 'root', component: 'Column', children: ['title'] }],
      },
    }),
  );
  const complete = applyA2uiMessage(
    root,
    parseA2uiMessage({
      version: '1.0',
      updateComponents: {
        surfaceId: 'demo',
        components: [
          {
            id: 'title',
            component: 'Text',
            text: { '@path': '/filters/regions/0' },
          },
        ],
      },
    }),
  );
  const updated = updateA2uiData(
    complete,
    'demo',
    '/filters/regions/0',
    'West',
  );
  expect(updated.surfaces.demo.dataModel).toEqual({
    filters: { regions: ['West', 'South'] },
  });
  expect(complete.surfaces.demo.dataModel).toEqual({
    filters: { regions: ['North', 'South'] },
  });
  expect(root.surfaces.demo.components.title).toBeUndefined();
  const deleted = applyA2uiMessage(
    updated,
    parseA2uiMessage({
      version: '1.0',
      deleteSurface: { surfaceId: 'demo' },
    }),
  );
  expect(deleted.surfaces.demo).toBeUndefined();
});

test('rejects cycles before mutating the prior state', () => {
  const state = applyA2uiMessage(
    initialA2uiState,
    create([
      { id: 'root', component: 'Column', children: ['child'] },
      { id: 'child', component: 'Text', text: 'Before' },
    ]),
  );
  expect(() =>
    applyA2uiMessage(
      state,
      parseA2uiMessage({
        version: '1.0',
        updateComponents: {
          surfaceId: 'demo',
          components: [{ id: 'child', component: 'Card', child: 'root' }],
        },
      }),
    ),
  ).toThrow(/cycle/i);
  expect(state.surfaces.demo.components.child.component).toBe('Text');
});

test('rejects executable components, remote function calls, and inherited paths', () => {
  expect(() =>
    create([{ id: 'root', component: 'iframe', src: 'https://example.com' }]),
  ).toThrow();
  expect(() =>
    create([
      {
        id: 'root',
        component: 'Text',
        text: { '@call': 'openUrl', args: { url: 'https://example.com' } },
      },
    ]),
  ).toThrow();
  expect(() =>
    create([
      {
        id: 'root',
        component: 'Text',
        text: { '@path': '/__proto__/polluted' },
      },
    ]),
  ).toThrow();
  expect(() =>
    parseA2uiMessage({ version: 'v0.9', deleteSurface: { surfaceId: 'demo' } }),
  ).toThrow();
  expect(() =>
    parseA2uiMessage({
      version: '1.0',
      createSurface: { surfaceId: 'demo', sendDataModel: true },
    }),
  ).toThrow();
});

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
  componentProps,
  getA2uiCatalog,
  getComponentDefinition,
  validateComponent,
  validateMetadata,
} from './catalog';
import {
  copyA2uiJson,
  hasOwn,
  identifier,
  isObject,
  onlyKeys,
  pointerParts,
  requireValue,
  writeA2uiData,
} from './json';
import {
  A2UI_VERSION,
  BASIC_A2UI_CATALOG_ID,
  type A2uiCatalog,
  type A2uiComponent,
  type A2uiJson,
  type A2uiJsonObject,
  type A2uiMessage,
  type A2uiState,
  type A2uiSurface,
} from './types';

const operations = [
  'createSurface',
  'updateComponents',
  'updateDataModel',
  'deleteSurface',
] as const;
const maxComponents = 400;
const maxSurfaces = 32;

export const initialA2uiState: A2uiState = { surfaces: {} };

function validateComponents(
  value: A2uiJson,
  catalogId: string | undefined,
  catalogs: readonly A2uiCatalog[],
): void {
  requireValue(
    Array.isArray(value) && value.length > 0 && value.length <= maxComponents,
    'Invalid A2UI component list',
  );
  const seen = new Set<string>();
  for (const entry of value) {
    const component = validateComponent(entry, catalogId, catalogs);
    requireValue(!seen.has(component.id), 'Duplicate A2UI component ID');
    seen.add(component.id);
  }
}

/** Validate and copy an untrusted A2UI 1.0 surface message. */
export function parseA2uiMessage(
  input: unknown,
  catalogs: readonly A2uiCatalog[] = [],
): A2uiMessage {
  const message = copyA2uiJson(input);
  requireValue(
    isObject(message) && message.version === A2UI_VERSION,
    'Expected an A2UI 1.0 message',
  );
  const operation = operations.find(key => hasOwn(message, key));
  requireValue(operation, 'Unsupported A2UI operation');
  onlyKeys(message, ['version', operation]);
  const payload = message[operation];
  requireValue(
    isObject(payload) && identifier(payload.surfaceId),
    'Invalid A2UI surface identifier',
  );

  switch (operation) {
    case 'createSurface': {
      onlyKeys(payload, [
        'surfaceId',
        'catalogId',
        'components',
        'dataModel',
        'sendDataModel',
        'metadata',
      ]);
      const catalogId = hasOwn(payload, 'catalogId')
        ? payload.catalogId
        : undefined;
      requireValue(
        catalogId === undefined ||
          (identifier(catalogId) &&
            getA2uiCatalog(catalogId, catalogs) !== undefined),
        'Unsupported A2UI catalog',
      );
      requireValue(
        !hasOwn(payload, 'sendDataModel') || payload.sendDataModel === false,
        'Automatic A2UI data-model sharing is unsupported',
      );
      requireValue(
        !hasOwn(payload, 'dataModel') || isObject(payload.dataModel),
        'The A2UI data model must be an object',
      );
      if (hasOwn(payload, 'metadata')) validateMetadata(payload.metadata);
      if (hasOwn(payload, 'components')) {
        validateComponents(payload.components, catalogId, catalogs);
      }
      break;
    }
    case 'updateComponents':
      onlyKeys(payload, ['surfaceId', 'components']);
      validateComponents(payload.components, undefined, catalogs);
      break;
    case 'updateDataModel': {
      onlyKeys(payload, ['surfaceId', 'path', 'value']);
      requireValue(hasOwn(payload, 'value'), 'Missing A2UI data model value');
      if (hasOwn(payload, 'path')) {
        requireValue(
          typeof payload.path === 'string' &&
            (payload.path === '' || payload.path.startsWith('/')),
          'Expected an absolute A2UI data path',
        );
        pointerParts(payload.path);
      }
      break;
    }
    case 'deleteSurface':
      onlyKeys(payload, ['surfaceId']);
      break;
    default:
      throw new Error('Unsupported A2UI operation');
  }
  return message as unknown as A2uiMessage;
}

function replaceSurface(state: A2uiState, surface: A2uiSurface): A2uiState {
  return {
    surfaces: { ...state.surfaces, [surface.surfaceId]: surface },
  };
}

function findSurface(state: A2uiState, surfaceId: string): A2uiSurface {
  requireValue(hasOwn(state.surfaces, surfaceId), 'Unknown A2UI surface');
  return state.surfaces[surfaceId];
}

function validateGraph(
  components: Readonly<Record<string, A2uiComponent>>,
  catalogId: string | undefined,
  catalogs: readonly A2uiCatalog[],
): void {
  requireValue(
    Object.keys(components).length <= maxComponents,
    'A2UI surface has too many components',
  );
  const visiting = new Set<string>();
  const complete = new Set<string>();

  function visit(id: string, depth: number): void {
    if (!hasOwn(components, id) || complete.has(id)) return;
    requireValue(!visiting.has(id), 'A2UI component cycle');
    requireValue(depth <= 24, 'A2UI component tree is too deep');

    const component = components[id];
    const selected = getComponentDefinition(component, catalogId, catalogs);
    requireValue(selected, 'Unsupported A2UI component catalog');

    visiting.add(id);
    const children =
      selected.definition.children?.(componentProps(component)) ?? [];
    for (const child of children) {
      if (
        selected.catalog.id === BASIC_A2UI_CATALOG_ID &&
        component.component === 'Button' &&
        hasOwn(components, child)
      ) {
        const label = components[child];
        requireValue(
          getComponentDefinition(label, catalogId, catalogs)?.catalog.id ===
            BASIC_A2UI_CATALOG_ID &&
            (label.component === 'Text' || label.component === 'Icon'),
          'A2UI Button requires a Text or Icon child',
        );
      }
      visit(child, depth + 1);
    }
    visiting.delete(id);
    complete.add(id);
  }

  visit('root', 0);
  Object.keys(components).forEach(id => visit(id, 0));
}

function mergeComponents(
  current: Readonly<Record<string, A2uiComponent>>,
  incoming: readonly A2uiComponent[],
  catalogId: string | undefined,
  catalogs: readonly A2uiCatalog[],
): Readonly<Record<string, A2uiComponent>> {
  const updated = { ...current };
  for (const component of incoming) {
    const checked = validateComponent(component, catalogId, catalogs);
    updated[checked.id] = checked;
  }
  validateGraph(updated, catalogId, catalogs);
  return updated;
}

function updateData(
  state: A2uiState,
  surfaceId: string,
  path: string,
  value: A2uiJson,
): A2uiState {
  const surface = findSurface(state, surfaceId);
  const updated = writeA2uiData(surface.dataModel, path, value);
  // Bound the accumulated model as well as the incoming message.
  const dataModel = copyA2uiJson(updated) as A2uiJsonObject;
  return replaceSurface(state, { ...surface, dataModel });
}

/** Apply a surface message atomically and leave the previous state untouched. */
export function applyA2uiMessage(
  state: A2uiState,
  input: A2uiMessage,
  catalogs: readonly A2uiCatalog[] = [],
): A2uiState {
  const message = parseA2uiMessage(input, catalogs);
  if ('createSurface' in message) {
    const {
      surfaceId,
      catalogId,
      components = [],
      dataModel = {},
    } = message.createSurface;
    requireValue(!hasOwn(state.surfaces, surfaceId), 'Duplicate A2UI surface');
    requireValue(
      Object.keys(state.surfaces).length < maxSurfaces,
      'Too many A2UI surfaces',
    );
    return replaceSurface(state, {
      surfaceId,
      catalogId,
      dataModel,
      components: mergeComponents({}, components, catalogId, catalogs),
    });
  }
  if ('updateComponents' in message) {
    const surface = findSurface(state, message.updateComponents.surfaceId);
    return replaceSurface(state, {
      ...surface,
      components: mergeComponents(
        surface.components,
        message.updateComponents.components,
        surface.catalogId,
        catalogs,
      ),
    });
  }
  if ('updateDataModel' in message) {
    const { surfaceId, path = '/', value } = message.updateDataModel;
    return updateData(state, surfaceId, path, value);
  }
  const { surfaceId } = message.deleteSurface;
  findSurface(state, surfaceId);
  const surfaces = { ...state.surfaces };
  delete surfaces[surfaceId];
  return { surfaces };
}

/** Commit an explicitly edited binding to an existing surface. */
export function updateA2uiData(
  state: A2uiState,
  surfaceId: string,
  path: string,
  value: A2uiJson,
): A2uiState {
  return updateData(state, surfaceId, path, copyA2uiJson(value));
}

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
import type { A2uiJson, A2uiJsonObject } from './types';

const forbiddenKeys = new Set(['__proto__', 'prototype', 'constructor']);

export function hasOwn(value: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

export function isObject(value: unknown): value is A2uiJsonObject {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function requireValue(
  condition: unknown,
  message: string,
): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

export function onlyKeys(value: A2uiJsonObject, keys: readonly string[]): void {
  requireValue(
    Object.keys(value).every(key => keys.includes(key)),
    'Unsupported A2UI property',
  );
}

export function identifier(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= 160 &&
    !forbiddenKeys.has(value) &&
    Array.from(value).every(character => {
      const code = character.charCodeAt(0);
      return code >= 32 && code !== 127;
    })
  );
}

/** Copy only bounded, inert JSON values from a transport or an input. */
export function copyA2uiJson(value: unknown): A2uiJson {
  let remaining = 20_000;
  let remainingText = 500_000;

  function copy(input: unknown, depth: number): A2uiJson {
    remaining -= 1;
    requireValue(remaining >= 0 && depth <= 32, 'A2UI payload is too large');
    if (input === null || typeof input === 'boolean') {
      return input;
    }
    if (typeof input === 'string') {
      remainingText -= input.length;
      requireValue(
        input.length <= 16_000 && remainingText >= 0,
        'A2UI text is too large',
      );
      return input;
    }
    if (typeof input === 'number') {
      requireValue(Number.isFinite(input), 'Invalid A2UI number');
      return input;
    }
    if (Array.isArray(input)) {
      requireValue(input.length <= 1_000, 'A2UI array is too large');
      return Array.from(input, entry => copy(entry, depth + 1));
    }
    requireValue(isObject(input), 'Expected an A2UI JSON value');
    const result: A2uiJsonObject = {};
    const descriptors = Object.getOwnPropertyDescriptors(input);
    for (const [key, descriptor] of Object.entries(descriptors)) {
      requireValue(
        key.length <= 256 && !forbiddenKeys.has(key) && 'value' in descriptor,
        'Invalid A2UI object key',
      );
      result[key] = copy(descriptor.value, depth + 1);
    }
    return result;
  }

  return copy(value, 0);
}

/** Resolve absolute JSON Pointers or template-relative paths into model keys. */
export function pointerParts(
  pointer: string,
  scope: readonly string[] = [],
): readonly string[] {
  requireValue(pointer.length <= 512, 'A2UI data path is too long');
  if (pointer === '/') return [];
  if (pointer === '') return scope;
  const absolute = pointer.startsWith('/');
  const pieces = (absolute ? pointer.slice(1) : pointer).split('/');
  requireValue(pieces.length <= 24, 'A2UI data path is too deep');
  const decoded = pieces.map(part => {
    requireValue(!/~(?![01])/u.test(part), 'Invalid A2UI JSON Pointer escape');
    const name = part.replace(/~1/g, '/').replace(/~0/g, '~');
    requireValue(!forbiddenKeys.has(name), 'Unsafe A2UI data path');
    return name;
  });
  return absolute ? decoded : [...scope, ...decoded];
}

export function encodePointer(parts: readonly string[]): string {
  return `/${parts.map(part => part.replace(/~/g, '~0').replace(/\//g, '~1')).join('/')}`;
}

function indexOf(part: string): number {
  return /^(?:0|[1-9]\d*)$/u.test(part) ? Number(part) : -1;
}

export function readA2uiData(
  model: A2uiJsonObject,
  parts: readonly string[],
): A2uiJson | undefined {
  let current: A2uiJson | undefined = model;
  for (const key of parts) {
    if (Array.isArray(current)) {
      current = current[indexOf(key)];
    } else if (isObject(current) && hasOwn(current, key)) {
      current = current[key];
    } else {
      return undefined;
    }
  }
  return current;
}

function setValue(
  model: A2uiJson | undefined,
  keys: readonly string[],
  value: A2uiJson,
): A2uiJson {
  if (keys.length === 0) return value;
  const [key, ...path] = keys;
  if (Array.isArray(model)) {
    const index = indexOf(key);
    requireValue(
      index >= 0 && index <= model.length && index < 1_000,
      'Invalid A2UI array index',
    );
    if (value === null && index === model.length) return model;
    const updated = [...model];
    if (value === null && path.length === 0) {
      updated.splice(index, 1);
    } else {
      updated[index] = setValue(model[index], path, value);
    }
    return updated;
  }
  const object = isObject(model) ? model : {};
  if (value === null && !hasOwn(object, key)) return object;
  const updated = { ...object };
  if (value === null && path.length === 0) {
    delete updated[key];
  } else {
    updated[key] = setValue(
      hasOwn(object, key) ? object[key] : undefined,
      path,
      value,
    );
  }
  return updated;
}

export function writeA2uiData(
  model: A2uiJsonObject,
  path: string,
  value: A2uiJson,
): A2uiJsonObject {
  requireValue(
    path === '' || path.startsWith('/'),
    'Expected an absolute A2UI data path',
  );
  const keys = pointerParts(path);
  const result = setValue(model, keys, value) ?? {};
  requireValue(isObject(result), 'The A2UI data model root must be an object');
  return result;
}

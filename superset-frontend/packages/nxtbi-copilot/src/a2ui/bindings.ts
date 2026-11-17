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
import { hasOwn, isObject, pointerParts, readA2uiData } from './json';
import type { A2uiJson, A2uiJsonObject } from './types';

export interface A2uiEvaluation {
  dataModel: A2uiJsonObject;
  path: readonly string[];
  locale?: string;
  index?: number;
}

export function displayValue(value: A2uiJson | undefined): string {
  return typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
    ? String(value)
    : '';
}

export function asBoolean(value: A2uiJson | undefined): boolean {
  if (isObject(value) && typeof value.valid === 'boolean') return value.valid;
  return Boolean(value);
}

function asNumber(value: A2uiJson | undefined): number | undefined {
  if (typeof value === 'number') return value;
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function inRange(value: number | undefined, args: A2uiJsonObject): boolean {
  if (value === undefined) return false;
  const min = asNumber(args.min);
  const max = asNumber(args.max);
  return (
    (min === undefined || value >= min) && (max === undefined || value <= max)
  );
}

function formatNumber(
  args: A2uiJsonObject,
  locale: string | undefined,
  currency?: string,
): string {
  const value = asNumber(args.value);
  if (value === undefined) return '';
  const decimals = asNumber(args.decimals);
  const precision =
    decimals === undefined
      ? {}
      : {
          minimumFractionDigits: Math.max(
            0,
            Math.min(12, Math.trunc(decimals)),
          ),
          maximumFractionDigits: Math.max(
            0,
            Math.min(12, Math.trunc(decimals)),
          ),
        };
  try {
    return new Intl.NumberFormat(locale, {
      ...precision,
      useGrouping: args.grouping !== false,
      ...(currency && /^[a-z]{3}$/iu.test(currency)
        ? { style: 'currency', currency }
        : {}),
    }).format(value);
  } catch {
    return String(value);
  }
}

/** Evaluate only the pure renderer functions advertised in the local catalog. */
function evaluateFunction(
  name: string,
  args: A2uiJsonObject,
  scope: A2uiEvaluation,
): A2uiJson {
  const { value } = args;
  switch (name) {
    case 'required':
      return (
        value !== undefined &&
        value !== null &&
        (typeof value !== 'string' || value.trim().length > 0) &&
        (!Array.isArray(value) || value.length > 0)
      );
    case 'length':
      return (
        typeof value === 'string' && inRange(Array.from(value).length, args)
      );
    case 'numeric':
      return inRange(asNumber(value), args);
    case 'email':
      return (
        typeof value === 'string' &&
        value.length <= 320 &&
        /^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(value)
      );
    case 'formatString':
      return displayValue(value);
    case 'formatNumber':
      return formatNumber(args, scope.locale);
    case 'formatCurrency':
      return formatNumber(args, scope.locale, displayValue(args.currency));
    case 'pluralize': {
      const number = asNumber(value);
      if (number === undefined) return displayValue(args.other);
      try {
        const category = new Intl.PluralRules(scope.locale).select(number);
        return displayValue(
          hasOwn(args, category) ? args[category] : args.other,
        );
      } catch {
        return displayValue(args.other);
      }
    }
    case 'and':
    case 'or':
      return (
        Array.isArray(args.values) &&
        (name === 'and'
          ? args.values.every(asBoolean)
          : args.values.some(asBoolean))
      );
    case 'not':
      return !asBoolean(value);
    case '@index':
      return scope.index === undefined
        ? null
        : scope.index + (asNumber(args.offset) ?? 0);
    default:
      return null;
  }
}

export function resolveA2uiValue(
  value: A2uiJson | undefined,
  scope: A2uiEvaluation,
): A2uiJson {
  if (Array.isArray(value)) {
    return value.map(item => resolveA2uiValue(item, scope));
  }
  if (!isObject(value)) return value ?? null;
  if (typeof value['@path'] === 'string') {
    return (
      readA2uiData(scope.dataModel, pointerParts(value['@path'], scope.path)) ??
      null
    );
  }
  if (typeof value['@call'] === 'string') {
    const args = isObject(value.args)
      ? resolveA2uiValue(value.args, scope)
      : {};
    return evaluateFunction(value['@call'], isObject(args) ? args : {}, scope);
  }
  return Object.fromEntries(
    Object.entries(value).map(([name, item]) => [
      name,
      resolveA2uiValue(item, scope),
    ]),
  );
}

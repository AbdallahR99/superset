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
import { sanitizeHtml } from '@superset-ui/core';

/**
 * @fileoverview Keeps an authored ECharts option from running script.
 *
 * A widget's `echartsOptions` is data: written by whoever defined the widget,
 * drawn in the page of whoever looks at it — another Superset user, or a host
 * application's visitor. Almost all of an option paints onto a canvas, where
 * text is only ever text. Two places reach the DOM instead:
 *
 * - a `tooltip`'s string `formatter` is a template ECharts fills and assigns
 *   as HTML (it encodes the values it substitutes, but not the template);
 * - `link` / `sublink` on a title is opened when the title is clicked.
 *
 * Both are cleaned here, wherever in the option they sit, after `$bind`
 * markers are resolved so a bound value cannot put back what was removed.
 */

const MAX_DEPTH = 64;
const LINK_KEYS = new Set(['link', 'sublink']);
// Matched after dropping what a URL parser ignores inside a scheme.
const SAFE_LINK = /^(https?:|mailto:|\/|#|\.{0,2}\/|[^:]*$)/i;

function isSafeLink(link: string): boolean {
  // eslint-disable-next-line no-control-regex
  return SAFE_LINK.test(link.replace(/[\u0000- ]/g, ''));
}

const isPlainObject = (value: unknown): value is Record<string, unknown> => {
  if (value === null || typeof value !== 'object') return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
};

/**
 * A cleaned copy of `value`. Only plain objects and arrays are entered:
 * anything else (a gradient instance, a function a host passed in code) is
 * not something JSON can author and is kept as it is. `inTooltip` is true for
 * the direct members of a `tooltip` object.
 */
function clean(
  value: unknown,
  depth: number,
  ancestors: Set<object>,
  inTooltip: boolean,
): unknown {
  const isArray = Array.isArray(value);
  if (!isArray && !isPlainObject(value)) return value;
  const container = value as object;
  // Past the cap, or back at an ancestor: nothing below is passed on.
  if (depth > MAX_DEPTH || ancestors.has(container)) return undefined;
  ancestors.add(container);
  try {
    if (isArray) {
      // A `tooltip` may be an array of tooltip objects.
      return (value as unknown[]).map(item =>
        clean(item, depth + 1, ancestors, inTooltip),
      );
    }
    const copy: Record<string, unknown> = {};
    Object.entries(value as Record<string, unknown>).forEach(([key, child]) => {
      if (LINK_KEYS.has(key) && typeof child === 'string') {
        if (isSafeLink(child)) copy[key] = child;
        return;
      }
      if (inTooltip && key === 'formatter' && typeof child === 'string') {
        copy[key] = sanitizeHtml(child);
        return;
      }
      copy[key] = clean(child, depth + 1, ancestors, key === 'tooltip');
    });
    return copy;
  } finally {
    ancestors.delete(container);
  }
}

/**
 * A copy of `option` with every script-capable value cleaned. The option
 * passed in is left untouched: it may be the author's own (frozen) object.
 */
export function sanitizeEchartsOption<T extends Record<string, unknown>>(
  option: T,
): T {
  return clean(option, 0, new Set(), false) as T;
}

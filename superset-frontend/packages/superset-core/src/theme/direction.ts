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
import createCache, { EmotionCache } from '@emotion/cache';
import { useTheme as useEmotionTheme } from '@emotion/react';
import rtlPlugin from '@mui/stylis-plugin-rtl';
import { prefixer } from 'stylis';

/**
 * Text direction of the user interface.
 *
 * Direction is a property of the active locale, not of a theme: it is decided
 * by the server for the page load (`<html dir>`), read once at the root theme
 * provider and handed down through the Emotion theme as `theme.direction`, so
 * nested providers, portals, extensions and embedded surfaces all inherit it.
 */
export type Direction = 'ltr' | 'rtl';

/**
 * Languages written right-to-left, matched on the base language subtag.
 * The server derives direction from CLDR; this list is the client-side
 * fallback for contexts without a server-rendered `<html dir>` (unit tests,
 * Storybook, hosts that mount a provider on their own page).
 */
export const RTL_LANGUAGES: readonly string[] = [
  'ar',
  'ckb',
  'dv',
  'fa',
  'he',
  'iw',
  'ps',
  'sd',
  'ug',
  'ur',
  'yi',
];

/**
 * Direction for a locale code. Accepts both `ar_SA` and `ar-SA` forms.
 */
export function getDirectionForLocale(locale?: string | null): Direction {
  const language = (locale ?? '').trim().toLowerCase().split(/[-_]/)[0];
  return RTL_LANGUAGES.includes(language) ? 'rtl' : 'ltr';
}

/**
 * Direction declared by the document. The DOM attribute is the client-side
 * source of truth because module state can be instantiated more than once
 * across bundles, while there is only one document.
 */
export function getDocumentDirection(): Direction {
  if (typeof document === 'undefined') {
    return 'ltr';
  }
  return document.documentElement.getAttribute('dir') === 'rtl' ? 'rtl' : 'ltr';
}

/**
 * Direction in effect for the calling component: the nearest theme provider
 * (or `LtrIsolate`) wins, the document is the fallback.
 */
export function useDirection(): Direction {
  const theme = useEmotionTheme() as { direction?: Direction };
  return theme?.direction ?? getDocumentDirection();
}

/**
 * `true` when the calling component renders right-to-left.
 */
export function useIsRtl(): boolean {
  return useDirection() === 'rtl';
}

const CACHE_REGISTRY = Symbol.for('superset.theme.emotionCaches');

type CacheRegistry = Partial<Record<Direction, EmotionCache>>;

/**
 * The Emotion cache for a direction. There is exactly one cache per direction
 * for the whole page: every theme provider, nested dashboard theme and LTR
 * island shares it, so switching themes never leaves stale style containers
 * behind and two caches never fight over one key.
 *
 * The right-to-left cache mirrors physical CSS (`margin-left`, `left`,
 * `text-align: left`, four-value shorthands, ...) with a stylis plugin, which
 * is why it needs its own key: a class name is a hash of the unmirrored
 * source, and one name must not map to two different rule bodies.
 */
export function getEmotionCache(direction: Direction): EmotionCache {
  const holder = globalThis as unknown as Record<symbol, CacheRegistry>;
  if (!holder[CACHE_REGISTRY]) {
    holder[CACHE_REGISTRY] = {};
  }
  const registry = holder[CACHE_REGISTRY];
  let cache = registry[direction];
  if (!cache) {
    cache =
      direction === 'rtl'
        ? createCache({
            key: 'superset-rtl',
            // Passing stylisPlugins replaces Emotion's defaults, so the vendor
            // prefixer has to be listed explicitly.
            stylisPlugins: [prefixer, rtlPlugin],
          })
        : createCache({ key: 'superset' });
    registry[direction] = cache;
  }
  return cache;
}

/**
 * Marker that keeps the next declaration physical in right-to-left layouts.
 * Interpolate it so that no build step can strip the comment:
 *
 *   css`
 *     ${noFlip} left: 0;
 *   `
 *
 * Use it only for values that are physical by nature (a pixel offset measured
 * in JavaScript, a progress bar anchored to the left). To keep a whole subtree
 * left-to-right (code, SQL, chart canvases) use `LtrIsolate`. Never force a
 * direction with the CSS `direction` property inside a styled block: the
 * mirroring step rewrites `direction: ltr` to `direction: rtl`.
 */
export const noFlip = '/* @noflip */';

const PLACEMENT_SWAP: Record<string, string> = {
  left: 'right',
  right: 'left',
  Left: 'Right',
  Right: 'Left',
};

/**
 * Mirrors an explicit Ant Design placement (`bottomLeft`, `rightTop`, `left`,
 * ...) for right-to-left layouts. Ant Design mirrors its default placements
 * on its own but leaves explicit ones physical.
 */
export function flipPlacement<T extends string | undefined>(
  placement: T,
  direction: Direction,
): T {
  if (!placement || direction !== 'rtl') {
    return placement;
  }
  return placement.replace(
    /left|right|Left|Right/g,
    match => PLACEMENT_SWAP[match],
  ) as T;
}

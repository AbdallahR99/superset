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
import { createElement, useMemo } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { ConfigProvider } from 'antd';
import {
  CacheProvider as EmotionCacheProvider,
  ThemeProvider,
  useTheme as useEmotionTheme,
} from '@emotion/react';
import { getDocumentDirection, getEmotionCache } from './direction';
import type { Direction } from './direction';

/**
 * Sets the direction of a React subtree without rendering an element: styled
 * components below it are (or are not) mirrored accordingly, Ant Design
 * components follow, and `theme.direction` / `useDirection()` report it.
 *
 * The caller is responsible for putting the matching `dir` attribute on the
 * DOM element that bounds the subtree; use `LtrIsolate` when a wrapper element
 * is acceptable. When the subtree already has the requested direction this is
 * a pass-through.
 */
export function DirectionProvider({
  direction,
  children,
}: {
  direction: Direction;
  children?: ReactNode;
}) {
  const parentTheme = useEmotionTheme() as { direction?: Direction };
  const theme = useMemo(
    () => ({ ...parentTheme, direction }),
    [parentTheme, direction],
  );
  if ((parentTheme?.direction ?? getDocumentDirection()) === direction) {
    return <>{children}</>;
  }
  return (
    <EmotionCacheProvider value={getEmotionCache(direction)}>
      <ThemeProvider theme={theme}>
        <ConfigProvider direction={direction}>{children}</ConfigProvider>
      </ThemeProvider>
    </EmotionCacheProvider>
  );
}

export interface DirectionIsolateProps extends HTMLAttributes<HTMLElement> {
  /** Element rendered as the boundary. Use `bdi` or `span` for inline content. */
  as?: keyof JSX.IntrinsicElements;
  children?: ReactNode;
}

/**
 * Keeps a subtree left-to-right inside a right-to-left interface.
 *
 * Use it for content whose reading order is not a matter of locale: code and
 * SQL editors, query text, identifiers, URLs, and chart plot areas (axis
 * semantics must not be mirrored). Inside the boundary the `dir` attribute is
 * `ltr`, styled components are not mirrored, Ant Design components render
 * left-to-right and `theme.direction` is `'ltr'`.
 *
 * Popups rendered into `document.body` from inside the boundary keep this
 * React context but inherit the page direction from the DOM; give them a
 * `getPopupContainer` inside the boundary when that matters.
 */
export function LtrIsolate({
  as = 'div',
  children,
  ...rest
}: DirectionIsolateProps) {
  return (
    <DirectionProvider direction="ltr">
      {createElement(as, { dir: 'ltr', ...rest }, children)}
    </DirectionProvider>
  );
}

/**
 * Restores a direction below an `LtrIsolate`, for the parts of an isolated
 * region that are ordinary interface (for example the controls a chart
 * renders next to its canvas).
 */
export function DirectionRestore({
  direction,
  as = 'div',
  children,
  ...rest
}: DirectionIsolateProps & { direction: Direction }) {
  return (
    <DirectionProvider direction={direction}>
      {createElement(as, { dir: direction, ...rest }, children)}
    </DirectionProvider>
  );
}

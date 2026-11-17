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
import { act, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { Button } from 'antd';
import styled from '@emotion/styled';
import { css } from '@emotion/react';
import { Theme } from './Theme';
import {
  flipPlacement,
  getDirectionForLocale,
  getDocumentDirection,
  getEmotionCache,
  noFlip,
  useDirection,
} from './direction';
import { DirectionProvider, DirectionRestore, LtrIsolate } from './LtrIsolate';

const Box = styled.div`
  margin-left: 4px;
  padding: 1px 2px 3px 4px;
  text-align: left;
  margin-inline-start: 7px;
  user-select: none;
`;

const Pinned = styled.div`
  ${noFlip} left: 12px;
  margin-right: 3px;
`;

const DirectionProbe = ({ id }: { id: string }) => (
  <span data-test={id}>{useDirection()}</span>
);

const renderWith = (
  ui: React.ReactNode,
  direction?: 'ltr' | 'rtl',
  theme = Theme.fromConfig(),
) =>
  render(
    <theme.SupersetThemeProvider direction={direction}>
      {ui}
    </theme.SupersetThemeProvider>,
  );

afterEach(() => {
  document.documentElement.removeAttribute('dir');
});

test.each([
  ['ar', 'rtl'],
  ['ar_SA', 'rtl'],
  ['ar-EG', 'rtl'],
  ['AR', 'rtl'],
  ['fa', 'rtl'],
  ['he', 'rtl'],
  ['ur', 'rtl'],
  ['en', 'ltr'],
  ['zh_TW', 'ltr'],
  ['sr_Latn', 'ltr'],
  ['pt-BR', 'ltr'],
  ['', 'ltr'],
  [undefined, 'ltr'],
  [null, 'ltr'],
])('getDirectionForLocale(%p) is %s', (locale, expected) => {
  expect(getDirectionForLocale(locale)).toBe(expected);
});

test('getDocumentDirection follows the html dir attribute', () => {
  expect(getDocumentDirection()).toBe('ltr');
  document.documentElement.setAttribute('dir', 'rtl');
  expect(getDocumentDirection()).toBe('rtl');
  document.documentElement.setAttribute('dir', 'ltr');
  expect(getDocumentDirection()).toBe('ltr');
  document.documentElement.setAttribute('dir', 'auto');
  expect(getDocumentDirection()).toBe('ltr');
});

test('flipPlacement mirrors explicit placements only in rtl', () => {
  expect(flipPlacement('bottomLeft', 'ltr')).toBe('bottomLeft');
  expect(flipPlacement('bottomLeft', 'rtl')).toBe('bottomRight');
  expect(flipPlacement('rightTop', 'rtl')).toBe('leftTop');
  expect(flipPlacement('left', 'rtl')).toBe('right');
  expect(flipPlacement('top', 'rtl')).toBe('top');
  expect(flipPlacement(undefined, 'rtl')).toBeUndefined();
});

test('there is one stable Emotion cache per direction with distinct keys', () => {
  const ltr = getEmotionCache('ltr');
  const rtl = getEmotionCache('rtl');
  expect(getEmotionCache('ltr')).toBe(ltr);
  expect(getEmotionCache('rtl')).toBe(rtl);
  expect(ltr.key).toBe('superset');
  expect(rtl.key).toBe('superset-rtl');
});

test('left-to-right output is unchanged', () => {
  renderWith(<Box data-test="box" />, 'ltr');
  const box = screen.getByTestId('box');
  expect(box).toHaveStyleRule('margin-left', '4px');
  expect(box).toHaveStyleRule('padding', '1px 2px 3px 4px');
  expect(box).toHaveStyleRule('text-align', 'left');
});

test('right-to-left mirrors physical CSS and leaves logical properties alone', () => {
  renderWith(<Box data-test="box" />, 'rtl');
  const box = screen.getByTestId('box');
  expect(box).toHaveStyleRule('margin-right', '4px');
  expect(box).not.toHaveStyleRule('margin-left', '4px');
  expect(box).toHaveStyleRule('padding', '1px 4px 3px 2px');
  expect(box).toHaveStyleRule('text-align', 'right');
  expect(box).toHaveStyleRule('margin-inline-start', '7px');
});

test('the right-to-left cache keeps vendor prefixing', () => {
  renderWith(<Box data-test="box" />, 'rtl');
  const rules = Array.from(document.querySelectorAll('style'))
    .map(node => node.textContent ?? '')
    .concat(
      Array.from(document.styleSheets).flatMap(sheet =>
        Array.from(sheet.cssRules).map(rule => rule.cssText),
      ),
    )
    .join('\n');
  expect(rules).toMatch(/-webkit-user-select:\s*none/);
});

test('noFlip keeps a declaration physical in right-to-left', () => {
  renderWith(<Pinned data-test="pinned" />, 'rtl');
  const pinned = screen.getByTestId('pinned');
  expect(pinned).toHaveStyleRule('left', '12px');
  expect(pinned).toHaveStyleRule('margin-left', '3px');
});

test('the provider reads the document direction and tells Ant Design', () => {
  document.documentElement.setAttribute('dir', 'rtl');
  renderWith(
    <>
      <Button>go</Button>
      <DirectionProbe id="probe" />
    </>,
  );
  expect(screen.getByRole('button')).toHaveClass('ant-btn-rtl');
  expect(screen.getByTestId('probe')).toHaveTextContent('rtl');
});

test('a nested theme inherits direction and shares the cache', () => {
  const outer = Theme.fromConfig();
  const inner = Theme.fromConfig({ token: { colorPrimary: '#0f766e' } });
  render(
    <outer.SupersetThemeProvider direction="rtl">
      <inner.SupersetThemeProvider>
        <Box data-test="box" />
        <DirectionProbe id="probe" />
      </inner.SupersetThemeProvider>
    </outer.SupersetThemeProvider>,
  );
  expect(screen.getByTestId('probe')).toHaveTextContent('rtl');
  expect(screen.getByTestId('box')).toHaveStyleRule('margin-right', '4px');
  expect(screen.getByTestId('box').className).toMatch(/^superset-rtl-/);
});

test('theme updates reuse the cache instead of adding style containers', () => {
  const theme = Theme.fromConfig();
  renderWith(<Box data-test="box" />, 'rtl', theme);
  const cache = getEmotionCache('rtl');
  const containers = () =>
    document.querySelectorAll('style[data-emotion^="superset"]').length;
  const before = containers();
  act(() => {
    theme.setConfig({ token: { colorPrimary: '#111111' } });
    theme.setConfig({ token: { colorPrimary: '#222222' } });
    theme.setConfig({ token: { colorPrimary: '#333333' } });
  });
  expect(getEmotionCache('rtl')).toBe(cache);
  expect(containers()).toBeLessThanOrEqual(before + 1);
});

test('a theme cannot set the direction', () => {
  const theme = Theme.fromConfig({
    token: { direction: 'rtl' } as Record<string, unknown>,
  });
  expect((theme.theme as { direction?: string }).direction).toBeUndefined();
  expect(JSON.stringify(theme.toSerializedConfig())).not.toContain('direction');
  renderWith(<DirectionProbe id="probe" />, undefined, theme);
  expect(screen.getByTestId('probe')).toHaveTextContent('ltr');
});

test('LtrIsolate keeps a subtree left-to-right inside a right-to-left page', () => {
  renderWith(
    <>
      <Button>outer</Button>
      <LtrIsolate data-test="island">
        <Box data-test="box" />
        <Button>inner</Button>
        <DirectionProbe id="probe" />
        <DirectionRestore direction="rtl" data-test="restored">
          <Box data-test="restored-box" />
        </DirectionRestore>
      </LtrIsolate>
    </>,
    'rtl',
  );
  expect(screen.getByTestId('island')).toHaveAttribute('dir', 'ltr');
  expect(screen.getByTestId('box')).toHaveStyleRule('margin-left', '4px');
  expect(screen.getByTestId('probe')).toHaveTextContent('ltr');
  expect(screen.getByRole('button', { name: 'outer' })).toHaveClass(
    'ant-btn-rtl',
  );
  expect(screen.getByRole('button', { name: 'inner' })).not.toHaveClass(
    'ant-btn-rtl',
  );
  expect(screen.getByTestId('restored')).toHaveAttribute('dir', 'rtl');
  expect(screen.getByTestId('restored-box')).toHaveStyleRule(
    'margin-right',
    '4px',
  );
});

test('LtrIsolate is only an attribute in a left-to-right page', () => {
  renderWith(
    <LtrIsolate as="span" data-test="island">
      <Box data-test="box" />
    </LtrIsolate>,
    'ltr',
  );
  const island = screen.getByTestId('island');
  expect(island.tagName).toBe('SPAN');
  expect(island).toHaveAttribute('dir', 'ltr');
  expect(screen.getByTestId('box').className).toMatch(/^superset-(?!rtl)/);
});

test('DirectionProvider renders no element of its own', () => {
  const { container } = renderWith(
    <DirectionProvider direction="ltr">
      <i data-test="leaf" className={css``.name} />
    </DirectionProvider>,
    'rtl',
  );
  expect(screen.getByTestId('leaf').parentElement).toBe(container);
});

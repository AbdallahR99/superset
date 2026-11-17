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
import { render, screen, within } from 'spec/helpers/testing-library';
import type { Direction } from '@apache-superset/core/theme';
import DashboardProvider from './DashboardProvider';
import { registerBuiltInWidgets } from './registerBuiltInWidgets';
import { widgetHeaderControl } from './widgetHeaderControl';

const provider = DashboardProvider.getInstance();

const MIRRORED = { transform: 'scaleX(-1)' };

beforeAll(() => {
  registerBuiltInWidgets();
});

beforeEach(() => {
  provider.reset();
});

/** A collapsible widget's header toggle, drawn in `direction`. */
const mountToggle = (collapsed: boolean, direction: Direction): HTMLElement => {
  const id = provider.addWidget('root', 0, {
    type: 'collapsible',
    props: { collapsed },
  });
  render(<>{widgetHeaderControl('collapsible', id)}</>, { direction });
  return within(screen.getByTestId(`widget-collapse-toggle-${id}`)).getByRole(
    'img',
  );
};

test('left-to-right, a collapsed widget’s caret points right, unmirrored', () => {
  expect(mountToggle(true, 'ltr')).not.toHaveStyle(MIRRORED);
});

test('right-to-left, a collapsed widget’s caret points the way the text reads', () => {
  expect(mountToggle(true, 'rtl')).toHaveStyle(MIRRORED);
});

test('an expanded widget’s caret points down in either direction', () => {
  expect(mountToggle(false, 'rtl')).not.toHaveStyle(MIRRORED);
});

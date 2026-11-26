/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import { render, screen } from 'spec/helpers/testing-library';
import DashboardProvider from './DashboardProvider';
import { registerBuiltInWidgets } from './registerBuiltInWidgets';
import { DashboardViewModeContext } from './viewMode';
import WidgetView from './WidgetView';

const provider = DashboardProvider.getInstance();

beforeAll(registerBuiltInWidgets);
beforeEach(() => provider.reset());

test.each(['ltr', 'rtl'] as const)(
  'the %s reader follows logical grid position without writing the document',
  direction => {
    const root = provider.getRoot().id;
    provider.updateLayout(root, { rowUnit: 40, gap: 8 });
    const laterRow = provider.addWidget(root, 0, {
      type: 'markdown',
      layout: { col: 1, row: 4, colSpan: 24, rowSpan: 1 },
    });
    const inlineEnd = provider.addWidget(root, 1, {
      type: 'markdown',
      layout: { col: 13, row: 1, colSpan: 12, rowSpan: 3 },
    });
    const inlineStart = provider.addWidget(root, 2, {
      type: 'markdown',
      layout: { col: 1, row: 1, colSpan: 12, rowSpan: 3 },
    });
    const original = provider.getDocument();
    const version = provider.getDocumentVersion();

    render(
      <DashboardViewModeContext.Provider value="view">
        <WidgetView nodeId={root} />
      </DashboardViewModeContext.Provider>,
      { direction },
    );

    const cards = Array.from(screen.getByTestId('static-grid').children);
    expect(cards.map(card => card.getAttribute('data-node-id'))).toEqual([
      inlineStart,
      inlineEnd,
      laterRow,
    ]);
    const second = cards[1] as HTMLElement;
    expect(second.style.getPropertyValue('--dashboard-grid-column')).toBe(
      '13 / span 12',
    );
    expect(second.style.getPropertyValue('--dashboard-grid-row')).toBe(
      '1 / span 3',
    );
    expect(second.style.getPropertyValue('--dashboard-grid-block-size')).toBe(
      '136px',
    );
    expect(provider.getDocument()).toEqual(original);
    expect(provider.getDocumentVersion()).toBe(version);
  },
);

test('compact rows pair adjacent metric tiles and leave isolated tiles full width', () => {
  const root = provider.getRoot().id;
  const first = provider.addWidget(root, 0, {
    type: 'metric-tile',
    props: { label: 'Repeated title' },
  });
  const second = provider.addWidget(root, 1, { type: 'metric-tile' });
  const third = provider.addWidget(root, 2, { type: 'metric-tile' });
  provider.addWidget(root, 3, { type: 'markdown' });
  const fourth = provider.addWidget(root, 4, { type: 'metric-tile' });

  render(
    <DashboardViewModeContext.Provider value="view">
      <WidgetView nodeId={root} />
    </DashboardViewModeContext.Provider>,
  );

  const cards = Array.from(screen.getByTestId('static-grid').children);
  expect(
    cards
      .filter(card => card.hasAttribute('data-dashboard-paired-tile'))
      .map(card => card.getAttribute('data-node-id')),
  ).toEqual([first, second]);
  expect(screen.getByTestId(`widget-content-${first}`)).toHaveAttribute(
    'data-dashboard-duplicate-metric-label',
  );
  for (const id of [second, third, fourth]) {
    expect(screen.getByTestId(`widget-content-${id}`)).not.toHaveAttribute(
      'data-dashboard-duplicate-metric-label',
    );
  }
});

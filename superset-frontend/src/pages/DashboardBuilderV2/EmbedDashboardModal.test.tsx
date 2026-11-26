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
import fetchMock from 'fetch-mock';
import userEvent from '@testing-library/user-event';
import { FeatureFlag, isFeatureEnabled } from '@superset-ui/core';
import { render, screen } from 'spec/helpers/testing-library';
import DashboardProvider from 'src/core/dashboard/DashboardProvider';
import { EMBED_WIDGET_ID_PROP } from 'src/core/dashboard/EmbedWidgetModal';
import { dashboardSession } from 'src/core/dashboard/session';
import { registerBuiltInWidgets } from 'src/core/dashboard/registerBuiltInWidgets';
import DashboardHeader from './DashboardHeader';
import EmbedDashboardModal, {
  buildEmbedSnippet,
  listEmbeddableWidgets,
} from './EmbedDashboardModal';

jest.mock('@superset-ui/core', () => ({
  ...jest.requireActual('@superset-ui/core'),
  isFeatureEnabled: jest.fn(),
}));

const mockIsFeatureEnabled = isFeatureEnabled as jest.MockedFunction<
  typeof isFeatureEnabled
>;

// The page registers the built-in widget types (see its own module); a test
// that renders a part of the page without the page does it itself.
registerBuiltInWidgets();

const provider = DashboardProvider.getInstance();

const ADMIN = { userId: 1, firstName: 'Admin', lastName: 'User' };

const enable = (...flags: FeatureFlag[]): void => {
  mockIsFeatureEnabled.mockImplementation(flag => flags.includes(flag));
};

const renderHeader = () =>
  render(<DashboardHeader />, {
    useRedux: true,
    initialState: { user: ADMIN },
  });

beforeEach(() => {
  provider.reset();
  dashboardSession.reset();
  mockIsFeatureEnabled.mockReset();
  enable(FeatureFlag.EmbeddedSuperset);
  fetchMock.clearHistory().removeRoutes();
});

afterEach(() => {
  fetchMock.clearHistory().removeRoutes();
});

const addSaved = (content: string, savedId?: string): string =>
  provider.addWidget(provider.getRoot().id, 0, {
    type: 'markdown',
    props: {
      content,
      ...(savedId === undefined ? {} : { [EMBED_WIDGET_ID_PROP]: savedId }),
    },
  });

test('the embeddable widgets are the leaves, at any depth, and not the containers', () => {
  const root = provider.getRoot().id;
  const top = addSaved('top', 'uuid-top');
  const tabs = provider.addWidget(root, 1, { type: 'collapsible' });
  const nested = provider.addWidget(tabs, 0, {
    type: 'markdown',
    props: { content: 'nested' },
  });
  provider.addWidget(root, 2, { type: 'not-a-registered-type' });

  expect(listEmbeddableWidgets()).toEqual([
    expect.objectContaining({ nodeId: top, savedId: 'uuid-top' }),
    expect.objectContaining({ nodeId: nested, savedId: undefined }),
  ]);
});

test('the snippet renders each saved widget by id and names each one in the guest token', () => {
  const snippet = buildEmbedSnippet('https://bi.example.com', ['a', 'b']);

  expect(snippet).toContain("from '@apache-superset/widgets'");
  expect(snippet).toContain('supersetDomain="https://bi.example.com"');
  expect(snippet).toContain('<Widget id="a" />');
  expect(snippet).toContain('<Widget id="b" />');
  expect(snippet).toContain('{ type: "widget", id: "a" }');
  expect(snippet).toContain('{ type: "widget", id: "b" }');
  // A v2 dashboard is not embedded as a framed classic dashboard.
  expect(snippet).not.toContain('type: "dashboard"');
  expect(snippet).not.toContain('/embedded/');
});

test('the combined embed uses the Superset session when a saved widget has a semantic view', () => {
  addSaved('Dataset content', 'dataset-widget');
  provider.addWidget(provider.getRoot().id, 1, {
    type: 'metric-tile',
    props: {
      label: 'Market',
      dataBinding: {
        semanticViewId: '32f12c00-448e-42de-836f-fb87cc4ed02b',
        metrics: ['transactions'],
      },
      [EMBED_WIDGET_ID_PROP]: 'semantic-widget',
    },
  });
  render(<EmbedDashboardModal show onHide={jest.fn()} />, { useRedux: true });

  const snippet = screen.getByTestId('embed-dashboard-snippet');
  expect(snippet).toHaveTextContent('<Widget id="dataset-widget" />');
  expect(snippet).toHaveTextContent('<Widget id="semantic-widget" />');
  expect(snippet).not.toHaveTextContent(/fetchGuestToken|guest token payload/i);
  expect(
    screen.getByText('Viewers sign in to Superset to see these widgets.'),
  ).toBeInTheDocument();
});

test('the header embed action opens the widget embed, not the classic dashboard dialog', async () => {
  addSaved('saved one', 'uuid-1');
  renderHeader();

  await userEvent.click(screen.getByTestId('header-embed'));

  expect(await screen.findByTestId('embed-dashboard')).toBeInTheDocument();
  expect(screen.getByTestId('embed-dashboard-snippet')).toHaveTextContent(
    '<Widget id="uuid-1" />',
  );
  // The classic dialog configures allowed domains for a framed page and
  // reads `/api/v1/dashboard/<id>/embedded`; none of that belongs here.
  expect(screen.queryByText(/allowed domains/i)).not.toBeInTheDocument();
  expect(
    fetchMock.callHistory
      .calls()
      .filter(call => /\/api\/v1\/dashboard\/[^/]+\/embedded/.test(call.url)),
  ).toHaveLength(0);
});

test('the embed action works on a dashboard that was never saved', async () => {
  addSaved('one', 'uuid-1');
  renderHeader();

  expect(screen.getByTestId('header-embed')).toBeEnabled();
});

test('where embedding is turned off, the action is not offered at all', () => {
  enable();

  renderHeader();

  expect(screen.queryByTestId('header-embed')).not.toBeInTheDocument();
  expect(screen.getByTestId('header-save')).toBeInTheDocument();
});

test('a widget not yet saved for embedding is listed with a way to save it', async () => {
  const unsaved = addSaved('not saved');

  render(<EmbedDashboardModal show onHide={jest.fn()} />, { useRedux: true });

  expect(
    screen.getByTestId(`embed-dashboard-save-${unsaved}`),
  ).toBeInTheDocument();
  // Nothing has an id yet, so there is nothing to paste.
  expect(
    screen.queryByTestId('embed-dashboard-snippet'),
  ).not.toBeInTheDocument();

  await userEvent.click(screen.getByTestId(`embed-dashboard-save-${unsaved}`));

  // The widget's own embed dialog, which is what saves it.
  expect(
    await screen.findByTestId('embed-widget-inline-snippet'),
  ).toBeInTheDocument();
});

test('an empty dashboard says there is nothing to embed', () => {
  render(<EmbedDashboardModal show onHide={jest.fn()} />, { useRedux: true });

  expect(screen.getByTestId('embed-dashboard-empty')).toBeInTheDocument();
});

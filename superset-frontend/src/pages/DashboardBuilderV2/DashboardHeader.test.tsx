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
import userEvent from '@testing-library/user-event';
import { FeatureFlag } from '@superset-ui/core';
import { render, screen } from 'spec/helpers/testing-library';
import DashboardProvider from 'src/core/dashboard/DashboardProvider';
import DashboardHeader, { humanize } from './DashboardHeader';

const provider = DashboardProvider.getInstance();

const ADMIN = { userId: 1, firstName: 'Admin', lastName: 'User' };

/** The header reads the session for who is authoring, so it needs the store. */
const renderHeader = () =>
  render(<DashboardHeader />, {
    useRedux: true,
    initialState: { user: ADMIN },
  });

const previousFlags = window.featureFlags;
beforeEach(() => {
  window.featureFlags = {
    ...previousFlags,
    [FeatureFlag.VersionHistory]: true,
  };
  provider.reset();
});
afterEach(() => {
  window.featureFlags = previousFlags;
});

test('hides dashboard history when version history is disabled', () => {
  window.featureFlags = {
    ...previousFlags,
    [FeatureFlag.VersionHistory]: false,
  };
  renderHeader();
  expect(screen.queryByTestId('header-history')).not.toBeInTheDocument();
});

test('the header carries the dashboard-level affordances', () => {
  renderHeader();

  expect(screen.getByTestId('header-templates')).toBeInTheDocument();
  expect(screen.getByTestId('header-history')).toBeInTheDocument();
  expect(screen.getByTestId('header-favorite')).toBeInTheDocument();
  expect(screen.getByTestId('header-published')).toHaveTextContent('Draft');
  expect(screen.getByTestId('header-undo')).toBeInTheDocument();
  expect(screen.getByTestId('header-redo')).toBeInTheDocument();
  expect(screen.getByTestId('header-save')).toBeInTheDocument();
});

test('everything the builder cannot actually do is disabled, not silently dead', () => {
  renderHeader();

  // Saving is live; nothing else here acts on the saved dashboard yet:
  // nothing can be favourited, published or refreshed, and there
  // is no history to step through. A control that looks live and does
  // nothing teaches something false about all of them.
  [
    'header-templates',
    'header-history',
    'header-favorite',
    'header-undo',
    'header-redo',
  ].forEach(test => expect(screen.getByTestId(test)).toBeDisabled());
});

test('the record of what was written sits beside writing it', () => {
  renderHeader();

  const order = [
    ...screen.getByTestId('dashboard-header').querySelectorAll('[data-test]'),
  ].map(el => el.getAttribute('data-test'));

  // Saving commits a version; History is the versions already committed.
  // They are one concern read in one place, so History leaves the far left —
  // where it sat beside Templates as a thing asked before the work — and
  // comes to rest immediately before the button that produces what it lists.
  expect(order.indexOf('header-history')).toBe(
    order.indexOf('header-save') - 1,
  );
});

test('how the dashboard is arranged is not asked in the header', () => {
  renderHeader();

  // Arranging the canvas is authoring, not chrome. It belongs with the rest
  // of the root's properties, where the columns and the gap it works with
  // already live — see Inspector's Arrangement section.
  expect(screen.queryByTestId('layout-mode-switcher')).not.toBeInTheDocument();
});

test('what acts on the canvas is not offered from the bar above it', () => {
  renderHeader();

  // Arranging and refreshing both act on the canvas as a whole, not on the
  // dashboard's identity, so neither belongs in this bar.
  expect(screen.queryByTestId('canvas-arrange')).not.toBeInTheDocument();
  expect(screen.queryByTestId('header-arrange')).not.toBeInTheDocument();
  expect(screen.queryByTestId('header-refresh')).not.toBeInTheDocument();
});

test('the header says who is making the dashboard', () => {
  renderHeader();

  // The one piece of dashboard metadata this page can state truthfully: a
  // dashboard being created is being created by whoever is looking at it.
  expect(screen.getByTestId('header-metadata')).toHaveTextContent('Admin User');
});

test('the header does not claim a dashboard with no row behind it was saved', () => {
  renderHeader();

  // Every other unavailable affordance here says so. A humanized "a day ago"
  // beside them would be the only thing on the bar inventing a fact.
  expect(screen.getByTestId('header-metadata')).toHaveTextContent(
    'Not saved yet',
  );
});

test('the dashboard is nameable, and the name is stored on the dashboard', async () => {
  renderHeader();

  await userEvent.type(screen.getByTestId('header-title'), 'Vaccine rollout');
  await userEvent.tab();

  // On the root node rather than in this component's state: a name is
  // something the dashboard has, so the assistant can read and rename it too.
  expect(provider.getRoot().props?.title).toBe('Vaccine rollout');
});

test('undo and redo restore the dashboard title and update the available actions', async () => {
  renderHeader();

  const title = screen.getByRole('textbox', { name: 'Dashboard title' });
  const undo = () => screen.getByRole('button', { name: 'Undo' });
  const redo = () => screen.getByRole('button', { name: 'Redo' });
  expect(undo()).toBeDisabled();
  expect(redo()).toBeDisabled();

  await userEvent.type(title, 'Sales');
  await userEvent.tab();
  expect(undo()).toBeEnabled();
  await userEvent.click(undo());
  expect(title).toHaveValue('');
  expect(undo()).toBeDisabled();
  expect(redo()).toBeEnabled();

  await userEvent.click(redo());
  expect(title).toHaveValue('Sales');
  expect(undo()).toBeEnabled();
  expect(redo()).toBeDisabled();
});

test('the title shows a rename made anywhere else', () => {
  provider.updateProps(provider.getRoot().id, { title: 'From the assistant' });

  renderHeader();

  expect(screen.getByTestId('header-title')).toHaveValue('From the assistant');
});

test('emptying the title is not a rename', async () => {
  provider.updateProps(provider.getRoot().id, { title: 'Quarterly review' });
  renderHeader();

  await userEvent.clear(screen.getByTestId('header-title'));
  await userEvent.tab();

  // A stray select-all-and-delete must not silently leave the dashboard
  // nameless; the field goes back to what the dashboard is still called.
  expect(provider.getRoot().props?.title).toBe('Quarterly review');
  expect(screen.getByTestId('header-title')).toHaveValue('Quarterly review');
});

test('a save made a moment ago reads as a moment ago in every time zone', () => {
  // The API writes `changed_on` as the server's UTC clock with no zone
  // designator. Read in the reader's own zone it is off by their offset:
  // "5 hours ago" (or "in 4 hours") for a dashboard saved just before.
  jest.useFakeTimers().setSystemTime(new Date('2026-01-01T10:05:00Z'));
  try {
    // Only meaningful where the reader is not on UTC, as this suite is not.
    expect(new Date('2026-01-01T10:00:00').getTimezoneOffset()).not.toBe(0);
    expect(humanize('2026-01-01T10:00:00')).toBe('5 minutes ago');
    expect(humanize('2026-01-01T10:00:00.238676')).toBe('5 minutes ago');
    // A timestamp that names its zone is read as written.
    expect(humanize('2026-01-01T10:00:00Z')).toBe('5 minutes ago');
    expect(humanize('2026-01-01T12:00:00+02:00')).toBe('5 minutes ago');
    expect(humanize('not a time')).toBeUndefined();
    expect(humanize(undefined)).toBeUndefined();
  } finally {
    jest.useRealTimers();
  }
});

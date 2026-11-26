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
import fetchMock from 'fetch-mock';
import { render, screen, waitFor } from 'spec/helpers/testing-library';
import DashboardHistory from './DashboardHistory';

const activity = 'glob:*/api/v1/dashboard/uuid-49/activity/*';

afterEach(() => {
  fetchMock.clearHistory().removeRoutes();
});

test('loads and displays saved dashboard changes when history opens', async () => {
  fetchMock.get(activity, {
    count: 1,
    result: [
      {
        source: 'self',
        entity_kind: 'dashboard',
        transaction_id: 42,
        version_uuid: 'version-42',
        issued_at: '2026-03-25T12:00:00',
        changed_by: { id: 1, first_name: 'Jane', last_name: 'Smith' },
        kind: 'dashboard_title',
        path: ['dashboard_title'],
        operation: 'edit',
        from_value: 'Draft',
        to_value: 'Forecast',
        summary: 'Changed the dashboard title',
      },
    ],
  });
  render(<DashboardHistory uuid="uuid-49" />);
  expect(fetchMock.callHistory.calls(activity)).toHaveLength(0);
  await userEvent.click(screen.getByRole('button', { name: 'History' }));
  const savedVersion = await screen.findByText(/Jane Smith/);
  expect(savedVersion.textContent?.split(' · ')).toEqual([
    expect.stringMatching(/Mar 25, 2026/),
    'Jane Smith',
  ]);
  await userEvent.click(savedVersion);
  await waitFor(() =>
    expect(screen.getByText('Changed the dashboard title')).toBeVisible(),
  );
});

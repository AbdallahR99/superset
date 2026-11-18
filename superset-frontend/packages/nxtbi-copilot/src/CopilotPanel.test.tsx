/*
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

import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import userEvent from '@testing-library/user-event';
import { CopilotPanel } from './CopilotPanel';
import { readAgUiEvents } from './stream';

jest.mock('./stream', () => ({
  ...jest.requireActual('./stream'),
  readAgUiEvents: jest.fn(),
}));

test('restores the prompt and withholds a draft from an interrupted run', async () => {
  jest.mocked(readAgUiEvents).mockImplementationOnce(async function* () {
    yield {
      type: 'CUSTOM',
      name: 'nxtbi.dashboard-proposal',
      value: {
        title: 'Review budget',
        approvalToken: 'test-token',
        widgets: [{ type: 'metric-tile', datasetId: 1, metric: 'total' }],
      },
    };
    yield { type: 'RUN_ERROR' };
  });
  const run = jest.fn(async () => new Response());
  render(
    <CopilotPanel
      host={{
        context: () => ({}),
        run,
        approve: jest.fn(),
      }}
    />,
  );
  const composer = screen.getByRole('textbox', { name: 'Ask Copilot' });
  await userEvent.type(composer, 'Show the budget');
  await userEvent.click(screen.getByRole('button', { name: 'Send' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('ended early');
  expect(
    screen.queryByRole('button', { name: 'Review and save' }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Restore prompt' }));
  expect(composer).toHaveValue('Show the budget');
  expect(composer).toHaveFocus();
});

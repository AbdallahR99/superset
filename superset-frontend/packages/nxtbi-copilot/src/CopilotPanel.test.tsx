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
import type { CopilotHost, CopilotUploadedDataset } from './contracts';
import { readAgUiEvents } from './stream';

jest.mock('./stream', () => ({
  ...jest.requireActual('./stream'),
  readAgUiEvents: jest.fn(),
}));

test('renders streamed assistant Markdown and keeps the user prompt literal', async () => {
  let finish = () => {};
  const pending = new Promise<void>(resolve => {
    finish = resolve;
  });
  jest.mocked(readAgUiEvents).mockImplementationOnce(async function* () {
    yield {
      type: 'TEXT_MESSAGE_CONTENT',
      delta: '### Budget overview\n\n- **Budget** and `alloc',
    };
    await pending;
    yield {
      type: 'TEXT_MESSAGE_CONTENT',
      delta: [
        'ation`',
        '',
        '| Metric | Value |',
        '| --- | --- |',
        '| Spend | 20 |',
        '',
        '```sql',
        'SELECT 20',
        '```',
        '',
        '[Docs](https://example.com) [Blocked](javascript:alert%281%29)',
        '[Encoded](javascript&#58;alert%281%29)',
        '',
        '![Tracking](https://example.com/pixel.png)',
        '',
        '<script>untrusted content</script>',
      ].join('\n'),
    };
    yield { type: 'RUN_FINISHED' };
  });

  const { container } = render(
    <CopilotPanel
      host={{ context: () => ({}), run: async () => new Response() }}
    />,
  );
  expect(
    screen.queryByRole('button', { name: 'Choose CSV files' }),
  ).not.toBeInTheDocument();
  await userEvent.type(
    screen.getByRole('textbox', { name: 'Ask Copilot' }),
    '**Show the budget**',
  );
  await userEvent.click(screen.getByRole('button', { name: 'Send' }));

  expect(
    await screen.findByRole('heading', { name: 'Budget overview' }),
  ).toBeVisible();
  expect(screen.getByText('**Show the budget**')).toBeVisible();
  expect(screen.getByText('Budget').tagName).toBe('STRONG');
  expect(screen.queryByText(/`alloc/)).toBeNull();
  expect(screen.queryByRole('table')).toBeNull();

  finish();

  expect(
    await screen.findByRole('columnheader', { name: 'Value' }),
  ).toBeVisible();
  expect(screen.getByText('SELECT 20').closest('pre')).toHaveAttribute(
    'dir',
    'ltr',
  );
  expect(screen.getByText('allocation').tagName).toBe('CODE');
  expect(screen.getByRole('link', { name: 'Docs' })).toHaveAttribute(
    'href',
    'https://example.com',
  );
  expect(screen.getByText('Blocked')).not.toHaveAttribute('href');
  expect(screen.getByText('Encoded')).not.toHaveAttribute('href');
  expect(container.querySelector('img, script')).toBeNull();
  expect(screen.getByText(/<script>untrusted content<\/script>/)).toBeVisible();
});

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

test('imports CSV files sequentially and drafts with the selected dataset', async () => {
  const user = userEvent.setup();
  let finishFirst: (dataset: CopilotUploadedDataset) => void = () => {};
  const first = new Promise<CopilotUploadedDataset>(resolve => {
    finishFirst = resolve;
  });
  const uploadDataset = jest
    .fn<NonNullable<CopilotHost['uploadDataset']>>()
    .mockReturnValueOnce(first)
    .mockRejectedValueOnce(new Error('Internal transport detail'))
    .mockResolvedValueOnce({ id: 39, name: 'Expenses' });
  const run = jest.fn<CopilotHost['run']>().mockResolvedValue(new Response());
  const completedRun = async function* () {
    yield { type: 'RUN_FINISHED' };
  };
  jest
    .mocked(readAgUiEvents)
    .mockImplementationOnce(completedRun)
    .mockImplementationOnce(completedRun);
  render(
    <CopilotPanel
      host={{
        context: () => ({ active_dataset_id: 27 }),
        uploadDataset,
        run,
        approve: jest.fn(),
      }}
    />,
  );
  const picker = screen.getByLabelText('Choose CSV files', {
    selector: 'input',
  });
  const sales = new File(['name,value\nregion,SECRET_CSV_ROW'], 'sales.csv');
  const expenses = new File(['reason,total\nutilities,20'], 'expense.csv');
  await user.upload(picker, [sales, expenses]);
  expect(screen.getByText('sales.csv')).toBeVisible();
  expect(screen.getByText('expense.csv')).toBeVisible();
  expect(uploadDataset).not.toHaveBeenCalled();
  expect(run).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Import CSV files' }));
  expect(screen.getByRole('progressbar')).toHaveAttribute('max', '2');
  expect(uploadDataset).toHaveBeenCalledTimes(1);
  expect(uploadDataset).toHaveBeenLastCalledWith(
    sales,
    expect.any(AbortSignal),
  );

  finishFirst({ id: 38, name: 'Regional sales' });
  expect(await screen.findByRole('alert')).toHaveTextContent('Import failed');
  expect(
    screen.queryByText('Internal transport detail'),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('radio', { name: 'Regional sales' })).toBeChecked();
  await user.click(
    screen.getByRole('button', { name: 'Retry failed imports' }),
  );
  expect(uploadDataset.mock.calls.map(([file]) => file)).toEqual([
    sales,
    expenses,
    expenses,
  ]);

  await user.click(await screen.findByRole('radio', { name: 'Expenses' }));
  const composer = screen.getByRole('textbox', { name: 'Ask Copilot' });
  await user.type(composer, 'My unsent question');
  await user.click(
    screen.getByRole('button', { name: 'Draft dashboard from dataset' }),
  );

  expect(run).toHaveBeenCalledWith(
    expect.objectContaining({
      context: expect.arrayContaining([
        { description: 'active_dataset_id', value: '27' },
        { description: 'uploaded_dataset_id', value: '39' },
        { description: 'uploaded_dataset_action', value: 'draft' },
      ]),
      messages: [
        expect.objectContaining({
          content: expect.stringContaining('dataset #39'),
        }),
      ],
    }),
    expect.any(AbortSignal),
  );
  expect(JSON.stringify(run.mock.calls[0][0])).not.toContain('SECRET_CSV_ROW');
  expect(composer).toHaveValue('My unsent question');

  await user.click(screen.getByRole('button', { name: 'Send' }));
  expect(run).toHaveBeenCalledTimes(2);
  const manual = run.mock.calls[1][0];
  expect(manual.context).toContainEqual({
    description: 'uploaded_dataset_id',
    value: '39',
  });
  expect(
    manual.context.some(item => item.description === 'uploaded_dataset_action'),
  ).toBe(false);
  expect(manual.messages.at(-1)?.content).toBe('My unsent question');
});

test('rejects unsupported, empty, and oversized selections before upload', async () => {
  const user = userEvent.setup({ applyAccept: false });
  const uploadDataset = jest.fn();
  render(
    <CopilotPanel
      host={{ context: () => ({}), run: jest.fn(), uploadDataset }}
    />,
  );
  await user.upload(
    screen.getByLabelText('Choose CSV files', { selector: 'input' }),
    [
      new File(['text'], 'not-a-csv.txt'),
      new File([], 'empty.csv'),
      new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'big.csv'),
    ],
  );
  expect(screen.getByText('Choose a .csv file.')).toBeVisible();
  expect(screen.getByText('This CSV is empty.')).toBeVisible();
  expect(screen.getByText('Choose a CSV of 10 MiB or less.')).toBeVisible();
  expect(
    screen.queryByRole('button', { name: 'Import CSV files' }),
  ).not.toBeInTheDocument();
  expect(uploadDataset).not.toHaveBeenCalled();
});

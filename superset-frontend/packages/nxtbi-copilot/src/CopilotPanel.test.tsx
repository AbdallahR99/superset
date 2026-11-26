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

import { render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import userEvent from '@testing-library/user-event';
import { BASIC_A2UI_CATALOG_ID } from './a2ui';
import { CopilotPanel } from './CopilotPanel';
import type {
  CopilotHost,
  CopilotUploadedDataset,
  DashboardProposal,
} from './contracts';
import { readAgUiEvents } from './stream';

jest.mock('./stream', () => ({
  ...jest.requireActual('./stream'),
  readAgUiEvents: jest.fn(),
}));

beforeEach(() => {
  jest.mocked(readAgUiEvents).mockReset();
});

function formActivity(
  label: string,
  value: string,
  surfaceId = 'investigation',
) {
  return {
    type: 'ACTIVITY_SNAPSHOT',
    activityType: 'a2ui-surface',
    content: {
      a2ui_operations: [
        {
          version: '1.0',
          createSurface: {
            surfaceId,
            catalogId: BASIC_A2UI_CATALOG_ID,
            components: [
              {
                id: 'root',
                component: 'Column',
                children: ['value', 'submit'],
              },
              {
                id: 'value',
                component: 'TextField',
                label,
                value: { '@path': '/selection' },
              },
              {
                id: 'submit',
                component: 'Button',
                child: 'submitText',
                action: {
                  event: {
                    name: 'nxtbi.submit-form',
                    context: { selection: { '@path': '/selection' } },
                  },
                },
              },
              { id: 'submitText', component: 'Text', text: 'Apply selection' },
            ],
            dataModel: { selection: value },
          },
        },
      ],
    },
  };
}

test('keeps interactive results in turn order and resolves actions against their own edits', async () => {
  const user = userEvent.setup();
  jest
    .mocked(readAgUiEvents)
    .mockImplementationOnce(async function* () {
      yield formActivity('First period', '2025');
      yield { type: 'RUN_FINISHED' };
    })
    .mockImplementationOnce(async function* () {
      yield formActivity('Second period', '2026');
      yield { type: 'RUN_FINISHED' };
    })
    .mockImplementationOnce(async function* () {
      yield { type: 'RUN_FINISHED' };
    });
  const run = jest
    .fn<ReturnType<CopilotHost['run']>, Parameters<CopilotHost['run']>>()
    .mockImplementation(async () => new Response());

  render(<CopilotPanel host={{ context: () => ({}), run }} />);
  const composer = screen.getByRole('textbox', { name: 'Ask Copilot' });
  const send = () => user.click(screen.getByRole('button', { name: 'Send' }));
  await user.type(composer, 'Analyze the earlier period');
  await send();
  const firstPeriod = await screen.findByRole('textbox', {
    name: 'First period',
  });
  await user.clear(firstPeriod);
  await user.type(firstPeriod, '2024');
  await user.type(composer, 'Analyze the later period');
  await send();

  const secondPeriod = await screen.findByRole('textbox', {
    name: 'Second period',
  });
  expect(firstPeriod).toHaveValue('2024');
  expect(secondPeriod).toHaveValue('2026');
  expect(
    firstPeriod.compareDocumentPosition(
      screen.getByText('Analyze the later period'),
    ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();

  await user.type(composer, 'An unsent question');
  const firstResult = firstPeriod.closest('fieldset') as HTMLFieldSetElement;
  await user.click(
    within(firstResult).getByRole('button', { name: 'Apply selection' }),
  );
  expect(
    run.mock.calls[2][0].forwardedProps.a2uiAction?.action.context,
  ).toEqual({
    selection: '2024',
  });
  expect(composer).toHaveValue('An unsent question');
});

test.each(['failed', 'stopped'] as const)(
  'keeps prior results and discards the partial reply when a run is %s',
  async interruption => {
    const user = userEvent.setup();
    const unfinishedReply = 'An unfinished comparison';
    let finish = () => {};
    const pending = new Promise<void>(resolve => {
      finish = resolve;
    });
    jest
      .mocked(readAgUiEvents)
      .mockImplementationOnce(async function* () {
        yield formActivity('Ready period', '2025');
        yield { type: 'RUN_FINISHED' };
      })
      .mockImplementationOnce(async function* () {
        yield formActivity('Unfinished period', '2026', 'interrupted');
        yield { type: 'TEXT_MESSAGE_CONTENT', delta: unfinishedReply };
        await pending;
        yield {
          type: interruption === 'failed' ? 'RUN_ERROR' : 'RUN_FINISHED',
        };
      })
      .mockImplementationOnce(async function* () {
        yield { type: 'RUN_FINISHED' };
      });
    const run = jest
      .fn<ReturnType<CopilotHost['run']>, Parameters<CopilotHost['run']>>()
      .mockImplementation(async () => new Response());
    render(<CopilotPanel host={{ context: () => ({}), run }} />);
    const composer = screen.getByRole('textbox', { name: 'Ask Copilot' });
    const send = () => user.click(screen.getByRole('button', { name: 'Send' }));
    await user.type(composer, 'Show a usable result');
    await send();
    await screen.findByRole('textbox', { name: 'Ready period' });

    await user.type(composer, 'Try another result');
    await send();
    const stop = await screen.findByRole('button', { name: 'Stop' });
    expect(await screen.findByText(unfinishedReply)).toBeInTheDocument();
    const partial = screen.queryByRole('textbox', {
      name: 'Unfinished period',
    });
    if (interruption === 'stopped') await user.click(stop);
    finish();
    expect(partial).toBeNull();

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
    });
    expect(screen.getByRole('textbox', { name: 'Ready period' })).toBeEnabled();
    expect(
      screen.queryByRole('textbox', { name: 'Unfinished period' }),
    ).toBeNull();
    expect(screen.queryByText(unfinishedReply)).not.toBeInTheDocument();

    await user.type(composer, 'Run a fresh comparison');
    await send();
    expect(run).toHaveBeenCalledTimes(3);
    expect(
      run.mock.calls[2][0].messages.map(message => message.content),
    ).not.toContain(unfinishedReply);
  },
);

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

test('keeps proposal format, canonical titles, and bindings when previewing and editing Arabic', async () => {
  const user = userEvent.setup();
  const proposal: DashboardProposal = {
    title: 'Review budget',
    dashboardType: 'v1',
    contentLocale: 'en',
    titleTranslations: { ar: 'مراجعة الميزانية' },
    approvalToken: 'test-token',
    widgets: [
      {
        type: 'metric-tile',
        datasetId: 1,
        metric: 'total',
        filter: { column: 'year', value: 2026 },
        title: 'Total',
        titleTranslations: { ar: 'المجموع' },
      },
    ],
  };
  jest.mocked(readAgUiEvents).mockImplementationOnce(async function* () {
    yield { type: 'CUSTOM', name: 'nxtbi.dashboard-proposal', value: proposal };
    yield { type: 'RUN_FINISHED' };
  });
  const run = jest.fn<
    ReturnType<CopilotHost['run']>,
    Parameters<CopilotHost['run']>
  >(async () => new Response());
  const approve = jest
    .fn<
      Promise<{ id: number; url: string }>,
      [DashboardProposal, AbortSignal]
    >()
    .mockResolvedValue({ id: 8, url: '/dashboard/8/' });
  render(
    <CopilotPanel
      host={{
        locale: 'ar-AE',
        context: () => ({}),
        dashboardTypes: ['v2', 'v1'],
        run,
        approve,
      }}
    />,
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'تنسيق لوحة المعلومات' }),
    'v1',
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'لغة لوحة المعلومات' }),
    'en',
  );
  const composer = screen.getByRole('textbox', { name: 'اسأل المساعد' });
  await user.type(composer, 'Draft a budget dashboard');
  await user.click(screen.getByRole('button', { name: 'إرسال' }));
  const preview = await screen.findByRole('combobox', { name: 'لغة المعاينة' });
  expect(run.mock.calls[0][0].context).toEqual(
    expect.arrayContaining([
      { description: 'locale', value: 'ar' },
      { description: 'dashboard_type', value: 'v1' },
      { description: 'content_locale', value: 'en' },
    ]),
  );
  const title = screen.getByRole('textbox', { name: 'عنوان لوحة المعلومات' });
  expect(title).toHaveValue('Review budget');
  expect(title).toHaveAttribute('dir', 'ltr');
  await user.selectOptions(preview, 'ar');
  expect(title).toHaveValue('مراجعة الميزانية');
  expect(title).toHaveAttribute('dir', 'rtl');
  await user.clear(title);
  await user.type(title, 'تقرير الميزانية');
  await user.selectOptions(preview, 'en');
  expect(title).toHaveValue('Review budget');
  await user.click(screen.getByRole('button', { name: 'مراجعة وحفظ' }));
  expect(approve).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'حفظ لوحة المعلومات' }));
  expect(approve).toHaveBeenCalledWith(
    { ...proposal, titleTranslations: { ar: 'تقرير الميزانية' } },
    expect.any(AbortSignal),
  );
});

test('imports CSV files sequentially and drafts with the selected dataset', async () => {
  const user = userEvent.setup();
  let finishFirst: (dataset: CopilotUploadedDataset) => void = () => {};
  const first = new Promise<CopilotUploadedDataset>(resolve => {
    finishFirst = resolve;
  });
  type UploadDataset = NonNullable<CopilotHost['uploadDataset']>;
  const uploadDataset = jest
    .fn<ReturnType<UploadDataset>, Parameters<UploadDataset>>()
    .mockReturnValueOnce(first)
    .mockRejectedValueOnce(new Error('Internal transport detail'))
    .mockResolvedValueOnce({ id: 39, name: 'Expenses' });
  const run = jest
    .fn<ReturnType<CopilotHost['run']>, Parameters<CopilotHost['run']>>()
    .mockResolvedValue(new Response());
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

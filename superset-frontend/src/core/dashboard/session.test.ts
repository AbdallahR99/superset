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
import DashboardProvider from './DashboardProvider';
import type { DocumentNode } from './DashboardProvider';
import { DashboardV2ConflictError } from './persistence';
import type { DashboardV2 } from './persistence';
import { DashboardSession } from './session';
import type { SessionApi } from './session';

const provider = DashboardProvider.getInstance();

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
}

function defer<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type FetchCall = Deferred<DashboardV2> & {
  ref: string | number;
  signal: AbortSignal | undefined;
};
type SaveCall = Deferred<DashboardV2> & {
  args: Parameters<SessionApi['save']>[0];
};

/** An API whose every request stays pending until the test settles it. */
function fakeApi() {
  const fetches: FetchCall[] = [];
  const saves: SaveCall[] = [];
  const api: SessionApi = {
    fetch: (ref, options) => {
      const call = { ...defer<DashboardV2>(), ref, signal: options?.signal };
      fetches.push(call);
      return call.promise;
    },
    save: args => {
      const call = { ...defer<DashboardV2>(), args };
      saves.push(call);
      return call.promise;
    },
  };
  return { api, fetches, saves };
}

const documentOf = (...markdown: string[]): Record<string, DocumentNode> => ({
  root: { type: 'grid', children: markdown },
  ...Object.fromEntries(
    markdown.map(id => [id, { type: 'markdown', props: { content: id } }]),
  ),
});

const saved = (
  id: number,
  revision: number,
  nodes: Record<string, DocumentNode> = documentOf(),
): DashboardV2 => ({
  id,
  uuid: `uuid-${id}`,
  dashboard_title: `Dashboard ${id}`,
  changed_on: '2020-01-01T00:00:00',
  revision,
  document: { version: 1, nodes },
  embedded: null,
});

/** Lets every already-settled promise run its continuations. */
const flush = async (): Promise<void> => {
  for (let turn = 0; turn < 5; turn += 1) {
    // eslint-disable-next-line no-await-in-loop
    await Promise.resolve();
  }
};

const setup = () => {
  const { api, fetches, saves } = fakeApi();
  const session = new DashboardSession(provider, api);
  return { session, fetches, saves };
};

const addMarkdown = (): string =>
  provider.addWidget('root', 0, { type: 'markdown' });

beforeEach(() => {
  provider.reset();
});

test('a dashboard with no ref opens blank, ready and clean', () => {
  addMarkdown();
  const { session, fetches } = setup();

  session.open(undefined);

  expect(fetches).toHaveLength(0);
  expect(provider.getRoot().children).toEqual([]);
  expect(session.getState()).toMatchObject({
    status: 'ready',
    dashboardId: undefined,
    baseRevision: undefined,
  });
  expect(session.isDirty()).toBe(false);
});

test('opening a saved dashboard blanks the tree until its own document arrives', async () => {
  addMarkdown();
  const { session, fetches } = setup();

  session.open('5');

  // Not the previous dashboard under this one's name.
  expect(provider.getRoot().children).toEqual([]);
  expect(session.getState()).toMatchObject({ status: 'loading', ref: '5' });

  fetches[0].resolve(saved(5, 3, documentOf('a')));
  await flush();

  expect(provider.getRoot().children).toEqual(['a']);
  expect(session.getState()).toMatchObject({
    status: 'ready',
    dashboardId: 5,
    baseRevision: 3,
  });
  expect(session.isDirty()).toBe(false);
});

test('nothing can be saved while a dashboard is loading or after it failed to load', async () => {
  const { session, fetches, saves } = setup();
  session.open('5');

  await expect(session.save()).resolves.toEqual({ status: 'skipped' });

  fetches[0].reject(new Response(null, { status: 404 }));
  await flush();

  expect(session.getState()).toMatchObject({
    status: 'error',
    loadFailure: 'not-found',
  });
  await expect(session.save()).resolves.toEqual({ status: 'skipped' });
  expect(saves).toHaveLength(0);
});

test('a load that answers after navigating to another dashboard is discarded and aborted', async () => {
  const { session, fetches } = setup();
  session.open('5');
  session.open('6');

  expect(fetches[0].signal?.aborted).toBe(true);

  // The slow answer for 5 arrives after the fast one for 6.
  fetches[1].resolve(saved(6, 1, documentOf('six')));
  await flush();
  fetches[0].resolve(saved(5, 9, documentOf('five')));
  await flush();

  expect(provider.getRoot().children).toEqual(['six']);
  expect(session.getState()).toMatchObject({
    ref: '6',
    dashboardId: 6,
    baseRevision: 1,
  });
});

test('a failed load of a dashboard navigated away from does not mark the current one failed', async () => {
  const { session, fetches } = setup();
  session.open('5');
  session.open(undefined);

  fetches[0].reject(new Error('network'));
  await flush();

  expect(session.getState().status).toBe('ready');
});

test('an answer about a different id is not applied', async () => {
  const { session, fetches } = setup();
  session.open('5');

  fetches[0].resolve(saved(6, 1, documentOf('six')));
  await flush();

  expect(session.getState()).toMatchObject({ status: 'error' });
  expect(provider.getRoot().children).toEqual([]);
});

test('edits made while loading are kept, and the loaded copy becomes a conflict instead of overwriting them', async () => {
  const { session, fetches, saves } = setup();
  session.open('5');
  const edited = addMarkdown();

  fetches[0].resolve(saved(5, 4, documentOf('theirs')));
  await flush();

  expect(provider.getRoot().children).toEqual([edited]);
  expect(session.getState()).toMatchObject({
    status: 'ready',
    dashboardId: 5,
    baseRevision: undefined,
    conflict: { revision: 4, source: 'load' },
  });
  expect(session.isDirty()).toBe(true);

  // Keeping on editing resolves nothing: saving asks again and sends nothing.
  session.dismissConflict();
  await expect(session.save()).resolves.toEqual({ status: 'conflict' });
  expect(saves).toHaveLength(0);
  expect(session.getState().conflict).toMatchObject({ source: 'load' });
});

test('a document that is too deep is a load failure, not a crash', async () => {
  const { session, fetches } = setup();
  session.open('5');
  const nodes: Record<string, DocumentNode> = {
    root: { type: 'grid', children: ['n1'] },
  };
  for (let index = 1; index <= 40; index += 1) {
    nodes[`n${index}`] = { type: 'tabs', children: [`n${index + 1}`] };
  }
  nodes.n41 = { type: 'markdown' };

  fetches[0].resolve(saved(5, 1, nodes));
  await flush();

  expect(session.getState()).toMatchObject({
    status: 'error',
    loadFailure: 'invalid',
  });
});

test('a repaired document reports how much was repaired', async () => {
  const { session, fetches } = setup();
  session.open('5');

  fetches[0].resolve(
    saved(5, 1, {
      root: { type: 'grid', children: ['a'] },
      a: { type: 'tabs', children: ['a'] },
    }),
  );
  await flush();

  expect(session.getState()).toMatchObject({ status: 'ready', repairs: 1 });
});

test('a row title is shown when the document carries none', async () => {
  const { session, fetches } = setup();
  session.open('5');

  fetches[0].resolve(saved(5, 1, documentOf()));
  await flush();

  expect(provider.getRoot().props?.title).toBe('Dashboard 5');
  // Putting the name where it is read is not an edit.
  expect(session.isDirty()).toBe(false);
});

test('the first save creates, and the next one updates against the revision it returned', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();

  const first = session.save();
  expect(saves[0].args.id).toBeUndefined();
  expect(saves[0].args.baseRevision).toBeUndefined();
  saves[0].resolve(saved(7, 1));
  await expect(first).resolves.toEqual({
    status: 'saved',
    id: 7,
    created: true,
  });
  expect(session.getState()).toMatchObject({
    dashboardId: 7,
    baseRevision: 1,
    saving: false,
  });
  expect(session.isDirty()).toBe(false);

  addMarkdown();
  const second = session.save();
  expect(saves[1].args).toMatchObject({ id: 7, baseRevision: 1 });
  saves[1].resolve(saved(7, 2));
  await expect(second).resolves.toEqual({
    status: 'saved',
    id: 7,
    created: false,
  });
  expect(session.getState().baseRevision).toBe(2);
});

test('saving twice before the first answer creates one dashboard, not two', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();

  const first = session.save();
  const second = session.save();

  expect(second).toBe(first);
  expect(saves).toHaveLength(1);

  saves[0].resolve(saved(7, 1));
  await first;
  await flush();

  // Nothing changed in between, so there is nothing more to send.
  expect(saves).toHaveLength(1);
});

test('an edit made during a save is sent by one follow-up save, as an update', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();

  const running = session.save();
  const late = addMarkdown();
  session.save();
  session.save();
  expect(saves).toHaveLength(1);

  saves[0].resolve(saved(7, 1));
  await flush();

  expect(saves).toHaveLength(2);
  expect(saves[1].args).toMatchObject({ id: 7, baseRevision: 1 });
  expect(Object.keys(saves[1].args.nodes)).toContain(late);
  expect(session.getState().saving).toBe(true);

  saves[1].resolve(saved(7, 2));
  await expect(running).resolves.toEqual({
    status: 'saved',
    id: 7,
    created: true,
  });
  expect(session.getState()).toMatchObject({ saving: false, baseRevision: 2 });
  expect(session.isDirty()).toBe(false);
});

test('an edit made during a save leaves the dashboard dirty when no follow-up was asked for', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();

  const running = session.save();
  addMarkdown();
  saves[0].resolve(saved(7, 1));
  await running;

  expect(saves).toHaveLength(1);
  expect(session.isDirty()).toBe(true);
});

test('opening the route of a dashboard just created adopts it instead of reloading', async () => {
  const { session, fetches, saves } = setup();
  session.open(undefined);
  const widget = addMarkdown();
  provider.setSelection(widget);

  const running = session.save();
  saves[0].resolve(saved(7, 1));
  await running;
  session.open('7');

  expect(fetches).toHaveLength(0);
  expect(provider.getRoot().children).toEqual([widget]);
  expect(provider.getSelection()).toBe(widget);
  expect(session.getState()).toMatchObject({
    status: 'ready',
    ref: '7',
    dashboardId: 7,
  });
});

test('adoption happens once: a later visit to the same route loads from the server', async () => {
  const { session, fetches, saves } = setup();
  session.open(undefined);
  addMarkdown();
  const running = session.save();
  saves[0].resolve(saved(7, 1));
  await running;
  session.open('7');
  session.close();

  session.open('7');

  expect(fetches).toHaveLength(1);
  expect(session.getState().status).toBe('loading');
});

test('the page remounting on its way to the new route still adopts', async () => {
  const { session, fetches, saves } = setup();
  session.open(undefined);
  const widget = addMarkdown();
  const running = session.save();
  saves[0].resolve(saved(7, 1));
  await running;

  // The unsaved route and the saved one are different routes: the page
  // closes and opens again in the same pass.
  session.close();
  session.open('7');

  expect(fetches).toHaveLength(0);
  expect(provider.getRoot().children).toEqual([widget]);
  expect(session.getState()).toMatchObject({ status: 'ready', ref: '7' });
});

test('a created dashboard left without visiting its route is loaded afresh when visited later', async () => {
  const { session, fetches, saves } = setup();
  session.open(undefined);
  addMarkdown();
  const running = session.save();
  saves[0].resolve(saved(7, 1));
  await running;

  session.close();
  await flush();
  session.open('7');

  expect(fetches).toHaveLength(1);
  expect(session.getState().status).toBe('loading');
});

test('a refused save records the conflict and does not retry or overwrite', async () => {
  const { session, fetches, saves } = setup();
  session.open('5');
  fetches[0].resolve(saved(5, 3, documentOf('a')));
  await flush();
  const mine = addMarkdown();

  const running = session.save();
  saves[0].reject(new DashboardV2ConflictError(4));

  await expect(running).resolves.toEqual({ status: 'conflict' });
  expect(saves).toHaveLength(1);
  expect(session.getState()).toMatchObject({
    saving: false,
    baseRevision: 3,
    conflict: { revision: 4, source: 'save' },
  });
  expect(provider.getRoot().children).toContain(mine);
  expect(session.isDirty()).toBe(true);
});

test('keeping on editing after a conflict means the next save is refused the same way', async () => {
  const { session, fetches, saves } = setup();
  session.open('5');
  fetches[0].resolve(saved(5, 3));
  await flush();
  addMarkdown();
  const first = session.save();
  saves[0].reject(new DashboardV2ConflictError(4));
  await first;

  session.dismissConflict();
  expect(session.getState().conflict).toBeUndefined();
  const second = session.save();

  // Still based on the revision that was loaded, never silently on theirs.
  expect(saves[1].args.baseRevision).toBe(3);
  saves[1].reject(new DashboardV2ConflictError(4));
  await expect(second).resolves.toEqual({ status: 'conflict' });
});

test('overwriting saves on top of the revision the server reported', async () => {
  const { session, fetches, saves } = setup();
  session.open('5');
  fetches[0].resolve(saved(5, 3));
  await flush();
  const mine = addMarkdown();
  const first = session.save();
  saves[0].reject(new DashboardV2ConflictError(4));
  await first;

  const overwriting = session.overwrite();
  await flush();

  expect(saves[1].args).toMatchObject({ id: 5, baseRevision: 4 });
  expect(Object.keys(saves[1].args.nodes)).toContain(mine);
  saves[1].resolve(saved(5, 5));
  await expect(overwriting).resolves.toMatchObject({ status: 'saved' });
  expect(session.getState()).toMatchObject({
    baseRevision: 5,
    conflict: undefined,
  });
});

test('overwriting reads the current revision first when the refusal did not say', async () => {
  const { session, fetches, saves } = setup();
  session.open('5');
  fetches[0].resolve(saved(5, 3));
  await flush();
  addMarkdown();
  const first = session.save();
  saves[0].reject(new DashboardV2ConflictError(undefined));
  await first;

  const overwriting = session.overwrite();
  expect(fetches).toHaveLength(2);
  fetches[1].resolve(saved(5, 8, documentOf('theirs')));
  await flush();

  expect(saves[1].args.baseRevision).toBe(8);
  // Only the revision is taken from that read; the tree stays the author's.
  expect(provider.getNode('theirs')).toBeUndefined();
  saves[1].resolve(saved(5, 9));
  await expect(overwriting).resolves.toMatchObject({ status: 'saved' });
});

test('an overwrite that loses a second race is a conflict again, with the newer revision', async () => {
  const { session, fetches, saves } = setup();
  session.open('5');
  fetches[0].resolve(saved(5, 3));
  await flush();
  addMarkdown();
  const first = session.save();
  saves[0].reject(new DashboardV2ConflictError(4));
  await first;

  const overwriting = session.overwrite();
  await flush();
  saves[1].reject(new DashboardV2ConflictError(6));

  await expect(overwriting).resolves.toEqual({ status: 'conflict' });
  expect(session.getState().conflict).toEqual({ revision: 6, source: 'save' });
});

test('reloading theirs replaces the tree and clears the conflict', async () => {
  const { session, fetches, saves } = setup();
  session.open('5');
  fetches[0].resolve(saved(5, 3, documentOf('a')));
  await flush();
  addMarkdown();
  const first = session.save();
  saves[0].reject(new DashboardV2ConflictError(4));
  await first;

  session.reloadTheirs();
  expect(session.getState()).toMatchObject({
    status: 'loading',
    conflict: undefined,
  });
  fetches[1].resolve(saved(5, 4, documentOf('theirs')));
  await flush();

  expect(provider.getRoot().children).toEqual(['theirs']);
  expect(session.getState()).toMatchObject({
    status: 'ready',
    baseRevision: 4,
  });
  expect(session.isDirty()).toBe(false);
});

test('a save answered after navigating away is not applied to the dashboard opened since', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();
  const running = session.save();

  session.open(undefined);
  saves[0].resolve(saved(7, 1));

  await expect(running).resolves.toEqual({ status: 'superseded' });
  expect(session.getState()).toMatchObject({
    dashboardId: undefined,
    saving: false,
  });
});

test('a failed save says so and leaves the dashboard dirty', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();
  const error = new Error('boom');

  const running = session.save();
  saves[0].reject(error);

  await expect(running).resolves.toEqual({ status: 'error', error });
  expect(session.getState().saving).toBe(false);
  expect(session.isDirty()).toBe(true);
});

test('closing the page keeps anything in flight from landing later', async () => {
  const { session, fetches } = setup();
  const listener = jest.fn();
  session.open('5');
  session.subscribe(listener);

  session.close();
  listener.mockClear();
  fetches[0].resolve(saved(5, 3, documentOf('a')));
  await flush();

  expect(fetches[0].signal?.aborted).toBe(true);
  expect(listener).not.toHaveBeenCalled();
  expect(provider.getRoot().children).toEqual([]);
});

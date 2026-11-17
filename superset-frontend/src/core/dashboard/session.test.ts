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

/** A refusal the server wrote itself, as `SupersetClient` rejects with one. */
const refusal = (status: number, body: unknown = {}): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

/** The server could not be reached, or did not answer. */
const networkFailure = (): Error => new TypeError('Failed to fetch');

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test('a failed save says so and leaves the dashboard dirty', async () => {
  const { session, saves, fetches } = setup();
  session.open(undefined);
  addMarkdown();
  const error = refusal(400, { message: 'no' });

  const running = session.save();
  saves[0].reject(error);

  await expect(running).resolves.toEqual({ status: 'error', error });
  // The server answered, so there is nothing to ask it about.
  expect(fetches).toHaveLength(0);
  expect(session.getState().saving).toBe(false);
  expect(session.isDirty()).toBe(true);
});

test('a create carries a uuid, and every retry of that create carries the same one', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();

  const first = session.save();
  saves[0].reject(refusal(400));
  await first;
  const second = session.save();
  saves[1].reject(refusal(400));
  await second;

  expect(saves[0].args.uuid).toMatch(UUID);
  expect(saves[1].args.uuid).toBe(saves[0].args.uuid);
});

test('another unsaved document gets a uuid of its own, and an update carries none', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();
  const first = session.save();
  saves[0].reject(refusal(400));
  await first;

  session.open(undefined);
  addMarkdown();
  const second = session.save();
  saves[1].resolve(saved(7, 1));
  await second;
  addMarkdown();
  const third = session.save();
  saves[2].resolve(saved(7, 2));
  await third;

  expect(saves[1].args.uuid).toMatch(UUID);
  expect(saves[1].args.uuid).not.toBe(saves[0].args.uuid);
  expect(saves[2].args).toMatchObject({ id: 7, uuid: undefined });
});

test('a create whose answer was lost is found by its uuid instead of being created twice', async () => {
  const { session, saves, fetches } = setup();
  session.open(undefined);
  addMarkdown();

  const running = session.save();
  const sent = saves[0].args;
  saves[0].reject(networkFailure());
  await flush();

  // The server is asked what it holds under the uuid the create carried.
  expect(fetches).toHaveLength(1);
  expect(fetches[0].ref).toBe(sent.uuid);
  fetches[0].resolve(saved(7, 1, sent.nodes));

  await expect(running).resolves.toEqual({
    status: 'saved',
    id: 7,
    created: true,
  });
  expect(saves).toHaveLength(1);
  expect(session.getState()).toMatchObject({
    dashboardId: 7,
    baseRevision: 1,
    saving: false,
  });
  expect(session.isDirty()).toBe(false);
});

test('a create that never reached the server is reported as failed and can be retried as the same create', async () => {
  const { session, saves, fetches } = setup();
  session.open(undefined);
  addMarkdown();
  const error = networkFailure();

  const running = session.save();
  saves[0].reject(error);
  await flush();
  fetches[0].reject(refusal(404));

  await expect(running).resolves.toEqual({ status: 'error', error });
  expect(session.getState().dashboardId).toBeUndefined();
  expect(session.isDirty()).toBe(true);

  const retry = session.save();
  expect(saves[1].args).toMatchObject({ id: undefined });
  expect(saves[1].args.uuid).toBe(saves[0].args.uuid);
  saves[1].resolve(saved(7, 1));
  await expect(retry).resolves.toEqual({
    status: 'saved',
    id: 7,
    created: true,
  });
});

test('a create the server recognises as a repeat adopts the stored dashboard and writes later edits as an update', async () => {
  const { session, saves, fetches } = setup();
  session.open(undefined);
  addMarkdown();
  const first = session.save();
  const original = saves[0].args.nodes;
  saves[0].reject(networkFailure());
  await flush();
  // Neither the create nor the question about it got through.
  fetches[0].reject(networkFailure());
  await first;

  // The author carries on editing and saves again. The server did take the
  // first create, and answers the repeat with what it stored then.
  addMarkdown();
  const second = session.save();
  saves[1].resolve({ ...saved(7, 1, original), replayed: true });
  await flush();

  // The row exists but holds the earlier tree: this one goes in as an
  // update on the revision the row is at, not as a second create.
  expect(saves).toHaveLength(3);
  expect(saves[2].args).toMatchObject({ id: 7, baseRevision: 1 });
  expect(saves[2].args.nodes).toEqual(provider.getDocument());
  saves[2].resolve(saved(7, 2));

  await expect(second).resolves.toEqual({
    status: 'saved',
    id: 7,
    created: true,
  });
  expect(session.getState()).toMatchObject({
    dashboardId: 7,
    baseRevision: 2,
  });
  expect(session.isDirty()).toBe(false);
});

test('a repeat the server answers with exactly this tree is a finished save', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();

  const running = session.save();
  saves[0].resolve({
    ...saved(7, 1, saves[0].args.nodes),
    replayed: true,
  });

  await expect(running).resolves.toEqual({
    status: 'saved',
    id: 7,
    created: true,
  });
  expect(saves).toHaveLength(1);
  expect(session.isDirty()).toBe(false);
});

/** A session on dashboard 5 at `revision`, with one unsaved edit. */
const editedSession = async (revision: number) => {
  const context = setup();
  context.session.open('5');
  context.fetches[0].resolve(saved(5, revision, documentOf('a')));
  await flush();
  addMarkdown();
  return context;
};

test('an update answered with anything but the base plus one is a conflict, not a new base', async () => {
  const { session, saves } = await editedSession(3);

  const running = session.save();
  saves[0].resolve(saved(5, 5));

  await expect(running).resolves.toEqual({ status: 'conflict' });
  expect(session.getState()).toMatchObject({
    baseRevision: 3,
    conflict: { revision: 5, source: 'save' },
    saving: false,
  });
  expect(session.isDirty()).toBe(true);
});

test('an update whose answer was lost but which the server took is a finished save', async () => {
  const { session, saves, fetches } = await editedSession(3);

  const running = session.save();
  const sent = saves[0].args;
  saves[0].reject(networkFailure());
  await flush();

  expect(fetches).toHaveLength(2);
  expect(fetches[1].ref).toBe(5);
  // Key order and absent values differ between what was sent and what a
  // server hands back; neither makes it a different document.
  const stored = JSON.parse(JSON.stringify(sent.nodes)) as typeof sent.nodes;
  fetches[1].resolve(
    saved(5, 4, Object.fromEntries(Object.entries(stored).reverse())),
  );

  await expect(running).resolves.toEqual({
    status: 'saved',
    id: 5,
    created: false,
  });
  expect(saves).toHaveLength(1);
  expect(session.getState()).toMatchObject({ baseRevision: 4, saving: false });
  expect(session.getState().conflict).toBeUndefined();
  expect(session.isDirty()).toBe(false);
});

test('an update that never reached the server is reported as failed, on the same base', async () => {
  const { session, saves, fetches } = await editedSession(3);
  const error = networkFailure();

  const running = session.save();
  saves[0].reject(error);
  await flush();
  fetches[1].resolve(saved(5, 3, documentOf('a')));

  await expect(running).resolves.toEqual({ status: 'error', error });
  expect(session.getState()).toMatchObject({ baseRevision: 3 });
  expect(session.getState().conflict).toBeUndefined();
  expect(session.isDirty()).toBe(true);
});

test('an update whose answer was lost while someone else saved is a conflict', async () => {
  const { session, saves, fetches } = await editedSession(3);

  const running = session.save();
  saves[0].reject(networkFailure());
  await flush();
  // One revision on, but not the document that was sent.
  fetches[1].resolve(saved(5, 4, documentOf('theirs')));

  await expect(running).resolves.toEqual({ status: 'conflict' });
  expect(session.getState().conflict).toEqual({ revision: 4, source: 'save' });
  expect(session.isDirty()).toBe(true);
});

test('a gateway error is treated like a lost answer, a refusal is not', async () => {
  const { session, saves, fetches } = await editedSession(3);

  const first = session.save();
  const sent = saves[0].args;
  saves[0].reject(refusal(504));
  await flush();
  expect(fetches).toHaveLength(2);
  fetches[1].resolve(saved(5, 4, sent.nodes));
  await expect(first).resolves.toMatchObject({ status: 'saved' });

  addMarkdown();
  const second = session.save();
  saves[1].reject(refusal(422, { message: 'invalid' }));
  await expect(second).resolves.toMatchObject({ status: 'error' });
  expect(fetches).toHaveLength(2);
});

test('a refusal that follows an unanswered save is recognised as the author’s own save', async () => {
  const { session, saves, fetches } = await editedSession(3);
  const first = session.save();
  const sent = saves[0].args;
  saves[0].reject(networkFailure());
  await flush();
  // The server took the save, but could not be asked about it either.
  fetches[1].reject(networkFailure());
  await expect(first).resolves.toMatchObject({ status: 'error' });

  const retry = session.save();
  expect(saves[1].args).toMatchObject({ id: 5, baseRevision: 3 });
  saves[1].reject(new DashboardV2ConflictError(4));
  await flush();
  expect(fetches).toHaveLength(3);
  fetches[2].resolve(saved(5, 4, sent.nodes));

  // Nobody else saved: the copy on the server is the one on screen.
  await expect(retry).resolves.toEqual({
    status: 'saved',
    id: 5,
    created: false,
  });
  expect(session.getState()).toMatchObject({ baseRevision: 4 });
  expect(session.getState().conflict).toBeUndefined();
  expect(session.isDirty()).toBe(false);
});

test('edits made after an unanswered save are sent again on the revision that save produced', async () => {
  const { session, saves, fetches } = await editedSession(3);
  const first = session.save();
  const sent = saves[0].args;
  saves[0].reject(networkFailure());
  await flush();
  fetches[1].reject(networkFailure());
  await first;

  addMarkdown();
  const retry = session.save();
  saves[1].reject(new DashboardV2ConflictError(4));
  await flush();
  fetches[2].resolve(saved(5, 4, sent.nodes));
  await flush();

  expect(saves).toHaveLength(3);
  expect(saves[2].args).toMatchObject({ id: 5, baseRevision: 4 });
  saves[2].resolve(saved(5, 5));
  await expect(retry).resolves.toMatchObject({ status: 'saved', id: 5 });
  expect(session.getState()).toMatchObject({ baseRevision: 5 });
});

test('a refusal after an unanswered save is still a conflict when the server holds someone else’s copy', async () => {
  const { session, saves, fetches } = await editedSession(3);
  const first = session.save();
  saves[0].reject(networkFailure());
  await flush();
  fetches[1].reject(networkFailure());
  await first;

  const retry = session.save();
  saves[1].reject(new DashboardV2ConflictError(4));
  await flush();
  fetches[2].resolve(saved(5, 4, documentOf('theirs')));

  await expect(retry).resolves.toEqual({ status: 'conflict' });
  expect(session.getState().conflict).toEqual({ revision: 4, source: 'save' });
});

test('a create followed by a refused update still reports the dashboard it created', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();

  const first = session.save();
  const added = addMarkdown();
  const second = session.save();
  saves[0].resolve(saved(7, 1));
  await flush();
  const error = refusal(422, {
    message: 'Widget props failed validation.',
    errors: { [added]: [{ loc: ['content'], message: 'Required' }] },
  });
  saves[1].reject(error);

  await expect(first).resolves.toEqual({
    status: 'error',
    error,
    created: true,
    id: 7,
  });
  expect(await second).toBe(await first);
  expect(session.getState()).toMatchObject({
    dashboardId: 7,
    baseRevision: 1,
    nodeErrors: { [added]: ['content: Required'] },
  });
});

test('a create followed by a conflicting update reports both', async () => {
  const { session, saves } = setup();
  session.open(undefined);
  addMarkdown();

  const running = session.save();
  addMarkdown();
  session.save();
  saves[0].resolve(saved(7, 1));
  await flush();
  saves[1].reject(new DashboardV2ConflictError(2));

  await expect(running).resolves.toEqual({
    status: 'conflict',
    created: true,
    id: 7,
  });
});

test('what a refusal said about widgets is kept until the next save starts', async () => {
  const { session, saves } = await editedSession(3);

  const first = session.save();
  saves[0].reject(
    refusal(422, {
      message: 'invalid',
      errors: {
        a: [
          { loc: ['dataBinding', 'rowLimit'], message: 'Must be positive' },
          { loc: [], message: 'Unknown column' },
        ],
      },
    }),
  );
  await first;

  expect(session.getState().nodeErrors).toEqual({
    a: ['dataBinding.rowLimit: Must be positive', 'Unknown column'],
  });

  const second = session.save();
  expect(session.getState().nodeErrors).toEqual({});
  saves[1].resolve(saved(5, 4));
  await second;
  expect(session.getState().nodeErrors).toEqual({});
});

test("a widget's refusal goes when its properties are edited or it is removed, and stays through anything else", async () => {
  const { session, saves, fetches } = setup();
  session.open('5');
  fetches[0].resolve(saved(5, 3, documentOf('a', 'b', 'c')));
  await flush();
  provider.updateProps('a', { content: 'edited' });
  const listener = jest.fn();
  session.subscribe(listener);

  const running = session.save();
  saves[0].reject(
    refusal(422, {
      message: 'invalid',
      errors: {
        a: [{ loc: ['content'], message: 'Too long' }],
        b: [{ loc: ['content'], message: 'Too long' }],
        c: [{ loc: ['content'], message: 'Too long' }],
      },
    }),
  );
  await running;
  expect(Object.keys(session.getState().nodeErrors)).toEqual(['a', 'b', 'c']);

  // Moving a widget, or editing another one, says nothing about this one.
  provider.updateLayout('a', { col: 2 });
  provider.addWidget('root', 0, { type: 'markdown' });
  expect(Object.keys(session.getState().nodeErrors)).toEqual(['a', 'b', 'c']);

  listener.mockClear();
  provider.updateProps('a', { content: 'fixed' });
  expect(Object.keys(session.getState().nodeErrors)).toEqual(['b', 'c']);
  // Said to whoever draws the errors, once.
  expect(listener).toHaveBeenCalledTimes(1);

  provider.removeWidget('b');
  expect(Object.keys(session.getState().nodeErrors)).toEqual(['c']);

  provider.updateProps('c', { content: 'fixed' });
  expect(session.getState().nodeErrors).toEqual({});
  // Nothing is left to watch for: a later edit is not the session's news.
  listener.mockClear();
  provider.updateProps('c', { content: 'again' });
  expect(listener).not.toHaveBeenCalled();
});

test('a refusal about a widget edited while the save was away is not shown on it', async () => {
  const { session, saves } = await editedSession(3);

  const running = session.save();
  provider.updateProps('a', { content: 'already fixed' });
  saves[0].reject(
    refusal(422, {
      message: 'invalid',
      errors: { a: [{ loc: ['content'], message: 'Too long' }] },
    }),
  );
  await running;

  expect(session.getState().nodeErrors).toEqual({});
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

/** A create that failed with no answer, and no answer about it either. */
const lostCreate = async () => {
  const context = setup();
  context.session.open(undefined);
  addMarkdown();
  const first = context.session.save();
  const original = context.saves[0].args.nodes;
  context.saves[0].reject(networkFailure());
  await flush();
  context.fetches[0].reject(networkFailure());
  await first;
  return { ...context, original };
};

test('a repeated create that finds the dashboard saved by someone since is a conflict, not an update over it', async () => {
  const { session, saves } = await lostCreate();

  // The create did land. The dashboard was opened in another tab and saved
  // twice there, so it is at revision 3 with a tree this session never sent.
  addMarkdown();
  const second = session.save();
  saves[1].resolve({ ...saved(7, 3, documentOf('theirs')), replayed: true });

  await expect(second).resolves.toEqual({
    status: 'conflict',
    created: true,
    id: 7,
  });
  // The repeat is the last request: nothing is written over the other copy.
  expect(saves).toHaveLength(2);
  expect(session.getState()).toMatchObject({
    dashboardId: 7,
    uuid: 'uuid-7',
    baseRevision: undefined,
    saving: false,
    conflict: { revision: 3, source: 'save' },
  });
  expect(session.isDirty()).toBe(true);

  // Carrying on does not turn the next save into a blind update either.
  session.dismissConflict();
  await expect(session.save()).resolves.toEqual({ status: 'conflict' });
  expect(saves).toHaveLength(2);
  expect(session.getState().conflict).toEqual({ revision: 3, source: 'save' });

  // Overwriting is the author's decision, on the revision the server holds.
  const overwriting = session.overwrite();
  await flush();
  expect(saves).toHaveLength(3);
  expect(saves[2].args).toMatchObject({ id: 7, baseRevision: 3 });
  saves[2].resolve(saved(7, 4));
  await expect(overwriting).resolves.toMatchObject({ status: 'saved', id: 7 });
  expect(session.getState()).toMatchObject({
    baseRevision: 4,
    conflict: undefined,
  });
});

test('a lost create found by its uuid at a later revision with another tree is a conflict', async () => {
  const { session, saves, fetches } = setup();
  session.open(undefined);
  addMarkdown();

  const running = session.save();
  saves[0].reject(networkFailure());
  await flush();
  fetches[0].resolve(saved(7, 5, documentOf('theirs')));

  await expect(running).resolves.toEqual({
    status: 'conflict',
    created: true,
    id: 7,
  });
  expect(saves).toHaveLength(1);
  expect(session.getState()).toMatchObject({
    dashboardId: 7,
    baseRevision: undefined,
    conflict: { revision: 5, source: 'save' },
  });
});

test('a repeated create that finds one of its own earlier attempts is still updated without asking', async () => {
  const { session, saves, original } = await lostCreate();

  // A server that numbers its first write differently: the stored tree is
  // what tells this session the row is still its own.
  addMarkdown();
  const second = session.save();
  saves[1].resolve({ ...saved(7, 0, original), replayed: true });
  await flush();

  expect(saves).toHaveLength(3);
  expect(saves[2].args).toMatchObject({ id: 7, baseRevision: 0 });
  saves[2].resolve(saved(7, 1));
  await expect(second).resolves.toMatchObject({ status: 'saved', id: 7 });
  expect(session.getState().conflict).toBeUndefined();
});

test('reloading after a repeated create met someone else’s copy takes theirs', async () => {
  const { session, saves, fetches } = await lostCreate();
  addMarkdown();
  const second = session.save();
  saves[1].resolve({ ...saved(7, 3, documentOf('theirs')), replayed: true });
  await second;

  session.reloadTheirs();
  expect(fetches[1].ref).toBe('7');
  fetches[1].resolve(saved(7, 3, documentOf('theirs')));
  await flush();

  expect(provider.getRoot().children).toEqual(['theirs']);
  expect(session.getState()).toMatchObject({
    baseRevision: 3,
    conflict: undefined,
  });
  // The decision was made: saving is an ordinary update again.
  provider.updateProps('theirs', { content: 'edited' });
  const third = session.save();
  expect(saves[2].args).toMatchObject({ id: 7, baseRevision: 3 });
  saves[2].resolve(saved(7, 4));
  await third;
});

test('a lost update is recognised as stored when the only difference is a null the server does not store', async () => {
  const { session, saves, fetches } = await editedSession(3);
  const widget = provider.addWidget('root', 0, {
    type: 'markdown',
    layout: null,
    props: null,
    style: null,
  } as unknown as Parameters<typeof provider.addWidget>[2]);

  const running = session.save();
  const sent = saves[0].args.nodes;
  saves[0].reject(networkFailure());
  await flush();
  // What the server holds: the same tree, without the null parts.
  const stored = JSON.parse(JSON.stringify(sent)) as typeof sent;
  stored[widget] = { type: 'markdown' };
  fetches[1].resolve(saved(5, 4, stored));

  await expect(running).resolves.toMatchObject({ status: 'saved', id: 5 });
  expect(session.getState()).toMatchObject({
    baseRevision: 4,
    conflict: undefined,
  });
});

test.each([403, 422])(
  'a save refused with %s for a widget whose dataset the author cannot read is shown on that widget',
  async status => {
    const { session, saves } = await editedSession(3);

    const running = session.save();
    saves[0].reject(
      refusal(status, {
        message: 'You cannot author widgets on this dataset',
        errors: {
          a: [
            {
              loc: ['dataBinding', 'datasetId'],
              message: 'You do not have access to dataset 12',
            },
          ],
        },
      }),
    );

    await expect(running).resolves.toMatchObject({ status: 'error' });
    expect(saves).toHaveLength(1);
    expect(session.getState()).toMatchObject({
      saving: false,
      conflict: undefined,
      baseRevision: 3,
      nodeErrors: {
        a: ['dataBinding.datasetId: You do not have access to dataset 12'],
      },
    });
    expect(session.isDirty()).toBe(true);
  },
);

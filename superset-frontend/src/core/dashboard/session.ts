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

/**
 * @fileoverview Which saved dashboard the store's tree belongs to, and the
 * only code that loads it or writes it back.
 *
 * The store (`DashboardProvider`) is a tree and nothing else: it does not
 * know whether what it holds was ever saved, under which id, or whether the
 * server still holds the copy it was loaded from. Answering those from
 * component state is how a save ends up writing one dashboard's tree into
 * another's row, so the answers live here, outside React, and every load and
 * save goes through this one object:
 *
 * - One dashboard at a time. Turning to another one (`open`) blanks the tree
 *   first and bumps an epoch; a response that belongs to an earlier epoch is
 *   dropped, and the request behind it is aborted.
 * - A loaded document never replaces edits. If the tree changed while the
 *   load was in flight the loaded copy is discarded and the difference is
 *   put to the author as a conflict.
 * - One save in flight. A save asked for while another is running is folded
 *   into it: the running one finishes, and one more is sent if the tree
 *   changed since. That is also what keeps a double click on a dashboard
 *   that has no id yet from creating two.
 * - Every update names the revision it was based on and takes the new one
 *   from the response. A refusal (409) is never retried on its own: it is
 *   shown, and the author chooses to load the other copy, to overwrite it
 *   on purpose, or to carry on editing.
 */

import { useSyncExternalStore } from 'react';
import { t } from '@apache-superset/core/translation';
import type DashboardProvider from './DashboardProvider';
import type { DocumentNode } from './DashboardProvider';
import {
  DashboardV2ConflictError,
  fetchDashboardV2,
  saveDashboardV2,
} from './persistence';
import type { DashboardV2 } from './persistence';
import { provider, useDashboardRevision } from './store';

/** Why a dashboard could not be opened. */
export type LoadFailure = 'not-found' | 'forbidden' | 'invalid' | 'failed';

/** The other copy the author has to decide about. */
export interface SessionConflict {
  /** The revision the server holds, when it is known. */
  revision: number | undefined;
  /**
   * `save`: the server refused a save. `load`: the tree was edited while the
   * dashboard was still loading, so the loaded copy was not applied.
   */
  source: 'save' | 'load';
}

export interface DashboardSessionState {
  /** `ready` is the only status in which the tree may be edited or saved. */
  status: 'loading' | 'ready' | 'error';
  /** What the route calls this dashboard; `undefined` for one never saved. */
  ref: string | undefined;
  /** The saved row behind the tree; `undefined` until first saved. */
  dashboardId: number | undefined;
  uuid: string | undefined;
  /** The revision the tree was loaded from or last saved as. */
  baseRevision: number | undefined;
  changedOn: string | undefined;
  saving: boolean;
  conflict: SessionConflict | undefined;
  loadFailure: LoadFailure | undefined;
  /** How many structural repairs the last load made (see `sanitizeDocument`). */
  repairs: number;
}

export type SaveOutcome =
  | { status: 'saved'; id: number; created: boolean }
  /** The server holds a newer copy; `state.conflict` says which. */
  | { status: 'conflict' }
  | { status: 'error'; error: unknown }
  /** Nothing was sent: the session is not in a state that can be saved. */
  | { status: 'skipped' }
  /** The session turned to another dashboard before the answer came back. */
  | { status: 'superseded' };

/** The two requests a session makes, replaceable for a test. */
export interface SessionApi {
  fetch: typeof fetchDashboardV2;
  save: typeof saveDashboardV2;
}

const ROOT_ID = 'root';

const BLANK_STATE: DashboardSessionState = {
  status: 'ready',
  ref: undefined,
  dashboardId: undefined,
  uuid: undefined,
  baseRevision: undefined,
  changedOn: undefined,
  saving: false,
  conflict: undefined,
  loadFailure: undefined,
  repairs: 0,
};

const failureOf = (error: unknown): LoadFailure => {
  if (error instanceof Response) {
    if (error.status === 404) return 'not-found';
    if (error.status === 403) return 'forbidden';
  }
  return 'failed';
};

/**
 * The name the row carries, put where the builder reads a name from.
 *
 * A dashboard's name is edited on the root node and sent as
 * `dashboard_title` on save. A document written by anything other than this
 * builder may carry the name on the row alone, and without this it would
 * open untitled and be renamed to the placeholder by its first save.
 */
const withRowTitle = (
  nodes: Record<string, DocumentNode>,
  rowTitle: string | undefined,
): Record<string, DocumentNode> => {
  const root = nodes[ROOT_ID];
  const title = root?.props?.title;
  if (!root || !rowTitle || (typeof title === 'string' && title !== '')) {
    return nodes;
  }
  return {
    ...nodes,
    [ROOT_ID]: { ...root, props: { ...root.props, title: rowTitle } },
  };
};

export class DashboardSession {
  private state: DashboardSessionState = BLANK_STATE;

  private listeners = new Set<() => void>();

  /** Bumped whenever the session turns to a different dashboard. */
  private epoch = 0;

  private loadController: AbortController | undefined;

  /** The store's document version that matches what the server holds. */
  private savedVersion: number;

  private inFlightSave: Promise<SaveOutcome> | undefined;

  private resaveRequested = false;

  /**
   * The route ref a first save is about to move this page to. Opening that
   * one ref is the same dashboard under its new name, not a navigation, and
   * must not reload what was just written.
   */
  private adoptRef: string | undefined;

  /** Set when a loaded copy was discarded in favour of edits made meanwhile. */
  private loadDiscarded = false;

  constructor(
    private readonly store: DashboardProvider,
    private readonly api: SessionApi = {
      fetch: fetchDashboardV2,
      save: saveDashboardV2,
    },
  ) {
    this.savedVersion = store.getDocumentVersion();
  }

  public subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  public getState = (): DashboardSessionState => this.state;

  private setState(patch: Partial<DashboardSessionState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach(listener => listener());
  }

  /** Whether the tree holds edits the server does not. */
  public isDirty = (): boolean =>
    this.state.status === 'ready' &&
    this.store.getDocumentVersion() !== this.savedVersion;

  /** Drops whatever is in flight; nothing already sent can land after this. */
  private supersede(): void {
    this.epoch += 1;
    this.loadController?.abort();
    this.loadController = undefined;
    this.inFlightSave = undefined;
    this.resaveRequested = false;
  }

  /**
   * Turns the session to the dashboard the route names: a saved one by its
   * ref, or a blank unsaved one when there is no ref.
   */
  public open(ref: string | undefined): void {
    if (
      ref !== undefined &&
      ref === this.adoptRef &&
      this.state.status === 'ready' &&
      String(this.state.dashboardId) === ref
    ) {
      this.adoptRef = undefined;
      this.setState({ ref });
      return;
    }
    this.adoptRef = undefined;
    this.supersede();
    if (ref === undefined) {
      this.loadDiscarded = false;
      this.store.newDocument();
      this.savedVersion = this.store.getDocumentVersion();
      this.setState(BLANK_STATE);
      return;
    }
    this.load(ref);
  }

  /** Loads the current dashboard again, discarding the tree in memory. */
  public reload(): void {
    const ref =
      this.state.ref ??
      (this.state.dashboardId === undefined
        ? undefined
        : String(this.state.dashboardId));
    if (ref === undefined) return;
    this.supersede();
    this.load(ref);
  }

  /**
   * The page is going away. Nothing is reset, since there is nothing left to
   * show it to, but nothing still in flight may land on whatever is opened
   * next.
   */
  public close(): void {
    const pending = this.adoptRef;
    this.supersede();
    if (this.state.saving) this.setState({ saving: false });
    if (pending !== undefined) {
      // The route of a dashboard that has no id and the route of one that
      // has are different routes, so moving from the first to the second
      // after a first save unmounts this page and mounts it again: a close
      // immediately followed by the open that adopts. Both happen in one
      // synchronous pass, so the adoption is kept for exactly that long and
      // a later, unrelated visit to the same route loads from the server.
      Promise.resolve().then(() => {
        if (this.adoptRef === pending) this.adoptRef = undefined;
      });
    }
  }

  private async load(ref: string): Promise<void> {
    const { epoch } = this;
    const controller = new AbortController();
    this.loadController = controller;
    this.loadDiscarded = false;
    // Blanked before the request rather than when it answers: until then the
    // tree would be the previous dashboard's under this one's name.
    this.store.newDocument();
    const versionAtStart = this.store.getDocumentVersion();
    this.savedVersion = versionAtStart;
    this.setState({ ...BLANK_STATE, status: 'loading', ref });

    let result: DashboardV2;
    try {
      result = await this.api.fetch(ref, { signal: controller.signal });
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.setState({ status: 'error', loadFailure: failureOf(error) });
      return;
    }
    if (epoch !== this.epoch) return;
    this.loadController = undefined;

    // A numeric ref is an id, and an answer about a different id is not the
    // answer to this request, whatever produced it.
    if (/^\d+$/.test(ref) && result.id !== Number(ref)) {
      this.setState({ status: 'error', loadFailure: 'failed' });
      return;
    }

    const meta = {
      dashboardId: result.id,
      uuid: result.uuid,
      changedOn: result.changed_on,
    };

    if (this.store.getDocumentVersion() !== versionAtStart) {
      // Something wrote to the tree while this was loading. Those edits are
      // kept; the loaded copy is not applied over them, and since the tree
      // is then based on no revision at all, saving has to be a decision.
      this.loadDiscarded = true;
      this.setState({
        ...meta,
        status: 'ready',
        baseRevision: undefined,
        conflict: { revision: result.revision, source: 'load' },
      });
      return;
    }

    let repairs = 0;
    try {
      repairs = this.store.loadDocument(
        withRowTitle(result.document?.nodes ?? {}, result.dashboard_title),
      ).length;
    } catch {
      // No root, too many nodes, nested too deep: it is the document that is
      // wrong here, not the request.
      this.setState({ status: 'error', loadFailure: 'invalid' });
      return;
    }
    this.savedVersion = this.store.getDocumentVersion();
    this.setState({
      ...meta,
      status: 'ready',
      baseRevision: result.revision,
      repairs,
    });
  }

  /**
   * Writes the tree to the server: created when it has no id yet, updated
   * against the revision it was based on otherwise.
   */
  public save(): Promise<SaveOutcome> {
    if (this.state.status !== 'ready') {
      return Promise.resolve({ status: 'skipped' });
    }
    if (this.inFlightSave) {
      this.resaveRequested = true;
      return this.inFlightSave;
    }
    if (this.loadDiscarded) {
      // Based on nothing the server ever sent, so there is no revision to
      // send back and an update would be a blind overwrite.
      this.setState({
        conflict: this.state.conflict ?? {
          revision: undefined,
          source: 'load',
        },
      });
      return Promise.resolve({ status: 'conflict' });
    }
    const running: Promise<SaveOutcome> = this.runSave().finally(() => {
      if (this.inFlightSave === running) this.inFlightSave = undefined;
    });
    this.inFlightSave = running;
    return running;
  }

  private async runSave(): Promise<SaveOutcome> {
    const { epoch } = this;
    let created = false;
    let savedId = 0;
    this.setState({ saving: true });

    for (;;) {
      this.resaveRequested = false;
      const version = this.store.getDocumentVersion();
      const root = this.store.getRoot();
      const title =
        typeof root.props?.title === 'string' ? root.props.title : '';
      const id = this.state.dashboardId;
      let saved: DashboardV2;
      try {
        // Sequential on purpose: the next request is only decided once this
        // one has answered.
        // eslint-disable-next-line no-await-in-loop
        saved = await this.api.save({
          id,
          title: title || t('Untitled dashboard'),
          nodes: this.store.getDocument(),
          baseRevision: this.state.baseRevision,
        });
      } catch (error) {
        if (epoch !== this.epoch) return { status: 'superseded' };
        if (error instanceof DashboardV2ConflictError) {
          this.setState({
            saving: false,
            conflict: { revision: error.revision, source: 'save' },
          });
          return { status: 'conflict' };
        }
        this.setState({ saving: false });
        return { status: 'error', error };
      }
      if (epoch !== this.epoch) return { status: 'superseded' };

      this.savedVersion = version;
      savedId = saved.id;
      if (id === undefined) {
        created = true;
        this.adoptRef = String(saved.id);
      }
      this.setState({
        dashboardId: saved.id,
        uuid: saved.uuid,
        changedOn: saved.changed_on,
        baseRevision: saved.revision,
        conflict: undefined,
      });

      if (
        !this.resaveRequested ||
        this.store.getDocumentVersion() === version
      ) {
        break;
      }
    }

    this.setState({ saving: false });
    return { status: 'saved', id: savedId, created };
  }

  /**
   * Saves over the copy the server holds, on purpose: the save is based on
   * the server's own revision, read fresh when the conflict did not say.
   */
  public async overwrite(): Promise<SaveOutcome> {
    const { conflict, dashboardId, status } = this.state;
    if (
      status !== 'ready' ||
      conflict === undefined ||
      dashboardId === undefined ||
      this.inFlightSave
    ) {
      return { status: 'skipped' };
    }
    const { epoch } = this;
    let { revision } = conflict;
    if (revision === undefined) {
      this.setState({ saving: true });
      try {
        revision = (await this.api.fetch(dashboardId)).revision;
      } catch (error) {
        if (epoch !== this.epoch) return { status: 'superseded' };
        this.setState({ saving: false });
        return { status: 'error', error };
      }
      if (epoch !== this.epoch) return { status: 'superseded' };
    }
    this.loadDiscarded = false;
    this.setState({ conflict: undefined, baseRevision: revision });
    return this.save();
  }

  /** Gives up the tree in memory for the copy the server holds. */
  public reloadTheirs(): void {
    this.reload();
  }

  /**
   * Carries on editing. Nothing is resolved by this: the tree is still based
   * on a revision the server has moved past, so the next save meets the same
   * refusal and asks again.
   */
  public dismissConflict(): void {
    if (this.state.conflict !== undefined) {
      this.setState({ conflict: undefined });
    }
  }

  /** Test helper: back to a blank, unsaved session with no listeners. */
  public reset(): void {
    this.supersede();
    this.adoptRef = undefined;
    this.loadDiscarded = false;
    this.listeners.clear();
    this.state = BLANK_STATE;
    this.savedVersion = this.store.getDocumentVersion();
  }
}

/** The session of the builder's own store. */
export const dashboardSession = new DashboardSession(provider);

/**
 * The session's state plus whether the tree has unsaved edits. `dirty` is
 * read from the store rather than kept in the state, so it is subscribed to
 * the store's own revision.
 */
export function useDashboardSession(): DashboardSessionState & {
  dirty: boolean;
} {
  useDashboardRevision(provider);
  const state = useSyncExternalStore(
    dashboardSession.subscribe,
    dashboardSession.getState,
  );
  return { ...state, dirty: dashboardSession.isDirty() };
}

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
import { v4 as uuidv4 } from 'uuid';
import { t } from '@apache-superset/core/translation';
import type DashboardProvider from './DashboardProvider';
import type { DocumentNode } from './DashboardProvider';
import {
  DashboardV2ConflictError,
  fetchDashboardV2,
  isAmbiguousSaveFailure,
  readNodeErrors,
  sameDocumentNodes,
  saveDashboardV2,
  updateDashboardPublication,
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
  published: boolean;
  canEdit: boolean;
  canPublish: boolean;
  publishing: boolean;
  saving: boolean;
  conflict: SessionConflict | undefined;
  loadFailure: LoadFailure | undefined;
  /** How many structural repairs the last load made (see `sanitizeDocument`). */
  repairs: number;
  /**
   * What the last refused save said about particular widgets, by node id.
   * Drawn on those widgets (see `WidgetView`). A widget's lines go when its
   * properties are edited or it is removed, since they were about properties
   * it no longer has; all of them go when a save starts and when the session
   * turns to another dashboard.
   */
  nodeErrors: Readonly<Record<string, readonly string[]>>;
}

/**
 * Set on an outcome that is not `saved` when the run nevertheless created
 * the dashboard before it ended: a first save that went through, followed by
 * a second request (edits made meanwhile) that did not. The row exists under
 * `id`, and whoever reports the outcome has to move the page to it, or the
 * address stays the one of a dashboard that was never saved.
 */
interface CreationMade {
  created?: true;
  id?: number;
}

export type SaveOutcome =
  | { status: 'saved'; id: number; created: boolean }
  /** The server holds a newer copy; `state.conflict` says which. */
  | ({ status: 'conflict' } & CreationMade)
  | ({ status: 'error'; error: unknown } & CreationMade)
  /** Nothing was sent: the session is not in a state that can be saved. */
  | { status: 'skipped' }
  /** The session turned to another dashboard before the answer came back. */
  | { status: 'superseded' };

export type PublicationOutcome =
  | { status: 'changed'; published: boolean }
  | { status: 'skipped' | 'superseded' | 'error' };

/** The two requests a session makes, replaceable for a test. */
export interface SessionApi {
  fetch: typeof fetchDashboardV2;
  save: typeof saveDashboardV2;
  publish?: typeof updateDashboardPublication;
}

const ROOT_ID = 'root';

/** The revision a create stores, by contract. */
const INITIAL_REVISION = 1;

/** One object for "none", so a state that still has none is the same state. */
const NO_NODE_ERRORS: Readonly<Record<string, readonly string[]>> =
  Object.freeze({});

const BLANK_STATE: DashboardSessionState = {
  nodeErrors: NO_NODE_ERRORS,
  status: 'ready',
  ref: undefined,
  dashboardId: undefined,
  uuid: undefined,
  baseRevision: undefined,
  changedOn: undefined,
  published: false,
  canEdit: true,
  canPublish: false,
  publishing: false,
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

/** Visibility and permissions are reported by the server for the saved row. */
const dashboardStatus = (dashboard: DashboardV2) => ({
  published: dashboard.published === true,
  canEdit: dashboard.can_edit === true,
  canPublish: dashboard.can_publish === true,
});

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

  /** The store snapshot that matches what the server holds. */
  private savedStateId: number;

  private inFlightSave: Promise<SaveOutcome> | undefined;

  private inFlightPublication: Promise<PublicationOutcome> | undefined;

  private publicationController: AbortController | undefined;

  private resaveRequested = false;

  /**
   * The route ref a first save is about to move this page to. Opening that
   * one ref is the same dashboard under its new name, not a navigation, and
   * must not reload what was just written.
   */
  private adoptRef: string | undefined;

  /** Set when a loaded copy was discarded in favour of edits made meanwhile. */
  private loadDiscarded = false;

  /**
   * The uuid the unsaved document will be created under. Made up once per
   * unsaved document and sent with every attempt to create it, so an attempt
   * whose answer was lost and the retry that follows are one create.
   */
  private createUuid: string | undefined;

  /**
   * The trees sent under `createUuid`, one per attempt. Whichever attempt
   * the server took, what it stored is one of these, and a row found under
   * the uuid holding anything else has been saved by someone since.
   */
  private createAttempts: Record<string, DocumentNode>[] = [];

  /**
   * Set when the dashboard a lost create made was found holding a document
   * this session never sent. The tree is then based on no revision the
   * server handed to this session, and saving has to be a decision, exactly
   * as after a discarded load.
   */
  private foreignCopy: SessionConflict | undefined;

  /**
   * An update that got no answer, when the server could not be asked whether
   * it took it either. Kept until the next answer about this dashboard, so a
   * refusal of the retry can be told apart from someone else's save.
   */
  private unconfirmedSave:
    | {
        id: number;
        uuid: string | undefined;
        nodes: Record<string, DocumentNode>;
        baseRevision: number | undefined;
        stateId: number;
      }
    | undefined;

  /**
   * The properties each widget named by `state.nodeErrors` had in the
   * document the server refused. A widget whose properties are no longer
   * that object has been edited since.
   */
  private refusedProps = new Map<string, DocumentNode['props']>();

  /** Set while the store is watched for edits to a widget with errors. */
  private stopWatchingRefused: (() => void) | undefined;

  constructor(
    private readonly store: DashboardProvider,
    private readonly api: SessionApi = {
      fetch: fetchDashboardV2,
      save: saveDashboardV2,
    },
  ) {
    this.savedStateId = store.getDocumentStateId();
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

  /**
   * Records what a refused save said about particular widgets of `sent`,
   * the document that was refused, and keeps it only for as long as it is
   * about what is on screen.
   */
  private setNodeErrors(
    nodeErrors: Record<string, string[]>,
    sent: Record<string, DocumentNode>,
  ): void {
    this.refusedProps = new Map(
      Object.keys(nodeErrors).map((id): [string, DocumentNode['props']] => [
        id,
        sent[id]?.props,
      ]),
    );
    this.setState({ saving: false, nodeErrors });
    // A widget edited or removed while the save was away is already past
    // what the server looked at.
    this.dropOutdatedNodeErrors();
    if (
      this.stopWatchingRefused === undefined &&
      Object.keys(this.state.nodeErrors).length > 0
    ) {
      this.stopWatchingRefused = this.store.subscribe(
        this.dropOutdatedNodeErrors,
      );
    }
  }

  /**
   * Drops the errors of every widget that was removed or whose properties
   * were edited since the save that raised them. Moving or resizing a widget
   * leaves its properties, and so its errors, as they are.
   */
  private dropOutdatedNodeErrors = (): void => {
    const { nodeErrors } = this.state;
    const ids = Object.keys(nodeErrors);
    const current = ids.filter(id => {
      const node = this.store.getNode(id);
      return node !== undefined && node.props === this.refusedProps.get(id);
    });
    if (current.length === 0) {
      this.stopWatchingRefused?.();
      this.stopWatchingRefused = undefined;
      this.refusedProps = new Map();
    }
    if (current.length !== ids.length) {
      this.setState({
        nodeErrors:
          current.length === 0
            ? NO_NODE_ERRORS
            : Object.fromEntries(current.map(id => [id, nodeErrors[id]])),
      });
    }
  };

  /** Whether the tree holds edits the server does not. */
  public isDirty = (): boolean =>
    this.state.status === 'ready' &&
    this.store.getDocumentStateId() !== this.savedStateId;

  /** Drops whatever is in flight; nothing already sent can land after this. */
  private supersede(): void {
    this.epoch += 1;
    this.loadController?.abort();
    this.loadController = undefined;
    this.inFlightSave = undefined;
    this.publicationController?.abort();
    this.publicationController = undefined;
    this.inFlightPublication = undefined;
    this.resaveRequested = false;
    this.unconfirmedSave = undefined;
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
    // Another document, saved or not, is not the one the uuid was made for.
    this.createUuid = undefined;
    this.createAttempts = [];
    this.foreignCopy = undefined;
    if (ref === undefined) {
      this.loadDiscarded = false;
      this.store.newDocument();
      this.savedStateId = this.store.getDocumentStateId();
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
    if (this.state.saving || this.state.publishing) {
      this.setState({ saving: false, publishing: false });
    }
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
    this.foreignCopy = undefined;
    // Blanked before the request rather than when it answers: until then the
    // tree would be the previous dashboard's under this one's name.
    this.store.newDocument();
    const versionAtStart = this.store.getDocumentVersion();
    this.savedStateId = this.store.getDocumentStateId();
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
      ...dashboardStatus(result),
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
    this.savedStateId = this.store.getDocumentStateId();
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
    if (this.inFlightPublication) {
      const { epoch } = this;
      return this.inFlightPublication.then(() =>
        epoch === this.epoch ? this.save() : { status: 'superseded' },
      );
    }
    if (this.inFlightSave) {
      this.resaveRequested = true;
      return this.inFlightSave;
    }
    if (this.loadDiscarded || this.foreignCopy !== undefined) {
      // Based on nothing the server ever sent, so there is no revision to
      // send back and an update would be a blind overwrite.
      this.setState({
        conflict: this.state.conflict ??
          this.foreignCopy ?? {
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

  /** Change visibility of the last saved copy of this dashboard. */
  public togglePublication(): Promise<PublicationOutcome> {
    const { status, dashboardId, published, canPublish, conflict } = this.state;
    if (
      status !== 'ready' ||
      dashboardId === undefined ||
      !canPublish ||
      this.inFlightSave ||
      this.inFlightPublication ||
      conflict ||
      (!published && this.isDirty())
    ) {
      return Promise.resolve({ status: 'skipped' });
    }
    const epoch = this.epoch;
    const controller = new AbortController();
    this.publicationController = controller;
    const next = !published;
    const publish = this.api.publish ?? updateDashboardPublication;
    const running = Promise.resolve()
      .then(() => publish(dashboardId, next, controller.signal))
      .then((changedOn): PublicationOutcome => {
        if (epoch !== this.epoch) return { status: 'superseded' };
        this.setState({
          published: next,
          changedOn: changedOn ?? this.state.changedOn,
        });
        return { status: 'changed', published: next };
      })
      .catch((): PublicationOutcome => ({
        status: epoch === this.epoch ? 'error' : 'superseded',
      }))
      .finally(() => {
        if (this.inFlightPublication === running) {
          this.inFlightPublication = undefined;
          this.publicationController = undefined;
          this.setState({ publishing: false });
        }
      });
    this.inFlightPublication = running;
    this.setState({ publishing: true });
    return running;
  }

  /**
   * Asks the server what it holds after a save that got no usable answer.
   *
   * `stored`: the server holds exactly what was sent, so the save went
   * through and only its acknowledgement was lost. `conflict`: it holds
   * something else, newer than the base. `not-stored`: it holds the base, or
   * (for a create) nothing under the uuid that was sent. `unknown`: it could
   * not be asked either.
   */
  private async reconcile(sent: {
    id: number | undefined;
    uuid: string | undefined;
    nodes: Record<string, DocumentNode>;
    baseRevision: number | undefined;
  }): Promise<
    | { kind: 'stored'; dashboard: DashboardV2 }
    | { kind: 'conflict'; revision: number | undefined }
    | { kind: 'not-stored' }
    | { kind: 'unknown' }
  > {
    const ref = sent.id ?? sent.uuid;
    if (ref === undefined) return { kind: 'unknown' };
    let current: DashboardV2;
    try {
      current = await this.api.fetch(ref);
    } catch (error) {
      // Nothing under a uuid only this client knows means the create never
      // landed. Any other failure says nothing about what is stored.
      return sent.id === undefined &&
        error instanceof Response &&
        error.status === 404
        ? { kind: 'not-stored' }
        : { kind: 'unknown' };
    }
    if (sent.id === undefined) {
      // The row exists. Whether it holds this tree or an earlier one is for
      // the caller to tell, exactly as with a create the server replayed.
      return { kind: 'stored', dashboard: { ...current, replayed: true } };
    }
    if (current.revision === sent.baseRevision) return { kind: 'not-stored' };
    if (
      sent.baseRevision !== undefined &&
      current.revision === sent.baseRevision + 1 &&
      sameDocumentNodes(current.document?.nodes, sent.nodes)
    ) {
      return { kind: 'stored', dashboard: current };
    }
    return { kind: 'conflict', revision: current.revision };
  }

  private async runSave(): Promise<SaveOutcome> {
    const { epoch } = this;
    let created = false;
    let savedId = 0;
    // What a first save did, said with every way this can end: the row a
    // create made exists whatever happened to the requests after it, and the
    // page has to be moved to it.
    const creation = (): { created?: true; id?: number } =>
      created ? { created: true, id: savedId } : {};
    this.setState({ saving: true, nodeErrors: NO_NODE_ERRORS });

    for (;;) {
      this.resaveRequested = false;
      const stateId = this.store.getDocumentStateId();
      const root = this.store.getRoot();
      const title =
        typeof root.props?.title === 'string' ? root.props.title : '';
      const id = this.state.dashboardId;
      const { baseRevision } = this.state;
      const nodes = this.store.getDocument();
      if (id === undefined && this.createUuid === undefined) {
        // One per unsaved document, and the same one on every retry of its
        // create: that is what lets the server recognise a repeat instead of
        // creating a second dashboard.
        this.createUuid = uuidv4();
        this.createAttempts = [];
      }
      if (id === undefined) this.createAttempts.push(nodes);
      const uuid = id === undefined ? this.createUuid : undefined;
      let saved: DashboardV2 | undefined;
      try {
        // Sequential on purpose: the next request is only decided once this
        // one has answered.
        // eslint-disable-next-line no-await-in-loop
        saved = await this.api.save({
          id,
          title: title || t('Untitled dashboard'),
          nodes,
          baseRevision,
          uuid,
        });
      } catch (error) {
        if (epoch !== this.epoch) return { status: 'superseded' };
        let failure = error;
        const unconfirmed = this.unconfirmedSave;
        if (
          failure instanceof DashboardV2ConflictError &&
          id !== undefined &&
          unconfirmed !== undefined &&
          unconfirmed.id === id
        ) {
          // An earlier save of this dashboard never got an answer and the
          // server could not be asked about it then. A refusal that follows
          // may be about that very save: the server took it, and the
          // revision this one named is the one before it.
          // eslint-disable-next-line no-await-in-loop
          const verdict = await this.reconcile(unconfirmed);
          if (epoch !== this.epoch) return { status: 'superseded' };
          this.unconfirmedSave = undefined;
          if (verdict.kind === 'stored') {
            this.setState({
              baseRevision: verdict.dashboard.revision,
              changedOn: verdict.dashboard.changed_on,
              ...dashboardStatus(verdict.dashboard),
            });
            if (this.store.getDocumentStateId() === unconfirmed.stateId) {
              saved = verdict.dashboard;
            } else {
              // The author's own save, with edits made since: sent again on
              // the revision that save produced.
              continue;
            }
          }
        } else if (isAmbiguousSaveFailure(failure)) {
          // eslint-disable-next-line no-await-in-loop
          const verdict = await this.reconcile({
            id,
            uuid,
            nodes,
            baseRevision,
          });
          if (epoch !== this.epoch) return { status: 'superseded' };
          if (verdict.kind === 'stored') {
            saved = verdict.dashboard;
          } else if (verdict.kind === 'conflict') {
            failure = new DashboardV2ConflictError(verdict.revision);
          } else if (verdict.kind === 'unknown' && id !== undefined) {
            this.unconfirmedSave = { id, uuid, nodes, baseRevision, stateId };
          }
        }
        if (saved === undefined) {
          if (failure instanceof DashboardV2ConflictError) {
            this.setState({
              saving: false,
              conflict: { revision: failure.revision, source: 'save' },
            });
            return { status: 'conflict', ...creation() };
          }
          // eslint-disable-next-line no-await-in-loop
          const nodeErrors = await readNodeErrors(failure);
          if (epoch !== this.epoch) return { status: 'superseded' };
          this.setNodeErrors(nodeErrors, nodes);
          return { status: 'error', error: failure, ...creation() };
        }
      }
      if (epoch !== this.epoch) return { status: 'superseded' };
      this.unconfirmedSave = undefined;

      if (id === undefined) {
        created = true;
        savedId = saved.id;
        this.adoptRef = String(saved.id);
        this.createUuid = undefined;
        const attempts = this.createAttempts;
        this.createAttempts = [];
        const storedNodes = saved.document?.nodes;
        const holdsThisTree =
          saved.replayed !== true || sameDocumentNodes(storedNodes, nodes);
        if (
          !holdsThisTree &&
          saved.revision !== INITIAL_REVISION &&
          !attempts.some(attempt => sameDocumentNodes(storedNodes, attempt))
        ) {
          // The dashboard was created by an earlier attempt whose answer was
          // lost, and it has been saved since by someone who is not this
          // session (the author's other tab, say). The row is adopted, the
          // document it holds is not: writing this tree over it is for the
          // author to choose.
          this.foreignCopy = { revision: saved.revision, source: 'save' };
          this.setState({
            saving: false,
            dashboardId: saved.id,
            uuid: saved.uuid,
            changedOn: saved.changed_on,
            ...dashboardStatus(saved),
            baseRevision: undefined,
            conflict: this.foreignCopy,
          });
          return { status: 'conflict', ...creation() };
        }
        this.setState({
          dashboardId: saved.id,
          uuid: saved.uuid,
          changedOn: saved.changed_on,
          ...dashboardStatus(saved),
          baseRevision: saved.revision,
          conflict: undefined,
        });
        if (!holdsThisTree) {
          // The dashboard was created by an earlier attempt whose answer was
          // lost, and what it holds is still the tree as it was then. This
          // tree is written to it as an update, on the revision it is at.
          continue;
        }
      } else if (
        baseRevision !== undefined &&
        saved.revision !== undefined &&
        saved.revision !== baseRevision + 1
      ) {
        // An accepted update is the base plus one, by contract. Any other
        // number means the revision in the answer is not the one this save
        // produced, so adopting it would base the next save on a document
        // that is not the one on screen.
        this.setState({
          saving: false,
          conflict: { revision: saved.revision, source: 'save' },
        });
        return { status: 'conflict', ...creation() };
      } else {
        savedId = saved.id;
        this.setState({
          dashboardId: saved.id,
          uuid: saved.uuid,
          changedOn: saved.changed_on,
          ...dashboardStatus(saved),
          baseRevision: saved.revision,
          conflict: undefined,
        });
      }
      this.savedStateId = stateId;

      if (
        !this.resaveRequested ||
        this.store.getDocumentStateId() === stateId
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
    this.foreignCopy = undefined;
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
    this.createUuid = undefined;
    this.createAttempts = [];
    this.foreignCopy = undefined;
    this.loadDiscarded = false;
    this.listeners.clear();
    this.stopWatchingRefused?.();
    this.stopWatchingRefused = undefined;
    this.refusedProps = new Map();
    this.state = BLANK_STATE;
    this.savedStateId = this.store.getDocumentStateId();
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

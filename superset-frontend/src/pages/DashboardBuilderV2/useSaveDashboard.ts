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
import { useCallback, useEffect, useRef } from 'react';
import { useHistory } from 'react-router-dom';
import { t } from '@apache-superset/core/translation';
import { getClientErrorObject } from '@superset-ui/core';
import { useToasts } from 'src/components/MessageToasts/withToasts';
import { dashboardSession } from 'src/core/dashboard/session';
import { provider } from 'src/core/dashboard/store';
import type { SaveOutcome } from 'src/core/dashboard/session';

/** The route a saved Dashboard v2 is edited at. */
export const dashboardV2Path = (id: number): string => `/dashboard/v2/${id}/`;

/**
 * Why a save failed, in the server's words, and which widgets it was about.
 *
 * The API answers an invalid document with a `message` and, when the fault
 * is in particular widgets' properties, an `errors` object keyed by node id.
 * Anything that is not such a response is described as well as the shared
 * client-error reader can.
 */
export async function describeSaveError(
  error: unknown,
): Promise<{ message: string; nodeIds: string[] }> {
  if (error instanceof Response) {
    try {
      const body: unknown = await error.clone().json();
      if (typeof body === 'object' && body !== null) {
        const { message, errors } = body as Record<string, unknown>;
        return {
          message: typeof message === 'string' ? message : '',
          nodeIds:
            typeof errors === 'object' && errors !== null
              ? Object.keys(errors)
              : [],
        };
      }
    } catch {
      // Not JSON; fall through to the generic reader.
    }
  }
  const { message, error: summary } = await getClientErrorObject(
    error as Parameters<typeof getClientErrorObject>[0],
  );
  const reason = message || summary;
  return { message: typeof reason === 'string' ? reason : '', nodeIds: [] };
}

/**
 * What an outcome of a save is told to the author as, and done about.
 *
 * Shared by everything that can ask for a save, so each of them says the
 * same thing: the header's button, the conflict dialog's overwrite, and the
 * prompt that interrupts leaving with unsaved edits.
 *
 * A conflict is not reported here. The session records it and the conflict
 * dialog is drawn from that record, wherever the save was asked from.
 *
 * Nothing is done once the component that asked has unmounted: the answer
 * to a save can arrive after the author has left the page, and neither a
 * toast about a page they are no longer on nor a redirect back to it is
 * wanted then.
 */
export function useSaveOutcome(): (outcome: SaveOutcome) => Promise<void> {
  const history = useHistory();
  const { addDangerToast, addSuccessToast } = useToasts();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  return useCallback(
    async (outcome: SaveOutcome): Promise<void> => {
      if (!mounted.current) return;
      // A dashboard that was created is moved to whatever else the run came
      // to: a first save that went through and a follow-up that was refused
      // still leave a saved dashboard behind, and an address that goes on
      // naming the unsaved page would open a blank one on the next refresh.
      // Replaced rather than pushed: the unsaved page it came from is not
      // somewhere Back should return to, since it would be a second blank
      // dashboard rather than the one just saved.
      if (
        'created' in outcome &&
        outcome.created === true &&
        outcome.id !== undefined
      ) {
        history?.replace(dashboardV2Path(outcome.id));
      }
      if (outcome.status === 'saved') {
        addSuccessToast(t('Dashboard saved'));
      } else if (outcome.status === 'error') {
        const { message, nodeIds } = await describeSaveError(outcome.error);
        if (!mounted.current) return;
        // A refusal about particular widgets is only useful if the author
        // can find them, so the first one still on the dashboard is
        // selected: its properties are where the problem is fixed.
        const firstRejected = nodeIds.find(
          id => provider.getNode(id) !== undefined,
        );
        if (firstRejected !== undefined) provider.setSelection(firstRejected);
        addDangerToast(
          message !== ''
            ? t('This dashboard could not be saved: %s', message)
            : t('Sorry, there was an error saving this dashboard'),
        );
      }
    },
    [addDangerToast, addSuccessToast, history],
  );
}

/** Saves the dashboard through the session and reports how it went. */
export function useSaveDashboard(): () => Promise<SaveOutcome> {
  const report = useSaveOutcome();
  return useCallback(async () => {
    const outcome = await dashboardSession.save();
    await report(outcome);
    return outcome;
  }, [report]);
}

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
import type { CopilotHost, DashboardProposal } from '@nxtbi/copilot';

type RunInput = Parameters<CopilotHost['run']>[0];

export function createSessionTransport(base: string) {
  async function post(
    path: 'run' | 'approve',
    body: unknown,
    accept: string,
    signal: AbortSignal,
  ) {
    const session: RequestInit = {
      credentials: 'same-origin',
      redirect: 'error',
      signal,
    };
    const csrf = await fetch(`${base}/api/v1/security/csrf_token/`, {
      ...session,
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    if (!csrf.ok) return csrf;
    const data: { result?: unknown } = await csrf.json();
    if (typeof data.result !== 'string' || !data.result) {
      throw new Error('The Superset session could not be verified.');
    }
    return fetch(`${base}/api/v1/nxtbi_copilot/${path}`, {
      ...session,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: accept,
        'X-CSRFToken': data.result,
      },
      body: JSON.stringify(body),
    });
  }

  return {
    run(input: RunInput, signal: AbortSignal): Promise<Response> {
      return post('run', input, 'text/event-stream', signal);
    },
    async approve(
      proposal: DashboardProposal,
      signal: AbortSignal,
    ): Promise<{ id: number; url: string }> {
      const response = await post(
        'approve',
        proposal,
        'application/json',
        signal,
      );
      if (!response.ok)
        throw new Error(
          `Superset rejected the dashboard approval (HTTP ${response.status}).`,
        );
      const { id, url }: { id?: unknown; url?: unknown } =
        await response.json();
      if (
        typeof id !== 'number' ||
        !Number.isSafeInteger(id) ||
        id < 1 ||
        typeof url !== 'string'
      ) {
        throw new Error('Superset returned an invalid dashboard response.');
      }
      return { id, url };
    },
  };
}

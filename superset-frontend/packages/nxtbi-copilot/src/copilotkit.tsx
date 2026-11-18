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

import {
  CopilotKitProvider,
  HttpAgent,
  useRenderActivityMessage,
} from '@copilotkit/react-core/v2';
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { z } from 'zod';
import {
  A2uiRenderer,
  applyA2uiMessage,
  initialA2uiState,
  parseA2uiMessage,
  updateA2uiData,
  type A2uiAction,
  type A2uiRendererProps,
  type A2uiState,
} from './a2ui';

const contentSchema = z.object({
  batches: z.custom<unknown[][]>(
    (value: unknown) =>
      Array.isArray(value) &&
      value.length <= 13 &&
      value.every(batch => Array.isArray(batch) && batch.length <= 32),
  ),
});
type Content = z.infer<typeof contentSchema>;
type Preferences = Pick<
  A2uiRendererProps,
  'locale' | 'direction' | 'catalogs' | 'allowedActions' | 'onAction'
>;
const RendererPreferences = createContext<Preferences>({});
const activityType = 'a2ui-surface';

function SafeActivity({ content }: { content: Content }) {
  const options = useContext(RendererPreferences);
  const [state, setState] = useState(initialA2uiState);
  const seen = useRef(new WeakSet<unknown[]>());

  useEffect(() => {
    const unseen = content.batches.filter(batch => !seen.current.has(batch));
    for (const batch of unseen) seen.current.add(batch);
    if (!unseen.length) return;
    setState(previous =>
      unseen.reduce<A2uiState>((current, batch) => {
        try {
          return batch.reduce<A2uiState>(
            (next, operation) =>
              applyA2uiMessage(
                next,
                parseA2uiMessage(operation, options.catalogs),
                options.catalogs,
              ),
            current,
          );
        } catch {
          return current;
        }
      }, previous),
    );
  }, [content.batches, options.catalogs]);

  return (
    <A2uiRenderer
      {...options}
      state={state}
      onDataChange={(surfaceId, path, value) =>
        setState(previous => updateA2uiData(previous, surfaceId, path, value))
      }
    />
  );
}

const supportedActivities = [
  { activityType, content: contentSchema, render: SafeActivity },
];

function ReceiveActivity({ operations }: { operations: unknown[][] }) {
  const { renderActivityMessage } = useRenderActivityMessage();
  return renderActivityMessage({
    id: 'nxtbi-a2ui-surfaces',
    role: 'activity',
    activityType,
    content: { batches: operations },
  });
}

/**
 * CopilotKit v2 generative UI bridge. The host transports authenticated
 * AG-UI events, and CopilotKit dispatches the registered A2UI renderer.
 */
export function CopilotKitActivities({
  operations,
  onAction,
  runUrl,
  ...options
}: Preferences & {
  operations: unknown[][];
  onAction: (action: A2uiAction) => void;
  runUrl: string;
}) {
  const agents = useMemo(
    () => ({ default: new HttpAgent({ url: runUrl }) }),
    [runUrl],
  );
  return (
    <RendererPreferences.Provider value={{ ...options, onAction }}>
      <CopilotKitProvider
        selfManagedAgents={agents}
        renderActivityMessages={supportedActivities}
      >
        <ReceiveActivity operations={operations} />
      </CopilotKitProvider>
    </RendererPreferences.Provider>
  );
}

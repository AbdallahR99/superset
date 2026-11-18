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

export interface AgUiEvent {
  type: string;
  [key: string]: unknown;
}

const MAX_FRAME_LENGTH = 1024 * 1024;

function parseFrame(frame: string): AgUiEvent | undefined {
  const data = frame
    .split(/\r?\n/u)
    .filter(line => line.startsWith('data:'))
    .map(line => line.slice(5).replace(/^ /u, ''))
    .join('\n');
  if (!data || data === '[DONE]') return undefined;
  const payload: unknown = JSON.parse(data);
  if (
    typeof payload !== 'object' ||
    payload === null ||
    !('type' in payload) ||
    typeof payload.type !== 'string'
  ) {
    throw new Error('Invalid AG-UI event');
  }
  return payload as AgUiEvent;
}

/** Parse AG-UI SSE without losing boundaries across UTF-8 chunks. */
export async function* readAgUiEvents(response: Response): AsyncGenerator<AgUiEvent> {
  if (!response.ok) throw new Error(`Copilot HTTP ${response.status}`);
  if (
    !response.body ||
    !response.headers.get('Content-Type')?.includes('text/event-stream')
  ) {
    throw new Error('Copilot did not return an AG-UI stream');
  }

  const reader = response.body.getReader();
  const utf8 = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += utf8.decode(value, { stream: !done });
      let separator = /\r?\n\r?\n/u.exec(buffer);
      while (separator) {
        if (separator.index > MAX_FRAME_LENGTH) throw new Error('AG-UI event too large');
        const event = parseFrame(buffer.slice(0, separator.index));
        buffer = buffer.slice(separator.index + separator[0].length);
        if (event) yield event;
        separator = /\r?\n\r?\n/u.exec(buffer);
      }
      if (buffer.length > MAX_FRAME_LENGTH) throw new Error('AG-UI event too large');
      if (done) {
        const event = parseFrame(buffer);
        if (event) yield event;
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export function a2uiOperations(event: AgUiEvent): unknown[] | undefined {
  if (
    event.type !== 'ACTIVITY_SNAPSHOT' ||
    event.activityType !== 'a2ui-surface' ||
    typeof event.content !== 'object' ||
    !event.content ||
    !('a2ui_operations' in event.content)
  ) return undefined;
  const operations = event.content.a2ui_operations;
  return Array.isArray(operations) && operations.length <= 32 ? operations : undefined;
}

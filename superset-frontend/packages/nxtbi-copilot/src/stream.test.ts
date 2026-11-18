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

/** @jest-environment node */
import { fitAgUiInput, readAgUiEvents } from './stream';
import type { AgUiRunInput } from './contracts';

test('reads chunked UTF-8 and multiple AG-UI events per response', async () => {
  const text =
    'data: {"type":"TEXT_MESSAGE_CONTENT","delta":"مرحبا"}\r\n\r\n' +
    ': heartbeat\n\ndata: {"type":"RUN_FINISHED"}\n\n';
  const encoded = new TextEncoder().encode(text);
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < encoded.length; i += 3) {
        controller.enqueue(encoded.slice(i, i + 3));
      }
      controller.close();
    },
  });
  const response = new Response(stream, {
    headers: { 'Content-Type': 'text/event-stream' },
  });
  const events = [];
  for await (const event of readAgUiEvents(response)) events.push(event);
  expect(events).toEqual([
    { type: 'TEXT_MESSAGE_CONTENT', delta: 'مرحبا' },
    { type: 'RUN_FINISHED' },
  ]);
});

test('rejects non-stream responses', async () => {
  const events = readAgUiEvents(new Response('Unauthorized', { status: 401 }));
  await expect(events.next()).rejects.toThrow('401');
});

test('keeps the newest complete turns within the gateway byte budget', () => {
  const input: AgUiRunInput = {
    threadId: 'thread',
    runId: 'run',
    context: [],
    state: {},
    tools: [],
    forwardedProps: {},
    messages: [
      { id: 'first', role: 'user', content: 'س'.repeat(3000) },
      { id: 'reply', role: 'assistant', content: 'ب'.repeat(6500) },
      { id: 'latest', role: 'user', content: 'م'.repeat(3000) },
    ],
  };
  expect(fitAgUiInput(input).messages).toEqual(input.messages.slice(2));
  expect(input.messages).toHaveLength(3);
});

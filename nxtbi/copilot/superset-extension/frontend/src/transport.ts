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
import type {
  CopilotConversation,
  CopilotHost,
  CopilotTextMessage,
  CopilotUploadedDataset,
  DashboardProposal,
} from '@nxtbi/copilot';

type RunInput = Parameters<CopilotHost['run']>[0];

const uploadMessages = {
  en: {
    permission:
      'Your Superset account does not have permission to upload CSV files.',
    destination:
      'No single upload destination is available. Ask a Superset administrator to configure a CSV upload database.',
    size: 'The CSV exceeds the upload limit.',
    invalid:
      'Superset could not read this CSV. Check that it has a header row and uses UTF-8.',
    pending: 'This CSV import is still being registered. Retry in a moment.',
    registration:
      'The file was stored, but Superset could not register its dataset. Ask a Superset administrator to check the import.',
    generic: 'Superset could not import the CSV. Try again.',
  },
  ar: {
    permission: 'لا يملك حسابك في Superset إذن رفع ملفات CSV.',
    destination:
      'لا توجد وجهة رفع محددة. اطلب من مسؤول Superset تهيئة قاعدة بيانات لرفع ملفات CSV.',
    size: 'يتجاوز ملف CSV الحد الأقصى لحجم الرفع.',
    invalid:
      'تعذّر على Superset قراءة الملف. تأكد من وجود صف للعناوين ومن استخدام ترميز UTF-8.',
    pending: 'لا يزال تسجيل ملف CSV جاريًا. أعد المحاولة بعد قليل.',
    registration:
      'تم تخزين الملف، لكن تعذّر تسجيل مجموعة البيانات. اطلب من مسؤول Superset مراجعة الاستيراد.',
    generic: 'تعذّر على Superset استيراد الملف. حاول مجددًا.',
  },
};

function readConversation(value: unknown): CopilotConversation | undefined {
  if (typeof value !== 'object' || value === null) return undefined;
  const item = value as Partial<CopilotConversation>;
  if (
    typeof item.threadId !== 'string' ||
    typeof item.updatedAt !== 'string' ||
    !Array.isArray(item.messages) ||
    !item.messages.length ||
    !item.messages.every(
      (message: CopilotTextMessage | null) =>
        message &&
        typeof message.id === 'string' &&
        (message.role === 'user' || message.role === 'assistant') &&
        typeof message.content === 'string',
    )
  ) {
    return undefined;
  }
  const dashboard = item.savedDashboard;
  return {
    threadId: item.threadId,
    updatedAt: item.updatedAt,
    messages: item.messages,
    savedDashboard:
      dashboard &&
      Number.isSafeInteger(dashboard.id) &&
      dashboard.id > 0 &&
      dashboard.url === `/dashboard/v2/${dashboard.id}/`
        ? { id: dashboard.id, url: dashboard.url }
        : undefined,
  };
}

export function createSessionTransport(base: string, language = () => 'en') {
  const uploadIds = new WeakMap<File, string>();
  async function write(
    path: 'run' | 'approve' | 'history' | 'upload/',
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
    const multipart = body instanceof FormData;
    return fetch(`${base}/api/v1/nxtbi_copilot/${path}`, {
      ...session,
      method: path === 'history' ? 'PUT' : 'POST',
      headers: {
        ...(!multipart && { 'Content-Type': 'application/json' }),
        Accept: accept,
        'X-CSRFToken': data.result,
      },
      body: multipart ? body : JSON.stringify(body),
    });
  }

  return {
    run(input: RunInput, signal: AbortSignal): Promise<Response> {
      return write('run', input, 'text/event-stream', signal);
    },
    async uploadDataset(
      file: File,
      signal: AbortSignal,
    ): Promise<CopilotUploadedDataset> {
      const messages = language().startsWith('ar')
        ? uploadMessages.ar
        : uploadMessages.en;
      const id = uploadIds.get(file) ?? crypto.randomUUID();
      uploadIds.set(file, id);
      const body = new FormData();
      body.append('file', file);
      body.append('upload_id', id);
      const response = await write('upload/', body, 'application/json', signal);
      if (!response.ok) {
        const problem: { code?: unknown } | null = await response
          .json()
          .catch(() => null);
        if (problem?.code === 'upload_destination')
          throw new Error(messages.destination);
        if (problem?.code === 'upload_conflict')
          throw new Error(messages.pending);
        if (problem?.code === 'upload_registration')
          throw new Error(messages.registration);
      }
      switch (response.status) {
        case 200:
        case 201:
          break;
        case 401:
        case 403:
          throw new Error(messages.permission);
        case 404:
        case 503:
          throw new Error(messages.destination);
        case 413:
          throw new Error(messages.size);
        case 400:
        case 422:
          throw new Error(messages.invalid);
        default:
          throw new Error(messages.generic);
      }
      const dataset: { id?: unknown; name?: unknown } | null =
        await response.json();
      if (
        !dataset ||
        typeof dataset.id !== 'number' ||
        !Number.isSafeInteger(dataset.id) ||
        dataset.id < 1 ||
        dataset.id > 2147483647 ||
        typeof dataset.name !== 'string' ||
        !dataset.name.trim() ||
        dataset.name.length > 256
      ) {
        throw new Error(messages.generic);
      }
      return { id: dataset.id, name: dataset.name };
    },
    history: {
      async list(signal: AbortSignal): Promise<CopilotConversation[]> {
        const response = await fetch(`${base}/api/v1/nxtbi_copilot/history`, {
          credentials: 'same-origin',
          redirect: 'error',
          cache: 'no-store',
          headers: { Accept: 'application/json' },
          signal,
        });
        if (!response.ok) throw new Error('Could not load Copilot history.');
        const { result }: { result?: unknown } = await response.json();
        if (!Array.isArray(result)) {
          throw new Error('Superset returned invalid Copilot history.');
        }
        return result.flatMap(entry => readConversation(entry) ?? []);
      },
      async save(conversation: CopilotConversation, signal: AbortSignal) {
        const response = await write(
          'history',
          conversation,
          'application/json',
          signal,
        );
        if (!response.ok) throw new Error('Could not save Copilot history.');
      },
    },
    async approve(
      proposal: DashboardProposal,
      signal: AbortSignal,
    ): Promise<{ id: number; url: string }> {
      const response = await write(
        'approve',
        proposal,
        'application/json',
        signal,
      );
      if (response.status !== 200 && response.status !== 201)
        throw new Error(
          `Superset rejected the dashboard approval (HTTP ${response.status}).`,
        );
      const { id, url }: { id?: unknown; url?: unknown } =
        await response.json();
      if (
        typeof id !== 'number' ||
        !Number.isSafeInteger(id) ||
        id < 1 ||
        url !== `/dashboard/v2/${id}/`
      ) {
        throw new Error('Superset returned an invalid dashboard response.');
      }
      return { id, url };
    },
  };
}

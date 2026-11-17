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
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import {
  A2uiRenderer,
  applyA2uiMessage,
  initialA2uiState,
  parseA2uiMessage,
  updateA2uiData,
  type A2uiAction,
} from './a2ui';
import {
  readProposal,
  type AgUiRunInput,
  type CopilotHost,
  type CopilotTextMessage,
  type DashboardProposal,
} from './contracts';
import { a2uiOperations, readAgUiEvents } from './stream';

const english = {
  title: 'NxtBI Copilot',
  description: 'Ask a question or describe the dashboard you need.',
  placeholder: 'Ask Copilot',
  send: 'Send',
  stop: 'Stop',
  working: 'Working…',
  submit: 'Continue with these values.',
  streamError: 'The response ended early. Please try again.',
  uiError: 'This interactive view could not be loaded.',
  proposal: 'Dashboard proposal',
  dashboardTitle: 'Dashboard title',
  review: 'Review and save',
  confirm: 'Save dashboard',
  cancel: 'Back',
  saved: 'Dashboard saved.',
  saveError: 'Could not save this dashboard. Check your access and selections.',
};

const arabic: typeof english = {
  title: 'مساعد NxtBI',
  description: 'اطرح سؤالاً أو صف لوحة المعلومات التي تحتاج إليها.',
  placeholder: 'اسأل المساعد',
  send: 'إرسال',
  stop: 'إيقاف',
  working: 'جارٍ العمل…',
  submit: 'المتابعة بهذه القيم.',
  streamError: 'انقطع الرد. يرجى المحاولة مرة أخرى.',
  uiError: 'تعذّر تحميل هذه الواجهة التفاعلية.',
  proposal: 'اقتراح لوحة معلومات',
  dashboardTitle: 'عنوان لوحة المعلومات',
  review: 'مراجعة وحفظ',
  confirm: 'حفظ لوحة المعلومات',
  cancel: 'رجوع',
  saved: 'تم حفظ لوحة المعلومات.',
  saveError: 'تعذّر حفظ اللوحة. تحقّق من صلاحياتك واختياراتك.',
};

interface CopilotPanelProps {
  host: CopilotHost;
  /** An optional CopilotKit or other host activity surface. */
  renderActivities?: (
    operations: unknown[][],
    onAction: (action: A2uiAction) => void,
  ) => ReactNode;
}

const MAX_MESSAGES = 16;
const MAX_PROMPT = 3000;
const MAX_ANSWER = 24000;

function wireHistory(history: CopilotTextMessage[]): CopilotTextMessage[] {
  let remaining = 27000;
  const result: CopilotTextMessage[] = [];
  for (const message of [...history].reverse()) {
    const content = message.content.slice(0, Math.min(remaining, 6500));
    if (!content) break;
    result.unshift({ ...message, content });
    remaining -= content.length;
  }
  return result[0]?.role === 'assistant' ? result.slice(1) : result;
}

function buildContext(host: CopilotHost): AgUiRunInput['context'] {
  const context = { ...host.context(), locale: host.locale ?? 'en' };
  return Object.entries(context)
    .filter(
      ([description, value]) =>
        ['locale', 'page', 'active_dashboard_id', 'active_chart_id', 'active_dataset_id'].includes(
          description,
        ) && (typeof value === 'string' || typeof value === 'number'),
    )
    .map(([description, value]) => ({
      description,
      value: String(value).slice(0, 160),
    }));
}

/** Host-neutral chat, streamed A2UI and a separate trusted approval control. */
export function CopilotPanel({ host, renderActivities }: CopilotPanelProps) {
  const isArabic = host.locale?.startsWith('ar');
  const copy = isArabic ? arabic : english;
  const direction = host.direction ?? (isArabic ? 'rtl' : 'ltr');
  const [threadId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<CopilotTextMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [surface, setSurface] = useState(initialA2uiState);
  const [activities, setActivities] = useState<unknown[][]>([]);
  const [proposal, setProposal] = useState<DashboardProposal>();
  const [confirming, setConfirming] = useState(false);
  const connection = useRef<AbortController>();
  const mutation = useRef<AbortController>();
  const viewport = useRef<HTMLDivElement>(null);
  const catalogs = host.catalog ? [host.catalog] : undefined;

  useEffect(
    () => () => {
      connection.current?.abort();
      mutation.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [messages, surface, proposal]);

  async function send(value: string, action?: A2uiAction) {
    const text = value.trim().slice(0, MAX_PROMPT);
    if (!text || connection.current || mutation.current) return;
    const controller = new AbortController();
    connection.current = controller;
    const history = [
      ...messages.slice(-(MAX_MESSAGES - 1)),
      { id: crypto.randomUUID(), role: 'user' as const, content: text },
    ];
    const reply: CopilotTextMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
    };
    let complete = false;
    setMessages(history);
    setStreaming(true);
    setError('');
    setNotice('');
    setDraft('');
    setProposal(undefined);
    setConfirming(false);

    try {
      const response = await host.run(
        {
          threadId,
          runId: crypto.randomUUID(),
          messages: wireHistory(history),
          tools: [],
          context: buildContext(host),
          state: {},
          forwardedProps: action ? { a2uiAction: action } : {},
        },
        controller.signal,
      );
      for await (const event of readAgUiEvents(response)) {
        if (controller.signal.aborted) break;
        if (event.type === 'RUN_FINISHED') complete = true;
        if (event.type === 'RUN_ERROR') throw new Error('The agent did not finish');
        if (
          ['TEXT_MESSAGE_CONTENT', 'TEXT_MESSAGE_CHUNK'].includes(event.type) &&
          typeof event.delta === 'string'
        ) {
          reply.content = (reply.content + event.delta).slice(0, MAX_ANSWER);
          setMessages([...history, { ...reply }]);
        }
        if (event.type === 'CUSTOM' && event.name === 'nxtbi.dashboard-proposal') {
          const next = readProposal(event.value);
          if (next) setProposal(next);
        }
        const operations = a2uiOperations(event);
        if (operations) {
          if (renderActivities) {
            setActivities(previous => [...previous.slice(-12), operations]);
          } else {
            try {
              const parsed = operations.map(item => parseA2uiMessage(item, catalogs));
              setSurface(previous => {
                try {
                  return parsed.reduce(
                    (result, message) => applyA2uiMessage(result, message, catalogs),
                    previous,
                  );
                } catch {
                  return previous;
                }
              });
            } catch {
              setError(copy.uiError);
            }
          }
        }
      }
      if (!complete && !controller.signal.aborted) throw new Error('Incomplete AG-UI run');
    } catch {
      if (!controller.signal.aborted) setError(copy.streamError);
    } finally {
      if (connection.current === controller) {
        connection.current = undefined;
        setStreaming(false);
      }
    }
  }

  function handleAction(action: A2uiAction) {
    if (host.onAction?.(action)) return;
    void send(action.action.userMessage || copy.submit, action);
  }

  async function approve() {
    if (!proposal || !host.approve || !confirming || mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setSaving(true);
    setError('');
    try {
      const result = await host.approve(proposal, controller.signal);
      if (controller.signal.aborted) return;
      setProposal(undefined);
      setConfirming(false);
      setNotice(copy.saved);
      host.navigate?.(result.url);
    } catch {
      if (!controller.signal.aborted) setError(copy.saveError);
    } finally {
      if (mutation.current === controller) {
        mutation.current = undefined;
        setSaving(false);
      }
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(draft);
  }

  return (
    <section className="nxtbi-copilot" aria-label={copy.title} dir={direction} lang={host.locale}>
      <div className="nxtbi-copilot__history" ref={viewport}>
        {!messages.length && <p className="nxtbi-copilot__intro">{copy.description}</p>}
        {messages.map(message => (
          <p key={message.id} className={`nxtbi-copilot__message nxtbi-copilot__message--${message.role}`} dir="auto">
            {message.content}
          </p>
        ))}
        {renderActivities ? (
          renderActivities(activities, handleAction)
        ) : (
          <A2uiRenderer
            state={surface}
            locale={host.locale}
            direction={direction}
            catalogs={catalogs}
            allowedActions={host.allowedActions}
            onAction={handleAction}
            onDataChange={(surfaceId, path, value) =>
              setSurface(previous => updateA2uiData(previous, surfaceId, path, value))
            }
          />
        )}
        {proposal && host.approve && (
          <section className="nxtbi-copilot__proposal" aria-label={copy.proposal}>
            <h3>{copy.proposal}</h3>
            <label>
              {copy.dashboardTitle}
              <input
                value={proposal.title}
                maxLength={256}
                disabled={saving}
                onChange={event => {
                  setConfirming(false);
                  setProposal({ ...proposal, title: event.target.value });
                }}
              />
            </label>
            {host.renderProposal?.(proposal, next => {
              if (saving) return;
              setConfirming(false);
              setProposal(next);
            })}
            {confirming ? (
              <div className="nxtbi-copilot__actions">
                <button type="button" disabled={saving} onClick={() => void approve()}>
                  {copy.confirm}
                </button>
                <button type="button" disabled={saving} onClick={() => setConfirming(false)}>
                  {copy.cancel}
                </button>
              </div>
            ) : (
              <button
                type="button"
                disabled={streaming || !proposal.title.trim()}
                onClick={() => setConfirming(true)}
              >
                {copy.review}
              </button>
            )}
          </section>
        )}
        {streaming && <p role="status">{copy.working}</p>}
        {notice && <p role="status">{notice}</p>}
        {error && <p className="nxtbi-copilot__error" role="alert">{error}</p>}
      </div>
      <form className="nxtbi-copilot__composer" onSubmit={submit}>
        <textarea
          rows={2}
          value={draft}
          aria-label={copy.placeholder}
          placeholder={copy.placeholder}
          onChange={event => setDraft(event.target.value)}
          maxLength={MAX_PROMPT}
        />
        {streaming ? (
          <button type="button" onClick={() => connection.current?.abort()}>{copy.stop}</button>
        ) : (
          <button type="submit" disabled={!draft.trim() || saving}>{copy.send}</button>
        )}
      </form>
    </section>
  );
}

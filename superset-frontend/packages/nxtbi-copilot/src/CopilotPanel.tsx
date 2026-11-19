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
  memo,
  useEffect,
  useId,
  useRef,
  useState,
  type AnchorHTMLAttributes,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from 'react';
import Markdown, { type MarkdownToJSX } from 'markdown-to-jsx/react';
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
  type CopilotConversation,
  type CopilotHost,
  type CopilotTextMessage,
  type CopilotUploadedDataset,
  type DashboardProposal,
} from './contracts';
import { a2uiOperations, fitAgUiInput, readAgUiEvents } from './stream';
import { CopilotIcon } from './CopilotIcon';

/** Only render a link when the browser resolves it to a supported protocol. */
function MarkdownLink({
  href,
  title,
  children,
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  if (href) {
    try {
      const { protocol } = new URL(href, 'https://copilot.invalid');
      if (['https:', 'http:', 'mailto:'].includes(protocol)) {
        return (
          <a href={href} title={title}>
            {children}
          </a>
        );
      }
    } catch {
      // Keep the label for a malformed destination.
    }
  }
  return <span>{children}</span>;
}

const markdownOptions: MarkdownToJSX.Options = {
  disableParsingRawHTML: true,
  ignoreHTMLBlocks: true,
  forceBlock: true,
  wrapper: null,
  overrides: {
    a: MarkdownLink,
    img: () => null,
    pre: { props: { dir: 'ltr' } },
    table: ({ children }: { children: ReactNode }) => (
      <div className="nxtbi-copilot__markdown-table">
        <table>{children}</table>
      </div>
    ),
  },
};

/** Render assistant text safely while new stream chunks arrive. */
const AssistantMarkdown = memo(function AssistantMarkdown({
  content,
  streaming,
}: {
  content: string;
  streaming: boolean;
}) {
  return (
    <div className="nxtbi-copilot__markdown" dir="auto">
      <Markdown
        options={{ ...markdownOptions, optimizeForStreaming: streaming }}
      >
        {content}
      </Markdown>
    </div>
  );
});

const starterIcons = ['data', 'dashboard', 'search'] as const;

const english = {
  title: 'NxtBI Copilot',
  welcome: 'What would you like to explore?',
  description:
    'Start with the data you can access and turn it into a dashboard.',
  suggestions: {
    data: {
      label: 'Explore datasets',
      prompt:
        'Show me the datasets I can access and help me choose useful metrics.',
    },
    dashboard: {
      label: 'Draft a dashboard',
      prompt:
        'Help me choose a dataset and draft a dashboard I can preview, save, and publish.',
    },
    search: {
      label: 'Find my dashboards',
      prompt: 'Find my dashboards',
    },
  },
  history: 'History',
  newChat: 'New chat',
  conversations: 'Recent conversations',
  loadingHistory: 'Loading conversations…',
  noHistory: 'Your conversations will appear here after you send a message.',
  historyError: 'Could not load your conversations.',
  retryHistory: 'Try again',
  historySaveError: 'Could not save this conversation to history.',
  speaker: 'Copilot',
  placeholder: 'Ask Copilot',
  send: 'Send',
  stop: 'Stop',
  working: 'Working…',
  submit: 'Continue with these values.',
  streamError: 'The response ended early. Please try again.',
  restorePrompt: 'Restore prompt',
  uiError: 'This interactive view could not be loaded.',
  proposal: 'Dashboard proposal',
  dashboardTitle: 'Dashboard title',
  review: 'Review and save',
  confirm: 'Save dashboard',
  cancel: 'Back',
  saved: 'Dashboard saved',
  saving: 'Saving…',
  openDashboard: 'Open dashboard',
  publishHint: 'Open the dashboard to review and publish it.',
  saveError: 'Could not save this dashboard. Check your access and selections.',
  chooseCsv: 'Choose CSV files',
  csvFiles: 'CSV files and datasets',
  importFiles: 'Import CSV files',
  retryImport: 'Retry failed imports',
  importing: 'Importing CSV files…',
  datasetReady: 'Datasets ready to use',
  removeFile: 'Remove',
  removeFromChat: 'Remove from chat',
  draftFromDataset: 'Draft dashboard from dataset',
  draftDatasetPrompt: (id: number) =>
    `Inspect dataset #${id} and draft a dashboard using its data.`,
  csvType: 'Choose a .csv file.',
  csvEmpty: 'This CSV is empty.',
  csvSize: 'Choose a CSV of 10 MiB or less.',
  csvError: 'Import failed. Check the CSV and your access, then retry.',
};

const arabic: typeof english = {
  title: 'مساعد NxtBI',
  welcome: 'ما الذي تريد استكشافه؟',
  description: 'ابدأ بالبيانات المتاحة لك وحوّلها إلى لوحة معلومات.',
  suggestions: {
    data: {
      label: 'استكشف مجموعات البيانات',
      prompt:
        'اعرض مجموعات البيانات المتاحة لي وساعدني في اختيار مقاييس مفيدة.',
    },
    dashboard: {
      label: 'جهّز مسودة لوحة معلومات',
      prompt:
        'ساعدني في اختيار مجموعة بيانات وإعداد مسودة لوحة معلومات لمعاينتها وحفظها ونشرها.',
    },
    search: {
      label: 'اعثر على لوحات معلوماتي',
      prompt: 'اعثر على لوحات معلوماتي',
    },
  },
  history: 'السجل',
  newChat: 'محادثة جديدة',
  conversations: 'المحادثات الأخيرة',
  loadingHistory: 'جارٍ تحميل المحادثات…',
  noHistory: 'ستظهر محادثاتك هنا بعد إرسال رسالة.',
  historyError: 'تعذّر تحميل محادثاتك.',
  retryHistory: 'حاول مرة أخرى',
  historySaveError: 'تعذّر حفظ هذه المحادثة في السجل.',
  speaker: 'المساعد',
  placeholder: 'اسأل المساعد',
  send: 'إرسال',
  stop: 'إيقاف',
  working: 'جارٍ العمل…',
  submit: 'المتابعة بهذه القيم.',
  streamError: 'انقطع الرد. يرجى المحاولة مرة أخرى.',
  restorePrompt: 'استعادة الطلب',
  uiError: 'تعذّر تحميل هذه الواجهة التفاعلية.',
  proposal: 'اقتراح لوحة معلومات',
  dashboardTitle: 'عنوان لوحة المعلومات',
  review: 'مراجعة وحفظ',
  confirm: 'حفظ لوحة المعلومات',
  cancel: 'رجوع',
  saved: 'تم حفظ لوحة المعلومات',
  saving: 'جارٍ الحفظ…',
  openDashboard: 'فتح لوحة المعلومات',
  publishHint: 'افتح لوحة المعلومات لمراجعتها ونشرها.',
  saveError: 'تعذّر حفظ اللوحة. تحقّق من صلاحياتك واختياراتك.',
  chooseCsv: 'اختر ملفات CSV',
  csvFiles: 'ملفات CSV ومجموعات البيانات',
  importFiles: 'استيراد ملفات CSV',
  retryImport: 'إعادة محاولة الاستيراد',
  importing: 'جارٍ استيراد ملفات CSV…',
  datasetReady: 'مجموعات بيانات جاهزة للاستخدام',
  removeFile: 'إزالة',
  removeFromChat: 'إزالة من المحادثة',
  draftFromDataset: 'أنشئ مسودة لوحة من مجموعة البيانات',
  draftDatasetPrompt: id =>
    `افحص مجموعة البيانات رقم ${id} وأنشئ مسودة لوحة معلومات باستخدام بياناتها.`,
  csvType: 'اختر ملفًا بامتداد .csv.',
  csvEmpty: 'ملف CSV هذا فارغ.',
  csvSize: 'اختر ملف CSV بحجم 10 ميبي بايت أو أقل.',
  csvError: 'تعذّر الاستيراد. تحقّق من ملف CSV وصلاحياتك وحاول مجددًا.',
};

interface CopilotPanelProps {
  host: CopilotHost;
  headerActions?: ReactNode;
  /** An optional CopilotKit or other host activity surface. */
  renderActivities?: (
    operations: unknown[][],
    onAction: (action: A2uiAction) => void,
  ) => ReactNode;
}

const MAX_MESSAGES = 16;
const MAX_PROMPT = 3000;
const MAX_ANSWER = 24000;
const HISTORY_TIMEOUT = 8000;
const SCROLL_MARGIN = 32;
const MAX_CSV_SIZE = 10 * 1024 * 1024;

type CsvAttachment =
  | { id: string; status: 'ready' | 'failed'; file: File }
  | {
      id: string;
      status: 'invalid';
      name: string;
      reason: 'csvType' | 'csvSize' | 'csvEmpty';
    }
  | { id: string; status: 'imported'; dataset: CopilotUploadedDataset };

function prepareAttachment(file: File): CsvAttachment {
  const id = crypto.randomUUID();
  if (!/\.csv$/i.test(file.name))
    return { id, status: 'invalid', name: file.name, reason: 'csvType' };
  if (file.size === 0)
    return { id, status: 'invalid', name: file.name, reason: 'csvEmpty' };
  if (file.size > MAX_CSV_SIZE)
    return { id, status: 'invalid', name: file.name, reason: 'csvSize' };
  return { id, status: 'ready', file };
}

function canApprove(proposal: DashboardProposal): boolean {
  return (
    Boolean(proposal.title.trim()) &&
    proposal.widgets.every(widget =>
      Boolean(
        widget.metric.trim() &&
        (widget.type !== 'echarts' || widget.dimension?.trim()),
      ),
    )
  );
}

function CopilotMark() {
  return (
    <span className="nxtbi-copilot__mark" aria-hidden="true">
      ✦
    </span>
  );
}

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

function buildContext(
  host: CopilotHost,
  uploadedDatasetId?: number,
  uploadedDatasetAction?: 'draft',
): AgUiRunInput['context'] {
  const context = {
    ...host.context(),
    uploaded_dataset_id: uploadedDatasetId,
    uploaded_dataset_action: uploadedDatasetId
      ? uploadedDatasetAction
      : undefined,
    locale: host.locale ?? 'en',
  };
  return Object.entries(context)
    .filter(
      ([description, value]) =>
        [
          'locale',
          'page',
          'active_dashboard_id',
          'active_chart_id',
          'active_dataset_id',
          'uploaded_dataset_id',
          'uploaded_dataset_action',
        ].includes(description) &&
        (typeof value === 'string' || typeof value === 'number'),
    )
    .map(([description, value]) => ({
      description,
      value: String(value).slice(0, 160),
    }));
}

/** Host-neutral chat, streamed A2UI and a separate trusted approval control. */
export function CopilotPanel({
  host,
  headerActions,
  renderActivities,
}: CopilotPanelProps) {
  const isArabic = host.locale?.startsWith('ar');
  const copy = isArabic ? arabic : english;
  const direction = host.direction ?? (isArabic ? 'rtl' : 'ltr');
  const historyId = useId();
  const datasetSelectionName = useId();
  const [threadId, setThreadId] = useState<string>(() => crypto.randomUUID());
  const [messages, setMessages] = useState<CopilotTextMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [attachments, setAttachments] = useState<CsvAttachment[]>([]);
  const [uploadedDatasetId, setUploadedDatasetId] = useState<number>();
  const [uploadProgress, setUploadProgress] = useState<{
    completed: number;
    total: number;
  }>();
  const [savedDashboard, setSavedDashboard] =
    useState<CopilotConversation['savedDashboard']>();
  const [error, setError] = useState('');
  const [failedPrompt, setFailedPrompt] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState<CopilotConversation[]>([]);
  const [historyStatus, setHistoryStatus] = useState<
    'idle' | 'loading' | 'ready' | 'error'
  >('idle');
  const [historySaveFailed, setHistorySaveFailed] = useState(false);
  const [historyRequest, setHistoryRequest] = useState(0);
  const [surface, setSurface] = useState(initialA2uiState);
  const [activities, setActivities] = useState<unknown[][]>([]);
  const [proposal, setProposal] = useState<DashboardProposal>();
  const [confirming, setConfirming] = useState(false);
  const connection = useRef<AbortController>();
  const mutation = useRef<AbortController>();
  const filePicker = useRef<HTMLInputElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  const catalogs = host.catalog ? [host.catalog] : undefined;
  const { history: archive } = host;
  const busy = streaming || saving || Boolean(uploadProgress);
  const pendingFiles = attachments.filter(item => 'file' in item);
  const hasImported = attachments.some(item => item.status === 'imported');

  useEffect(
    () => () => {
      connection.current?.abort();
      mutation.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (!historyOpen && followLatest.current && viewport.current)
      viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [historyOpen, messages, surface, proposal, savedDashboard, error]);

  useEffect(() => {
    if (!archive || !historyOpen) return undefined;
    const controller = new AbortController();
    setHistoryStatus('loading');
    void archive
      .list(
        AbortSignal.any([
          controller.signal,
          AbortSignal.timeout(HISTORY_TIMEOUT),
        ]),
      )
      .then(entries => {
        if (controller.signal.aborted) return;
        setConversations(entries);
        setHistoryStatus('ready');
      })
      .catch(() => {
        if (!controller.signal.aborted) setHistoryStatus('error');
      });
    return () => controller.abort();
  }, [archive, historyOpen, historyRequest]);

  async function remember(
    transcript: CopilotTextMessage[],
    dashboard = savedDashboard,
  ) {
    if (!archive) return;
    try {
      await archive.save(
        {
          threadId,
          messages: transcript,
          updatedAt: new Date().toISOString(),
          savedDashboard: dashboard,
        },
        AbortSignal.timeout(HISTORY_TIMEOUT),
      );
      setHistorySaveFailed(false);
    } catch {
      setHistorySaveFailed(true);
    }
  }

  function switchConversation(conversation?: CopilotConversation) {
    followLatest.current = true;
    setThreadId(conversation?.threadId ?? crypto.randomUUID());
    setMessages(conversation?.messages ?? []);
    setSavedDashboard(conversation?.savedDashboard);
    setSurface(initialA2uiState);
    setActivities([]);
    setProposal(undefined);
    setConfirming(false);
    setDraft('');
    setAttachments([]);
    setUploadedDatasetId(undefined);
    setError('');
    setFailedPrompt('');
    setHistorySaveFailed(false);
    setHistoryOpen(false);
    window.requestAnimationFrame(() => composer.current?.focus());
  }

  async function send(
    value: string,
    action?: A2uiAction,
    uploadedDatasetAction?: 'draft',
  ) {
    const text = value.trim().slice(0, MAX_PROMPT);
    if (!text || connection.current || mutation.current) return;
    const controller = new AbortController();
    connection.current = controller;
    const previous = messages.at(-1);
    const retry =
      failedPrompt === text &&
      previous?.role === 'user' &&
      previous.content === text;
    const history = retry
      ? messages
      : [
          ...messages.slice(-(MAX_MESSAGES - 1)),
          { id: crypto.randomUUID(), role: 'user' as const, content: text },
        ];
    const reply: CopilotTextMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
    };
    let complete = false;
    followLatest.current = true;
    setMessages(history);
    setStreaming(true);
    setError('');
    setFailedPrompt('');
    if (!uploadedDatasetAction) setDraft('');
    setProposal(undefined);
    setConfirming(false);

    const promptSaved = remember(history);
    try {
      const response = await host.run(
        fitAgUiInput({
          threadId,
          runId: crypto.randomUUID(),
          messages: wireHistory(history),
          tools: [],
          context: buildContext(host, uploadedDatasetId, uploadedDatasetAction),
          state: {},
          forwardedProps: action ? { a2uiAction: action } : {},
        }),
        controller.signal,
      );
      for await (const event of readAgUiEvents(response)) {
        if (controller.signal.aborted) break;
        if (event.type === 'RUN_FINISHED') complete = true;
        if (event.type === 'RUN_ERROR')
          throw new Error('The agent did not finish');
        if (
          ['TEXT_MESSAGE_CONTENT', 'TEXT_MESSAGE_CHUNK'].includes(event.type) &&
          typeof event.delta === 'string'
        ) {
          reply.content = (reply.content + event.delta).slice(0, MAX_ANSWER);
          setMessages([...history, { ...reply }]);
        }
        if (
          event.type === 'CUSTOM' &&
          event.name === 'nxtbi.dashboard-proposal'
        ) {
          const next = readProposal(event.value);
          if (next) setProposal(next);
        }
        const operations = a2uiOperations(event);
        if (operations) {
          if (renderActivities) {
            setActivities(previous => [...previous.slice(-12), operations]);
          } else {
            try {
              const parsed = operations.map(item =>
                parseA2uiMessage(item, catalogs),
              );
              setSurface(previous => {
                try {
                  return parsed.reduce(
                    (result, message) =>
                      applyA2uiMessage(result, message, catalogs),
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
      if (controller.signal.aborted) {
        setProposal(undefined);
      } else if (!complete) {
        throw new Error('Incomplete AG-UI run');
      }
    } catch {
      complete = false;
      setProposal(undefined);
      if (!controller.signal.aborted) {
        setMessages(history);
        setFailedPrompt(text);
        setError(copy.streamError);
      }
    } finally {
      await promptSaved;
      if (complete && reply.content && !controller.signal.aborted) {
        await remember([...history, { ...reply }]);
      }
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

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = '';
    const selected = files.map(prepareAttachment);
    setAttachments(previous => [...previous, ...selected]);
  }

  async function importFiles() {
    const upload = host.uploadDataset;
    if (
      !upload ||
      !pendingFiles.length ||
      connection.current ||
      mutation.current
    )
      return;
    const controller = new AbortController();
    mutation.current = controller;
    setUploadProgress({ completed: 0, total: pendingFiles.length });
    try {
      for (const [index, item] of pendingFiles.entries()) {
        let next: CsvAttachment;
        try {
          const dataset = await upload(item.file, controller.signal);
          if (
            !Number.isSafeInteger(dataset.id) ||
            dataset.id <= 0 ||
            !dataset.name.trim()
          )
            throw new Error('Invalid uploaded dataset');
          next = { id: item.id, status: 'imported', dataset };
        } catch {
          next = { ...item, status: 'failed' };
        }
        if (controller.signal.aborted) return;
        if (next.status === 'imported') {
          const { id } = next.dataset;
          setUploadedDatasetId(previous => previous ?? id);
        }
        setAttachments(previous =>
          previous.map(attachment =>
            attachment.id === item.id ? next : attachment,
          ),
        );
        setUploadProgress({ completed: index + 1, total: pendingFiles.length });
      }
    } finally {
      if (mutation.current === controller) {
        mutation.current = undefined;
        if (!controller.signal.aborted) setUploadProgress(undefined);
      }
    }
  }

  function removeAttachment(item: CsvAttachment) {
    setAttachments(previous =>
      previous.filter(candidate => candidate.id !== item.id),
    );
    if (item.status === 'imported' && item.dataset.id === uploadedDatasetId)
      setUploadedDatasetId(undefined);
    window.requestAnimationFrame(() => composer.current?.focus());
  }

  async function approve() {
    if (
      !proposal ||
      !host.approve ||
      !confirming ||
      mutation.current ||
      !canApprove(proposal)
    )
      return;
    const controller = new AbortController();
    mutation.current = controller;
    setSaving(true);
    setError('');
    try {
      const result = await host.approve(proposal, controller.signal);
      if (controller.signal.aborted) return;
      setProposal(undefined);
      setConfirming(false);
      setSavedDashboard(result);
      await remember(messages, result);
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
    <section
      className="nxtbi-copilot"
      aria-label={copy.title}
      dir={direction}
      lang={host.locale}
    >
      <header className="nxtbi-copilot__header">
        <div className="nxtbi-copilot__identity">
          <CopilotMark />
          <strong>{copy.title}</strong>
        </div>
        <div className="nxtbi-copilot__toolbar">
          {archive && (
            <button
              type="button"
              className="nxtbi-copilot__icon-button"
              aria-label={copy.history}
              title={copy.history}
              aria-expanded={historyOpen}
              aria-controls={historyOpen ? historyId : undefined}
              disabled={busy}
              onClick={() => setHistoryOpen(open => !open)}
            >
              <CopilotIcon name="history" />
            </button>
          )}
          {headerActions}
        </div>
      </header>
      {archive && historyOpen ? (
        <section
          id={historyId}
          className="nxtbi-copilot__history"
          aria-label={copy.conversations}
        >
          <div className="nxtbi-copilot__history-heading">
            <h3>{copy.conversations}</h3>
            <button type="button" onClick={() => switchConversation()}>
              {copy.newChat}
            </button>
          </div>
          {historyStatus === 'loading' && (
            <p role="status">{copy.loadingHistory}</p>
          )}
          {historyStatus === 'error' && (
            <div role="alert">
              <p>{copy.historyError}</p>
              <button
                type="button"
                onClick={() => setHistoryRequest(attempt => attempt + 1)}
              >
                {copy.retryHistory}
              </button>
            </div>
          )}
          {historyStatus === 'ready' &&
            (conversations.length ? (
              <ul className="nxtbi-copilot__conversations">
                {conversations.map(conversation => (
                  <li key={conversation.threadId}>
                    <button
                      type="button"
                      onClick={() => {
                        if (conversation.threadId === threadId)
                          setHistoryOpen(false);
                        else switchConversation(conversation);
                      }}
                    >
                      <strong dir="auto">
                        {
                          conversation.messages.find(
                            message => message.role === 'user',
                          )?.content
                        }
                      </strong>
                      <time dateTime={conversation.updatedAt}>
                        {new Date(conversation.updatedAt).toLocaleDateString(
                          host.locale,
                          { month: 'short', day: 'numeric' },
                        )}
                      </time>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p>{copy.noHistory}</p>
            ))}
        </section>
      ) : (
        <>
          <div
            className="nxtbi-copilot__history"
            ref={viewport}
            onScroll={event => {
              const { scrollHeight, scrollTop, clientHeight } =
                event.currentTarget;
              followLatest.current =
                scrollHeight - scrollTop - clientHeight <= SCROLL_MARGIN;
            }}
          >
            {!messages.length && (
              <div className="nxtbi-copilot__welcome">
                <h3>{copy.welcome}</h3>
                <p>{copy.description}</p>
                {host.approve && (
                  <div className="nxtbi-copilot__suggestions">
                    {starterIcons.map(icon => (
                      <button
                        type="button"
                        key={icon}
                        onClick={() => {
                          setDraft(copy.suggestions[icon].prompt);
                          composer.current?.focus();
                        }}
                      >
                        <CopilotIcon name={icon} />
                        {copy.suggestions[icon].label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {messages.map((message, index) => (
              <div
                key={message.id}
                className={`nxtbi-copilot__message nxtbi-copilot__message--${message.role}`}
              >
                {message.role === 'assistant' ? (
                  <>
                    <span className="nxtbi-copilot__speaker">
                      {copy.speaker}
                    </span>
                    <AssistantMarkdown
                      content={message.content}
                      streaming={streaming && index === messages.length - 1}
                    />
                  </>
                ) : (
                  <p dir="auto">{message.content}</p>
                )}
              </div>
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
                  setSurface(previous =>
                    updateA2uiData(previous, surfaceId, path, value),
                  )
                }
              />
            )}
            {proposal && host.approve && (
              <section
                className="nxtbi-copilot__proposal"
                aria-label={copy.proposal}
              >
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
                    <button
                      className="nxtbi-copilot__primary"
                      type="button"
                      disabled={busy}
                      onClick={() => void approve()}
                    >
                      {saving ? copy.saving : copy.confirm}
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => setConfirming(false)}
                    >
                      {copy.cancel}
                    </button>
                  </div>
                ) : (
                  <button
                    className="nxtbi-copilot__primary"
                    type="button"
                    disabled={busy || !canApprove(proposal)}
                    onClick={() => setConfirming(true)}
                  >
                    {copy.review}
                  </button>
                )}
              </section>
            )}
            {streaming && (
              <p className="nxtbi-copilot__working" role="status">
                {copy.working}
              </p>
            )}
            {savedDashboard && (
              <div className="nxtbi-copilot__saved">
                <div>
                  <strong role="status">{copy.saved}</strong>
                  {host.navigate && <p>{copy.publishHint}</p>}
                </div>
                {host.navigate && (
                  <button
                    className="nxtbi-copilot__primary"
                    type="button"
                    disabled={saving}
                    onClick={() => host.navigate?.(savedDashboard.url)}
                  >
                    {copy.openDashboard}
                  </button>
                )}
              </div>
            )}
            {historySaveFailed && (
              <p className="nxtbi-copilot__error" role="status">
                {copy.historySaveError}
              </p>
            )}
            {error && (
              <div className="nxtbi-copilot__feedback">
                <p className="nxtbi-copilot__error" role="alert">
                  {error}
                </p>
                {failedPrompt && !draft && (
                  <button
                    type="button"
                    onClick={() => {
                      setDraft(failedPrompt);
                      composer.current?.focus();
                    }}
                  >
                    {copy.restorePrompt}
                  </button>
                )}
              </div>
            )}
          </div>
          {host.uploadDataset && attachments.length > 0 && (
            <section
              className="nxtbi-copilot__uploads"
              aria-label={copy.csvFiles}
            >
              <p role="status" className="nxtbi-copilot__upload-status">
                {uploadProgress
                  ? copy.importing
                  : hasImported
                    ? copy.datasetReady
                    : null}
              </p>
              {uploadProgress && uploadProgress.total > 1 && (
                <progress
                  aria-label={copy.importing}
                  value={uploadProgress.completed}
                  max={uploadProgress.total}
                />
              )}
              <ul>
                {attachments.map(item => {
                  const imported = item.status === 'imported';
                  const name = imported
                    ? item.dataset.name
                    : item.status === 'invalid'
                      ? item.name
                      : item.file.name;
                  const problem =
                    item.status === 'invalid'
                      ? copy[item.reason]
                      : item.status === 'failed'
                        ? copy.csvError
                        : null;
                  const remove = imported
                    ? copy.removeFromChat
                    : copy.removeFile;
                  return (
                    <li key={item.id}>
                      <div className="nxtbi-copilot__upload-row">
                        {imported ? (
                          <label>
                            <input
                              type="radio"
                              name={datasetSelectionName}
                              checked={uploadedDatasetId === item.dataset.id}
                              disabled={busy}
                              onChange={() =>
                                setUploadedDatasetId(item.dataset.id)
                              }
                            />
                            <bdi>{name}</bdi>
                          </label>
                        ) : (
                          <bdi>{name}</bdi>
                        )}
                        <button
                          type="button"
                          disabled={busy}
                          aria-label={`${remove} ${name}`}
                          onClick={() => removeAttachment(item)}
                        >
                          {remove}
                        </button>
                      </div>
                      {problem && (
                        <p className="nxtbi-copilot__error" role="alert">
                          {problem}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
              <div className="nxtbi-copilot__upload-actions">
                {pendingFiles.length > 0 && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void importFiles()}
                  >
                    {pendingFiles.some(item => item.status === 'ready')
                      ? copy.importFiles
                      : copy.retryImport}
                  </button>
                )}
                {host.approve && uploadedDatasetId !== undefined && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void send(
                        copy.draftDatasetPrompt(uploadedDatasetId),
                        undefined,
                        'draft',
                      )
                    }
                  >
                    {copy.draftFromDataset}
                  </button>
                )}
              </div>
            </section>
          )}
          <form className="nxtbi-copilot__composer" onSubmit={submit}>
            {host.uploadDataset && (
              <>
                <input
                  ref={filePicker}
                  type="file"
                  accept=".csv,text/csv"
                  aria-label={copy.chooseCsv}
                  multiple
                  hidden
                  onChange={chooseFiles}
                />
                <button
                  type="button"
                  className="nxtbi-copilot__attach-button"
                  aria-label={copy.chooseCsv}
                  disabled={busy}
                  onClick={() => filePicker.current?.click()}
                >
                  <CopilotIcon name="attach" />
                  CSV
                </button>
              </>
            )}
            <textarea
              ref={composer}
              rows={2}
              value={draft}
              aria-label={copy.placeholder}
              placeholder={copy.placeholder}
              dir="auto"
              onChange={event => setDraft(event.target.value)}
              maxLength={MAX_PROMPT}
            />
            {streaming ? (
              <button type="button" onClick={() => connection.current?.abort()}>
                {copy.stop}
              </button>
            ) : (
              <button
                className="nxtbi-copilot__primary"
                type="submit"
                disabled={!draft.trim() || busy}
              >
                {copy.send}
              </button>
            )}
          </form>
        </>
      )}
    </section>
  );
}

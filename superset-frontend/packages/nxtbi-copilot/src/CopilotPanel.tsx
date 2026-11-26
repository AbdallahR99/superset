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
import MarkdownRenderer, { type MarkdownToJSX } from 'markdown-to-jsx/react';
import {
  A2uiRenderer,
  applyA2uiMessage,
  initialA2uiState,
  parseA2uiMessage,
  updateA2uiData,
  type A2uiAction,
  type A2uiState,
} from './a2ui';
import {
  dashboardLocale,
  dashboardTitleIn,
  editDashboardTitle,
  readCaptionSuggestions,
  readProposal,
  type AgUiRunInput,
  type CopilotConversation,
  type CopilotHost,
  type CopilotTextMessage,
  type CopilotUploadedDataset,
  type DashboardContentLocale,
  type DashboardLocalizationRequest,
  type DashboardProposal,
  type DashboardType,
} from './contracts';
import { a2uiOperations, fitAgUiInput, readAgUiEvents } from './stream';
import { CopilotIcon } from './CopilotIcon';
import { ExistingDatasetPicker } from './ExistingDatasetPicker';

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
      <MarkdownRenderer
        options={{ ...markdownOptions, optimizeForStreaming: streaming }}
      >
        {content}
      </MarkdownRenderer>
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
  interactiveResult: 'Interactive result',
  submit: 'Continue with these values.',
  streamError: 'The response ended early. Please try again.',
  restorePrompt: 'Restore prompt',
  uiError: 'This interactive view could not be loaded.',
  proposal: 'Dashboard proposal',
  dashboardTitle: 'Dashboard title',
  dashboardType: 'Dashboard format',
  classic: 'Classic (V1)',
  builder: 'Dashboard V2',
  contentLocale: 'Dashboard language',
  previewLocale: 'Preview language',
  suggestArabic: 'Suggest translations in Arabic',
  suggestEnglish: 'Suggest translations in English',
  suggestingTranslations: 'Suggesting translations…',
  translationReviewReady: 'Translations are ready to review.',
  cancelSuggestions: 'Cancel translation request',
  translationError: 'Could not suggest translations. Try again.',
  noSuggestions: 'Copilot returned no new captions.',
  suggestedTranslations: 'Suggested translations',
  currentTranslation: 'Current',
  suggestedTranslation: 'Suggested',
  applyTranslations: 'Apply translations',
  dismissSuggestions: 'Dismiss suggestions',
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
  draftExistingDatasetPrompt: (name: string) =>
    `Draft a dashboard using ${name}.`,
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
  interactiveResult: 'نتيجة تفاعلية',
  submit: 'المتابعة بهذه القيم.',
  streamError: 'انقطع الرد. يرجى المحاولة مرة أخرى.',
  restorePrompt: 'استعادة الطلب',
  uiError: 'تعذّر تحميل هذه الواجهة التفاعلية.',
  proposal: 'اقتراح لوحة معلومات',
  dashboardTitle: 'عنوان لوحة المعلومات',
  dashboardType: 'تنسيق لوحة المعلومات',
  classic: 'كلاسيكي (الإصدار الأول)',
  builder: 'لوحة المعلومات (الإصدار الثاني)',
  contentLocale: 'لغة لوحة المعلومات',
  previewLocale: 'لغة المعاينة',
  suggestArabic: 'اقتراح ترجمات إلى العربية',
  suggestEnglish: 'اقتراح ترجمات إلى الإنجليزية',
  suggestingTranslations: 'جارٍ اقتراح الترجمات…',
  translationReviewReady: 'الترجمات جاهزة للمراجعة.',
  cancelSuggestions: 'إلغاء طلب الترجمة',
  translationError: 'تعذّر اقتراح الترجمات. حاول مجددًا.',
  noSuggestions: 'لم يقترح المساعد عناوين جديدة.',
  suggestedTranslations: 'الترجمات المقترحة',
  currentTranslation: 'الحالي',
  suggestedTranslation: 'المقترح',
  applyTranslations: 'تطبيق الترجمات',
  dismissSuggestions: 'رفض الاقتراحات',
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
  draftExistingDatasetPrompt: name =>
    `أنشئ مسودة لوحة معلومات باستخدام مجموعة البيانات ${name}.`,
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
const MAX_ACTIVITY_BATCHES = 13;
const HISTORY_TIMEOUT = 8000;
const CAPTION_TIMEOUT = 30_000;
const SCROLL_MARGIN = 32;
const MAX_CSV_SIZE = 10 * 1024 * 1024;

interface InteractiveResult {
  surface: A2uiState;
  activities: unknown[][];
}

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

const dashboardLanguages = [
  { locale: 'en', direction: 'ltr', label: 'English' },
  { locale: 'ar', direction: 'rtl', label: 'العربية' },
] as const;

function DashboardLanguageOptions() {
  return dashboardLanguages.map(({ locale, direction, label }) => (
    <option key={locale} value={locale} lang={locale} dir={direction}>
      {label}
    </option>
  ));
}

function wireHistory(history: CopilotTextMessage[]): CopilotTextMessage[] {
  let remaining = 27000;
  const result: CopilotTextMessage[] = [];
  for (const message of [...history].reverse()) {
    if (!message.content) continue;
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
  dashboardType?: DashboardType,
  contentLocale?: DashboardContentLocale,
): AgUiRunInput['context'] {
  const context = {
    ...host.context(),
    uploaded_dataset_id: uploadedDatasetId,
    uploaded_dataset_action: uploadedDatasetId
      ? uploadedDatasetAction
      : undefined,
    locale: dashboardLocale(host.locale),
    dashboard_type: dashboardType,
    content_locale: contentLocale,
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
          'dashboard_type',
          'content_locale',
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
  const shellLocale = dashboardLocale(host.locale);
  const isArabic = shellLocale === 'ar';
  const copy = isArabic ? arabic : english;
  const direction = host.direction ?? (isArabic ? 'rtl' : 'ltr');
  const historyId = useId();
  const translationsId = useId();
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
  const [results, setResults] = useState<Record<string, InteractiveResult>>({});
  const [proposal, setProposal] = useState<DashboardProposal>();
  const [formatPreference, setFormatPreference] = useState<DashboardType>();
  const [languagePreference, setLanguagePreference] =
    useState<DashboardContentLocale>();
  const [previewLocale, setPreviewLocale] = useState<DashboardContentLocale>();
  const [confirming, setConfirming] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestions, setSuggestions] = useState<(string | null)[]>();
  const [suggestionError, setSuggestionError] = useState(false);
  const connection = useRef<AbortController>();
  const mutation = useRef<AbortController>();
  const captionRequest = useRef<AbortController>();
  const filePicker = useRef<HTMLInputElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  const suggestButton = useRef<HTMLButtonElement>(null);
  const dashboardTitleInput = useRef<HTMLInputElement>(null);
  const catalogs = host.catalog ? [host.catalog] : undefined;
  const { history: archive } = host;
  const busy = streaming || saving || Boolean(uploadProgress);
  const dashboardTypes = host.approve ? host.dashboardTypes : undefined;
  const dashboardType =
    formatPreference && dashboardTypes?.includes(formatPreference)
      ? formatPreference
      : dashboardTypes?.[0];
  const contentLocale = languagePreference ?? shellLocale;
  const canonicalLocale = proposal?.contentLocale ?? shellLocale;
  const draftLocale = previewLocale ?? canonicalLocale;
  const targetLocale = canonicalLocale === 'ar' ? 'en' : 'ar';
  const hasSuggestions = suggestions?.some(Boolean);
  const pendingFiles = attachments.filter(item => 'file' in item);
  const hasImported = attachments.some(item => item.status === 'imported');

  useEffect(
    () => () => {
      connection.current?.abort();
      mutation.current?.abort();
      captionRequest.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (!historyOpen && followLatest.current && viewport.current)
      viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [historyOpen, messages, results, proposal, savedDashboard, error]);

  useEffect(() => {
    if (!archive || !historyOpen) return undefined;
    const controller = new AbortController();
    setHistoryStatus('loading');
    archive
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
          messages: transcript.filter(message => message.content),
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

  function dismissTranslations() {
    captionRequest.current?.abort();
    captionRequest.current = undefined;
    setSuggesting(false);
    setSuggestions(undefined);
    setSuggestionError(false);
  }

  function returnToTranslationTrigger() {
    dismissTranslations();
    suggestButton.current?.focus();
  }

  function replaceProposal(next: DashboardProposal | undefined) {
    dismissTranslations();
    setProposal(next);
  }

  function switchConversation(conversation?: CopilotConversation) {
    followLatest.current = true;
    setThreadId(conversation?.threadId ?? crypto.randomUUID());
    setMessages(conversation?.messages ?? []);
    setSavedDashboard(conversation?.savedDashboard);
    setResults({});
    replaceProposal(undefined);
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

  async function suggestTranslations() {
    if (
      !proposal?.contentLocale ||
      !proposal.title.trim() ||
      proposal.widgets.length > 8 ||
      connection.current ||
      mutation.current ||
      captionRequest.current
    ) {
      return;
    }
    const request: DashboardLocalizationRequest = {
      sourceLocale: proposal.contentLocale,
      targetLocale,
      captions: [
        proposal.title.trim(),
        ...proposal.widgets.map(widget => widget.title?.trim() || null),
      ],
    };
    if (request.captions.some(caption => caption && caption.length > 256)) {
      setSuggestionError(true);
      return;
    }
    const controller = new AbortController();
    captionRequest.current = controller;
    setConfirming(false);
    setSuggesting(true);
    setSuggestions(undefined);
    setSuggestionError(false);
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(CAPTION_TIMEOUT),
    ]);
    try {
      const response = await host.run(
        {
          threadId,
          runId: crypto.randomUUID(),
          messages: [
            {
              id: crypto.randomUUID(),
              role: 'user',
              content: 'Suggest dashboard captions',
            },
          ],
          tools: [],
          state: {},
          context: [],
          forwardedProps: { dashboardLocalization: request },
        },
        signal,
      );
      let complete = false;
      let captions: (string | null)[] | undefined;
      for await (const event of readAgUiEvents(response)) {
        if (signal.aborted) break;
        if (event.type === 'RUN_ERROR')
          throw new Error('Caption request failed');
        if (event.type === 'RUN_FINISHED') {
          complete = true;
          break;
        }
        if (
          event.type === 'CUSTOM' &&
          event.name === 'nxtbi.dashboard-caption-suggestions'
        ) {
          captions = readCaptionSuggestions(event.value, request);
        }
      }
      if (!complete || !captions || signal.aborted)
        throw new Error('Incomplete caption suggestions');
      if (captionRequest.current === controller) {
        const titles = [proposal, ...proposal.widgets];
        setSuggestions(
          captions.map((caption, index) =>
            caption === titles[index].titleTranslations?.[targetLocale]
              ? null
              : caption,
          ),
        );
      }
    } catch {
      if (captionRequest.current === controller && !controller.signal.aborted)
        setSuggestionError(true);
    } finally {
      if (captionRequest.current === controller) {
        captionRequest.current = undefined;
        setSuggesting(false);
      }
    }
  }

  function applyTranslations() {
    if (!proposal || !suggestions) return;
    const [title, ...widgetTitles] = suggestions;
    replaceProposal({
      ...(title
        ? editDashboardTitle(proposal, canonicalLocale, targetLocale, title)
        : proposal),
      widgets: proposal.widgets.map((widget, index) => {
        const translated = widgetTitles[index];
        return translated
          ? editDashboardTitle(
              widget,
              canonicalLocale,
              targetLocale,
              translated,
            )
          : widget;
      }),
    });
    setConfirming(false);
    setPreviewLocale(targetLocale);
    window.requestAnimationFrame(() => dashboardTitleInput.current?.focus());
  }

  async function send(
    value: string,
    action?: A2uiAction,
    uploadedDatasetAction?: 'draft',
    datasetDraft?: AgUiRunInput['forwardedProps']['datasetDraft'],
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
    let runSurface = initialA2uiState;
    let runProposal: DashboardProposal | undefined;
    const runActivities: unknown[][] = [];
    followLatest.current = true;
    setMessages(history);
    const retainedIds = new Set(history.map(message => message.id));
    setResults(previous =>
      Object.fromEntries(
        Object.entries(previous).filter(([id]) => retainedIds.has(id)),
      ),
    );
    setStreaming(true);
    setError('');
    setFailedPrompt('');
    if (!action && !uploadedDatasetAction && !datasetDraft) setDraft('');
    replaceProposal(undefined);
    setConfirming(false);

    const promptSaved = remember(history);
    try {
      const response = await host.run(
        fitAgUiInput({
          threadId,
          runId: crypto.randomUUID(),
          messages: wireHistory(history),
          tools: [],
          context: buildContext(
            host,
            datasetDraft ? undefined : uploadedDatasetId,
            uploadedDatasetAction,
            dashboardType,
            dashboardTypes && contentLocale,
          ),
          state: {},
          forwardedProps: {
            ...(action && { a2uiAction: action }),
            ...(datasetDraft && { datasetDraft }),
          },
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
          runProposal = readProposal(event.value) ?? runProposal;
        }
        const operations = a2uiOperations(event);
        if (operations) {
          if (runActivities.length === MAX_ACTIVITY_BATCHES) {
            setError(copy.uiError);
            continue;
          }
          try {
            const parsed = operations.map(item =>
              parseA2uiMessage(item, catalogs),
            );
            runSurface = parsed.reduce(
              (state, message) => applyA2uiMessage(state, message, catalogs),
              runSurface,
            );
            runActivities.push(operations);
          } catch {
            setError(copy.uiError);
          }
        }
      }
      if (controller.signal.aborted) return;
      if (!complete) throw new Error('Incomplete AG-UI run');
      if (
        Object.values(runSurface.surfaces).some(surface =>
          Object.hasOwn(surface.components, 'root'),
        )
      ) {
        setResults(previous => ({
          ...previous,
          [reply.id]: { surface: runSurface, activities: runActivities },
        }));
        setMessages([...history, { ...reply }]);
      }
      if (runProposal) {
        replaceProposal(runProposal);
        setPreviewLocale(undefined);
      }
    } catch {
      complete = false;
      replaceProposal(undefined);
      if (!controller.signal.aborted) {
        if (!datasetDraft) setFailedPrompt(text);
        setError(copy.streamError);
      }
    } finally {
      if (!complete || controller.signal.aborted) setMessages(history);
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
    if (busy || connection.current || mutation.current) return;
    if (host.onAction?.(action)) return;
    send(action.action.userMessage || copy.submit, action);
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
    dismissTranslations();
    setSaving(true);
    setError('');
    try {
      const result = await host.approve(proposal, controller.signal);
      if (controller.signal.aborted) return;
      replaceProposal(undefined);
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
    send(draft);
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
            <p>
              <output>{copy.loadingHistory}</output>
            </p>
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
            {messages.map((message, index) => {
              const result = results[message.id];
              return (
                <div
                  key={message.id}
                  className={`nxtbi-copilot__message nxtbi-copilot__message--${message.role}${result ? ' nxtbi-copilot__message--interactive' : ''}`}
                >
                  {message.role === 'assistant' ? (
                    <>
                      <span className="nxtbi-copilot__speaker">
                        {copy.speaker}
                      </span>
                      {message.content && (
                        <AssistantMarkdown
                          content={message.content}
                          streaming={streaming && index === messages.length - 1}
                        />
                      )}
                      {result && (
                        <fieldset
                          className="nxtbi-copilot__artifact"
                          disabled={busy}
                        >
                          <legend>{copy.interactiveResult}</legend>
                          {renderActivities ? (
                            renderActivities(result.activities, handleAction)
                          ) : (
                            <A2uiRenderer
                              state={result.surface}
                              locale={host.locale}
                              direction={direction}
                              catalogs={catalogs}
                              allowedActions={host.allowedActions}
                              onAction={handleAction}
                              onDataChange={(surfaceId, path, value) =>
                                setResults(previous => ({
                                  ...previous,
                                  [message.id]: {
                                    ...previous[message.id],
                                    surface: updateA2uiData(
                                      previous[message.id].surface,
                                      surfaceId,
                                      path,
                                      value,
                                    ),
                                  },
                                }))
                              }
                            />
                          )}
                        </fieldset>
                      )}
                    </>
                  ) : (
                    <p dir="auto">{message.content}</p>
                  )}
                </div>
              );
            })}
            {proposal && host.approve && (
              <section
                className="nxtbi-copilot__proposal"
                aria-label={copy.proposal}
              >
                <h3>{copy.proposal}</h3>
                {proposal.dashboardType && (
                  <span>
                    {proposal.dashboardType === 'v1'
                      ? copy.classic
                      : copy.builder}
                  </span>
                )}
                {proposal.contentLocale && (
                  <label>
                    {copy.previewLocale}
                    <select
                      value={draftLocale}
                      disabled={busy}
                      onChange={event => {
                        setConfirming(false);
                        setPreviewLocale(dashboardLocale(event.target.value));
                      }}
                    >
                      <DashboardLanguageOptions />
                    </select>
                  </label>
                )}
                <label>
                  {copy.dashboardTitle}
                  <input
                    ref={dashboardTitleInput}
                    value={
                      dashboardTitleIn(
                        proposal,
                        canonicalLocale,
                        draftLocale,
                      ) ?? ''
                    }
                    placeholder={
                      draftLocale !== canonicalLocale
                        ? proposal.title
                        : undefined
                    }
                    lang={draftLocale}
                    dir={draftLocale === 'ar' ? 'rtl' : 'ltr'}
                    maxLength={256}
                    disabled={saving}
                    onChange={event => {
                      setConfirming(false);
                      replaceProposal(
                        editDashboardTitle(
                          proposal,
                          canonicalLocale,
                          draftLocale,
                          event.target.value,
                        ),
                      );
                    }}
                  />
                </label>
                {host.renderProposal?.(
                  proposal,
                  next => {
                    if (saving) return;
                    setConfirming(false);
                    replaceProposal(next);
                  },
                  draftLocale,
                )}
                {proposal.contentLocale && (
                  <div className="nxtbi-copilot__actions">
                    <button
                      ref={suggestButton}
                      type="button"
                      disabled={busy || !proposal.title.trim()}
                      aria-disabled={suggesting || undefined}
                      onClick={suggestTranslations}
                    >
                      {targetLocale === 'ar'
                        ? copy.suggestArabic
                        : copy.suggestEnglish}
                    </button>
                    {suggesting && (
                      <button
                        type="button"
                        onClick={returnToTranslationTrigger}
                      >
                        {copy.cancelSuggestions}
                      </button>
                    )}
                  </div>
                )}
                <output
                  className={
                    hasSuggestions || (!suggesting && !suggestions)
                      ? 'nxtbi-copilot__translation-announcement'
                      : undefined
                  }
                >
                  {suggesting
                    ? copy.suggestingTranslations
                    : hasSuggestions
                      ? copy.translationReviewReady
                      : suggestions
                        ? copy.noSuggestions
                        : null}
                </output>
                {suggestionError && (
                  <p className="nxtbi-copilot__error" role="alert">
                    {copy.translationError}
                  </p>
                )}
                {suggestions && hasSuggestions && (
                  <section aria-labelledby={translationsId}>
                    <h4 id={translationsId}>{copy.suggestedTranslations}</h4>
                    <ul className="nxtbi-copilot__translation-list">
                      {[proposal, ...proposal.widgets].map((item, index) => {
                        const suggested = suggestions[index];
                        if (!suggested) return null;
                        return (
                          <li key={index}>
                            <bdi lang={canonicalLocale}>{item.title}</bdi>
                            <dl>
                              <dt>{copy.currentTranslation}</dt>
                              <dd>
                                <bdi lang={targetLocale}>
                                  {item.titleTranslations?.[targetLocale] ??
                                    '—'}
                                </bdi>
                              </dd>
                              <dt>{copy.suggestedTranslation}</dt>
                              <dd>
                                <bdi lang={targetLocale}>{suggested}</bdi>
                              </dd>
                            </dl>
                          </li>
                        );
                      })}
                    </ul>
                    <div className="nxtbi-copilot__actions">
                      <button
                        type="button"
                        className="nxtbi-copilot__primary"
                        disabled={busy}
                        onClick={applyTranslations}
                      >
                        {copy.applyTranslations}
                      </button>
                      <button
                        type="button"
                        onClick={returnToTranslationTrigger}
                      >
                        {copy.dismissSuggestions}
                      </button>
                    </div>
                  </section>
                )}
                {confirming ? (
                  <div className="nxtbi-copilot__actions">
                    <button
                      className="nxtbi-copilot__primary"
                      type="button"
                      disabled={busy}
                      onClick={approve}
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
              <p className="nxtbi-copilot__working">
                <output>{copy.working}</output>
              </p>
            )}
            {savedDashboard && (
              <div className="nxtbi-copilot__saved">
                <div>
                  <strong>
                    <output>{copy.saved}</output>
                  </strong>
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
              <p className="nxtbi-copilot__error">
                <output>{copy.historySaveError}</output>
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
          {host.listDatasets && host.approve && (
            <ExistingDatasetPicker
              locale={shellLocale}
              listDatasets={host.listDatasets}
              busy={busy}
              onDraft={dataset => {
                send(
                  copy.draftExistingDatasetPrompt(dataset.name),
                  undefined,
                  undefined,
                  { datasetId: dataset.id },
                );
              }}
            />
          )}
          {host.uploadDataset && attachments.length > 0 && (
            <section
              className="nxtbi-copilot__uploads"
              aria-label={copy.csvFiles}
            >
              <output className="nxtbi-copilot__upload-status">
                {uploadProgress
                  ? copy.importing
                  : hasImported
                    ? copy.datasetReady
                    : null}
              </output>
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
                  <button type="button" disabled={busy} onClick={importFiles}>
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
                      send(
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
          {dashboardType && (
            <div className="nxtbi-copilot__draft-options">
              <label>
                {copy.dashboardType}
                <select
                  value={dashboardType}
                  disabled={busy}
                  onChange={event => {
                    const format = dashboardTypes?.find(
                      item => item === event.target.value,
                    );
                    if (format) setFormatPreference(format);
                  }}
                >
                  {dashboardTypes?.map(format => (
                    <option key={format} value={format}>
                      {format === 'v1' ? copy.classic : copy.builder}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {copy.contentLocale}
                <select
                  value={contentLocale}
                  disabled={busy}
                  onChange={event =>
                    setLanguagePreference(dashboardLocale(event.target.value))
                  }
                >
                  <DashboardLanguageOptions />
                </select>
              </label>
            </div>
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

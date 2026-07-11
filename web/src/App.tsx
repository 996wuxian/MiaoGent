import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from 'react';
import { api, isAbortError } from './api';
import miaogentLogo from './assets/miaogent-logo.png';
import { ConfirmDetail, ConfirmDialog, ConfirmDraft, DevtoolsPasswordDialog, HealthDrawer } from './components/Dialogs';
import { DesktopSettings } from './components/DesktopSettings';
import { DraftWorkspace, normalizeUid, type DraftEditorState } from './components/DraftWorkspace';
import { InspectionReport } from './components/InspectionReport';
import { InsightSummary, StartupSummaryDrawer } from './components/StartupSummary';
import {
  initializeDesktopBridge,
  isTauriRuntime,
  getDesktopConfig,
  isDesktopConfigComplete,
  openDevtools,
  shouldRefreshDesktopData,
  type DesktopTarget,
} from './desktop/desktopBridge';
import {
  AppIcon,
  Badge,
  CustomDropdown,
  EmptyState,
  IconButton,
  InlineError,
  LoadingLine,
  PanelHeader,
  SegmentedTabs,
  type BadgeTone,
  type IconName,
} from './components/ui';
import { useExclusiveAction } from './hooks/useExclusiveAction';
import type {
  ActionLog,
  Draft,
  DraftFilter,
  FetchFailure,
  HealthItem,
  InsightFeedback,
  InspectionPlanItem,
  MailInsight,
  MailImportance,
  MailMessage,
  MailView,
  QueueStatus,
  SearchMailItem,
  SecretaryInspectionReport,
  StartupSummary,
  Translation,
  TriageItem,
} from './types';

const pageSize = 20;

const classificationLabel: Record<string, string> = {
  ignore: '忽略',
  notify: '通知',
  respond: '需回复',
};

const actionLabel: Record<string, string> = {
  read_full: '查看全文',
  translate: '翻译',
  draft_reply: '生成草稿',
  mark_seen: '标为已读',
  move_to_trash: '移到垃圾箱',
  no_action: '无需处理',
};

const queueLabel: Record<string, string> = {
  pending: '待处理',
  later: '稍后',
  done: '已处理',
  skipped: '已跳过',
};

const importanceLabel: Record<string, string> = {
  general: '一般',
  important: '重要',
  urgent: '紧急',
};

const externalHealthLabel = {
  imap: 'IMAP 登录',
  smtp: 'SMTP 登录',
  deepseek: 'DeepSeek 连通性',
} as const;

type Theme = 'light' | 'dark';
type LeftView = 'recent' | 'queue' | 'search' | 'insights';
type RightView = 'actions' | 'drafts' | 'history';
type MobileStage = 'list' | 'reading' | 'right';
type MessageContentView = 'source' | 'translation';
type ExternalHealthTarget = keyof typeof externalHealthLabel;
type DesktopSettingsMode = 'settings' | 'onboarding';

type Resource<T> = {
  data: T;
  loading: boolean;
  error: string;
};

type FeedbackKind = 'success' | 'error' | 'loading';
type Feedback = { kind: FeedbackKind; message: string; persist: boolean; durationMs: number | null } | null;
type FeedbackOptions = { persist?: boolean; durationMs?: number };

type SearchFilters = {
  keyword: string;
  is_seen: '' | 'true' | 'false';
  classification: '' | 'ignore' | 'notify' | 'respond';
  queue_status: '' | QueueStatus;
};

type ListItem = {
  uid: string;
  sender: string;
  subject: string;
  date: string | null;
  isSeen: boolean | null;
  classification?: string | null;
  suggestedAction?: string | null;
  queueStatus?: string | null;
  reason?: string;
  actionReason?: string;
  importance?: string;
  needsReply?: boolean;
  summary?: string;
  replyStatus?: string;
  analysisStatus?: string;
  confidence?: number;
  draftId?: string | null;
};

type LoadRecentOptions = {
  append?: boolean;
};

const emptySearchFilters: SearchFilters = {
  keyword: '',
  is_seen: '',
  classification: '',
  queue_status: '',
};

function resource<T>(data: T): Resource<T> {
  return { data, loading: false, error: '' };
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function sameUid(left: string, right: string) {
  return Boolean(left && right && normalizeUid(left) === normalizeUid(right));
}

function parseMailDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function pad2(value: number) {
  return String(value).padStart(2, '0');
}

const mailMonthNumbers: Record<string, string> = {
  jan: '01',
  feb: '02',
  mar: '03',
  apr: '04',
  may: '05',
  jun: '06',
  jul: '07',
  aug: '08',
  sep: '09',
  oct: '10',
  nov: '11',
  dec: '12',
};

function parseMailHeaderDateParts(value: string | null | undefined) {
  if (!value) return null;
  const match = value.match(/(?:^|,\s*)(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{2}):(\d{2})(?::\d{2})?\s+(?:[+-]\d{4}|[A-Z]{1,5})\b/);
  if (!match) return null;
  const [, day, monthName, year, hour, minute] = match;
  const month = mailMonthNumbers[monthName.toLowerCase()];
  if (!month) return null;
  return {
    year,
    month,
    day: pad2(Number(day)),
    time: `${hour}:${minute}`,
  };
}

function formatMailDate(value: string | null | undefined, mode: 'list' | 'detail' = 'list') {
  const headerDate = parseMailHeaderDateParts(value);
  if (headerDate) {
    const full = `${headerDate.year}-${headerDate.month}-${headerDate.day} ${headerDate.time}`;
    if (mode === 'detail') return full;
    return Number(headerDate.year) === new Date().getFullYear()
      ? `${headerDate.month}-${headerDate.day} ${headerDate.time}`
      : full;
  }

  const parsed = parseMailDate(value);
  if (!parsed) return value || '';
  const year = parsed.getFullYear();
  const month = pad2(parsed.getMonth() + 1);
  const day = pad2(parsed.getDate());
  const time = `${pad2(parsed.getHours())}:${pad2(parsed.getMinutes())}`;
  if (mode === 'detail') return `${year}-${month}-${day} ${time}`;
  return year === new Date().getFullYear() ? `${month}-${day} ${time}` : `${year}-${month}-${day} ${time}`;
}

function mergeRecentMessages(existing: MailMessage[], incoming: MailMessage[]) {
  const seen = new Set(existing.map((item) => normalizeUid(item.id)));
  const merged = [...existing];
  for (const item of incoming) {
    const key = normalizeUid(item.id);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(item);
  }
  return merged;
}

function initialTheme(): Theme {
  const saved = window.localStorage.getItem('qq-mail-agent-theme');
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function App() {
  const desktopRuntime = isTauriRuntime();
  const initialLeftView = desktopRuntime ? 'insights' : 'recent';
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [leftView, setLeftView] = useState<LeftView>(initialLeftView);
  const [rightView, setRightView] = useState<RightView>('actions');
  const [mobileStage, setMobileStage] = useState<MobileStage>('list');
  const [recent, setRecent] = useState<Resource<MailMessage[]>>(resource([]));
  const [queue, setQueue] = useState<Resource<TriageItem[]>>(resource([]));
  const [search, setSearch] = useState<Resource<SearchMailItem[]>>(resource([]));
  const [insights, setInsights] = useState<Resource<MailInsight[]>>(resource([]));
  const [agentMailbox, setAgentMailbox] = useState<Resource<MailMessage[]>>(resource([]));
  const [fetchFailures, setFetchFailures] = useState<FetchFailure[]>([]);
  const [detail, setDetail] = useState<Resource<MailMessage | null>>(resource(null));
  const [selectedInsight, setSelectedInsight] = useState<Resource<MailInsight | null>>(resource(null));
  const [drafts, setDrafts] = useState<Resource<Draft[]>>(resource([]));
  const [actions, setActions] = useState<Resource<ActionLog[]>>(resource([]));
  const [health, setHealth] = useState<Resource<HealthItem[]>>(resource([]));
  const [externalHealth, setExternalHealth] = useState<Partial<Record<ExternalHealthTarget, HealthItem>>>({});
  const [translation, setTranslation] = useState<Resource<Translation | null>>(resource(null));
  const [messageContentView, setMessageContentView] = useState<MessageContentView>('source');
  const [selectedId, setSelectedId] = useState('');
  const [selectedDraftId, setSelectedDraftId] = useState('');
  const [draftEditor, setDraftEditor] = useState<DraftEditorState | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [queueStatus, setQueueStatus] = useState<QueueStatus>('pending');
  const [draftFilter, setDraftFilter] = useState<DraftFilter>('pending');
  const [sendingDraftId, setSendingDraftId] = useState('');
  const [searchFilters, setSearchFilters] = useState<SearchFilters>(emptySearchFilters);
  const [appliedSearchFilters, setAppliedSearchFilters] = useState<SearchFilters>(emptySearchFilters);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [healthOpen, setHealthOpen] = useState(false);
  const [inspectionReport, setInspectionReport] = useState<SecretaryInspectionReport | null>(null);
  const [inspectionOpen, setInspectionOpen] = useState(false);
  const [inspectionError, setInspectionError] = useState('');
  const [mailView, setMailView] = useState<MailView>('all');
  const [startupSummary, setStartupSummary] = useState<Resource<StartupSummary | null>>(resource(null));
  const [startupSummaryOpen, setStartupSummaryOpen] = useState(false);
  const [desktopConnected, setDesktopConnected] = useState(false);
  const [desktopConfigIncomplete, setDesktopConfigIncomplete] = useState(desktopRuntime);
  const [desktopTarget, setDesktopTarget] = useState<DesktopTarget | null>(null);
  const [desktopSettingsOpen, setDesktopSettingsOpen] = useState(false);
  const [desktopSettingsMode, setDesktopSettingsMode] = useState<DesktopSettingsMode>('settings');
  const [devtoolsUnlockOpen, setDevtoolsUnlockOpen] = useState(false);
  const [devtoolsUnlockError, setDevtoolsUnlockError] = useState('');
  const [confirmState, setConfirmState] = useState<import('./components/Dialogs').ConfirmState | null>(null);

  const { runExclusive, isPending } = useExclusiveAction();
  const confirmResolver = useRef<((confirmed: boolean) => void) | null>(null);
  const didInitRef = useRef(false);
  const selectedIdRef = useRef('');
  const leftViewRef = useRef<LeftView>(initialLeftView);
  const mailViewRef = useRef<MailView>('all');
  const queueStatusRef = useRef<QueueStatus>('pending');
  const draftFilterRef = useRef<DraftFilter>('pending');
  const detailRef = useRef<MailMessage | null>(null);
  const draftEditorRef = useRef<DraftEditorState | null>(null);
  const sendingDraftIdRef = useRef('');
  const selectionRequestRef = useRef<{ sequence: number; controller: AbortController | null }>({ sequence: 0, controller: null });
  const recentRequestRef = useRef<{ sequence: number; controller: AbortController | null }>({ sequence: 0, controller: null });
  const queueRequestRef = useRef<{ sequence: number; controller: AbortController | null }>({ sequence: 0, controller: null });
  const searchRequestRef = useRef<{ sequence: number; controller: AbortController | null }>({ sequence: 0, controller: null });
  const insightsRequestRef = useRef<{ sequence: number; controller: AbortController | null }>({ sequence: 0, controller: null });
  const appliedSearchFiltersRef = useRef<SearchFilters>(emptySearchFilters);
  const draftsRequestRef = useRef<{ sequence: number; controller: AbortController | null }>({ sequence: 0, controller: null });
  const actionsRequestRef = useRef<{ sequence: number; controller: AbortController | null }>({ sequence: 0, controller: null });
  const healthRequestRef = useRef<{ sequence: number; controller: AbortController | null }>({ sequence: 0, controller: null });
  const mailListRef = useRef<HTMLDivElement | null>(null);
  const desktopRefreshTimerRef = useRef<number | null>(null);
  const feedbackTimerRef = useRef<number | null>(null);
  const titleClickRef = useRef({ count: 0, lastAt: 0 });
  const desktopConfigIncompleteRef = useRef(desktopRuntime);

  const selectedDetail = useMemo(
    () => (detail.data && sameUid(detail.data.id, selectedId) ? detail.data : null),
    [detail.data, selectedId],
  );
  const selectedTranslation = selectedDetail && translation.data && sameUid(translation.data.mail_id, selectedDetail.id)
    ? translation.data
    : null;
  const translationVisible = Boolean(translation.loading || translation.error || selectedTranslation);
  const selectedDraft = useMemo(
    () => drafts.data.find((item) => item.draft_id === selectedDraftId),
    [drafts.data, selectedDraftId],
  );
  const draftDirty = Boolean(
    draftEditor &&
      (draftEditor.subject !== draftEditor.baselineSubject || draftEditor.body !== draftEditor.baselineBody),
  );
  const selectedQueue = useMemo(() => {
    const exact = queue.data.find((item) => sameUid(item.uid, selectedId));
    if (exact) return exact;
    const searched = leftView === 'search' ? search.data.find((item) => sameUid(item.uid, selectedId)) : undefined;
    return searched ? searchToTriage(searched) : undefined;
  }, [leftView, queue.data, search.data, selectedId]);
  const healthOk = health.data.length > 0 && health.data.every((item) => item.ok);
  const pageNumber = Math.floor(offset / pageSize) + 1;

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    detailRef.current = selectedDetail;
  }, [selectedDetail]);

  useEffect(() => {
    draftEditorRef.current = draftEditor;
  }, [draftEditor]);

  useEffect(() => {
    leftViewRef.current = leftView;
  }, [leftView]);

  useEffect(() => {
    mailViewRef.current = mailView;
  }, [mailView]);

  useEffect(() => {
    queueStatusRef.current = queueStatus;
  }, [queueStatus]);

  useEffect(() => {
    draftFilterRef.current = draftFilter;
  }, [draftFilter]);

  useEffect(() => {
    desktopConfigIncompleteRef.current = desktopConfigIncomplete;
    if (desktopConfigIncomplete) setStartupSummaryOpen(false);
  }, [desktopConfigIncomplete]);

  useEffect(() => {
    document.documentElement.classList.toggle('theme-dark', theme === 'dark');
    document.documentElement.classList.toggle('theme-light', theme === 'light');
    window.localStorage.setItem('qq-mail-agent-theme', theme);
  }, [theme]);

  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    if (isTauriRuntime()) return;
    void loadLocalHealth();
    void loadRecent(0);
    void loadQueue('pending');
    void loadDrafts('pending', { forceEditor: true });
    void loadActions();
  }, []);

  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void initializeDesktopBridge({
      onBackendReady: () => {
        if (disposed) return;
        setDesktopConnected(true);
        void Promise.all([loadLocalHealth(), loadQueue('pending'), loadStartupSummary()]);
        scheduleDesktopRefresh();
      },
      onEvent: (event) => {
        if (disposed) return;
        if (event.event === 'startup_summary' || event.event === 'sync_summary') {
          setStartupSummary({ data: event.payload as unknown as StartupSummary, loading: false, error: '' });
          if (event.event === 'startup_summary' && !desktopConfigIncompleteRef.current) {
            setStartupSummaryOpen(true);
          }
        }
        if (event.event === 'watcher_status') {
          const status = event.payload.status;
          if (status === 'sidecar_stopped' || status === 'sidecar_ready_timeout' || status === 'sidecar_restart_failed' || status === 'sidecar_restart_exhausted') {
            setDesktopConnected(false);
          }
        }
        if (event.event === 'attention_required') {
          announce('error', '有邮件需要人工查看，已刷新 Agent 工作台。');
        }
        if (shouldRefreshDesktopData(event)) scheduleDesktopRefresh();
      },
      onNavigate: setDesktopTarget,
      onSyncRequest: () => void runDesktopSync(),
    }).then((stop) => {
      if (disposed) stop();
      else cleanup = stop;
    }).catch((error) => {
      if (!disposed) announce('error', `桌面桥接初始化失败：${errorMessage(error)}`);
    });
    return () => {
      disposed = true;
      cleanup?.();
      if (desktopRefreshTimerRef.current !== null) {
        window.clearTimeout(desktopRefreshTimerRef.current);
        desktopRefreshTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!desktopRuntime) return;
    void refreshDesktopConfigState({ autoOpen: true });
  }, [desktopRuntime]);

  useEffect(() => {
    if (!desktopTarget) return;
    if (desktopTarget.kind === 'summary') {
      if (desktopConfigIncompleteRef.current) {
        openDesktopSettings('onboarding');
      } else {
        setStartupSummaryOpen(true);
        void loadStartupSummary();
      }
    } else {
      mailViewRef.current = 'all';
      setMailView('all');
      switchLeftView('recent');
      void selectMessage(desktopTarget.uid, { markSeenOnOpen: false });
    }
    setDesktopTarget(null);
  }, [desktopTarget]);

  useEffect(() => {
    if (!draftDirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [draftDirty]);

  useEffect(() => () => {
    if (feedbackTimerRef.current !== null) {
      window.clearTimeout(feedbackTimerRef.current);
      feedbackTimerRef.current = null;
    }
  }, []);

  const closeConfirm = useCallback((confirmed: boolean) => {
    confirmResolver.current?.(confirmed);
    confirmResolver.current = null;
    setConfirmState(null);
  }, []);

  function askConfirm(config: import('./components/Dialogs').ConfirmState): Promise<boolean> {
    confirmResolver.current?.(false);
    setConfirmState(config);
    return new Promise((resolve) => {
      confirmResolver.current = resolve;
    });
  }

  function announce(kind: FeedbackKind, message: string, options: FeedbackOptions = {}) {
    if (feedbackTimerRef.current !== null) {
      window.clearTimeout(feedbackTimerRef.current);
      feedbackTimerRef.current = null;
    }
    const persist = options.persist ?? kind !== 'success';
    const durationMs = persist ? null : options.durationMs ?? 2000;
    setFeedback({ kind, message, persist, durationMs });
    if (durationMs !== null) {
      feedbackTimerRef.current = window.setTimeout(() => {
        feedbackTimerRef.current = null;
        setFeedback((current) => (
          current?.kind === kind && current.message === message && current.durationMs === durationMs
            ? null
            : current
        ));
      }, durationMs);
    }
  }

  function openDesktopSettings(mode: DesktopSettingsMode = desktopConfigIncomplete ? 'onboarding' : 'settings') {
    setDesktopSettingsMode(mode);
    setDesktopSettingsOpen(true);
  }

  async function refreshDesktopConfigState({ autoOpen = false }: { autoOpen?: boolean } = {}) {
    if (!desktopRuntime) return;
    try {
      const config = await getDesktopConfig();
      const incomplete = !isDesktopConfigComplete(config);
      setDesktopConfigIncomplete(incomplete);
      if (incomplete && autoOpen) {
        setDesktopSettingsMode('onboarding');
        setDesktopSettingsOpen(true);
      }
    } catch (error) {
      setDesktopConfigIncomplete(true);
      if (autoOpen) {
        setDesktopSettingsMode('onboarding');
        setDesktopSettingsOpen(true);
      }
      announce('error', `桌面配置读取失败：${errorMessage(error)}`);
    }
  }

  function handleTitleClick() {
    if (!desktopRuntime) return;
    const now = window.performance.now();
    const previous = titleClickRef.current;
    const count = now - previous.lastAt <= 1500 ? previous.count + 1 : 1;
    titleClickRef.current = { count, lastAt: now };
    if (count >= 5) {
      titleClickRef.current = { count: 0, lastAt: 0 };
      setDevtoolsUnlockError('');
      setDevtoolsUnlockOpen(true);
    }
  }

  async function unlockDevtools(password: string) {
    await runExclusive('open-devtools', async () => {
      try {
        setDevtoolsUnlockError('');
        await openDevtools(password);
        setDevtoolsUnlockOpen(false);
        announce('success', '开发者控制台已打开。');
      } catch (error) {
        setDevtoolsUnlockError(errorMessage(error));
      }
    });
  }

  function clearSelection() {
    selectionRequestRef.current.controller?.abort();
    selectionRequestRef.current.sequence += 1;
    selectionRequestRef.current.controller = null;
    selectedIdRef.current = '';
    detailRef.current = null;
    setSelectedId('');
    setDetail(resource(null));
    setSelectedInsight(resource(null));
    setTranslation(resource(null));
  }

  function discardEditorChanges() {
    setDraftEditor((current) =>
      (() => {
        const next = current
          ? {
              ...current,
              subject: current.baselineSubject,
              body: current.baselineBody,
            }
          : null;
        draftEditorRef.current = next;
        return next;
      })(),
    );
  }

  async function guardDraftChanges(context: string) {
    if (!draftDirty) return true;
    const confirmed = await askConfirm({
      title: '有未保存的草稿修改',
      message: `${context}会放弃当前尚未保存的主题或正文。`,
      confirmLabel: '放弃修改',
      tone: 'warning',
      details: selectedDraft ? <ConfirmDetail rows={[['草稿', selectedDraft.subject], ['状态', '未保存修改']]} /> : undefined,
    });
    if (confirmed) discardEditorChanges();
    return confirmed;
  }

  async function loadLocalHealth() {
    healthRequestRef.current.controller?.abort();
    const sequence = healthRequestRef.current.sequence + 1;
    const controller = new AbortController();
    healthRequestRef.current = { sequence, controller };
    setHealth((current) => ({ ...current, loading: true, error: '' }));
    try {
      const items = await api.localHealth(controller.signal);
      if (healthRequestRef.current.sequence !== sequence) return;
      setHealth({ data: items, loading: false, error: '' });
    } catch (error) {
      if (isAbortError(error) || healthRequestRef.current.sequence !== sequence) return;
      setHealth((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  }

  async function loadActions() {
    actionsRequestRef.current.controller?.abort();
    const sequence = actionsRequestRef.current.sequence + 1;
    const controller = new AbortController();
    actionsRequestRef.current = { sequence, controller };
    setActions((current) => ({ ...current, loading: true, error: '' }));
    try {
      const items = await api.actions(controller.signal);
      if (actionsRequestRef.current.sequence !== sequence) return;
      setActions({ data: items, loading: false, error: '' });
    } catch (error) {
      if (isAbortError(error) || actionsRequestRef.current.sequence !== sequence) return;
      setActions((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  }

  async function loadRecent(nextOffset: number, options: LoadRecentOptions = {}) {
    recentRequestRef.current.controller?.abort();
    const sequence = recentRequestRef.current.sequence + 1;
    const controller = new AbortController();
    recentRequestRef.current = { sequence, controller };
    const append = options.append === true;
    setRecent((current) => ({ ...current, loading: true, error: '' }));
    try {
      const items = await api.recentMessages(pageSize, nextOffset, controller.signal);
      if (recentRequestRef.current.sequence !== sequence) return;
      setRecent((current) => ({
        data: append ? mergeRecentMessages(current.data, items) : items,
        loading: false,
        error: '',
      }));
      setOffset(nextOffset);
      setHasMore(items.length === pageSize);
      if (!append && leftViewRef.current === 'recent' && selectedIdRef.current && !items.some((item) => sameUid(item.id, selectedIdRef.current))) {
        clearSelection();
      }
      if (!append && items.length === 0 && leftViewRef.current === 'recent') clearSelection();
    } catch (error) {
      if (isAbortError(error) || recentRequestRef.current.sequence !== sequence) return;
      setRecent((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  }

  async function loadQueue(status: QueueStatus) {
    queueRequestRef.current.controller?.abort();
    const sequence = queueRequestRef.current.sequence + 1;
    const controller = new AbortController();
    queueRequestRef.current = { sequence, controller };
    setQueue((current) => ({ ...current, loading: true, error: '' }));
    try {
      const [richResult, searchResult] = await Promise.allSettled([
        api.triageQueue([status], controller.signal),
        api.searchMessages({ queue_status: status, limit: 100 }, controller.signal),
      ]);
      if (queueRequestRef.current.sequence !== sequence) return;
      if (richResult.status === 'rejected' && searchResult.status === 'rejected') throw richResult.reason;
      const richItems = richResult.status === 'fulfilled' ? richResult.value.filter((item) => item.queue_status === status) : [];
      const richMap = new Map(richItems.map((item) => [normalizeUid(item.uid), item]));
      const items =
        searchResult.status === 'fulfilled'
          ? searchResult.value.map((item) => {
              const rich = richMap.get(normalizeUid(item.uid));
              return rich ? { ...rich, is_seen: item.is_seen } : searchToTriage(item);
            })
          : richItems;
      setQueue({ data: items, loading: false, error: '' });
      setQueueStatus(status);
      queueStatusRef.current = status;
    } catch (error) {
      if (isAbortError(error) || queueRequestRef.current.sequence !== sequence) return;
      setQueue((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  }

  async function loadInsights(view: MailView) {
    insightsRequestRef.current.controller?.abort();
    const sequence = insightsRequestRef.current.sequence + 1;
    const controller = new AbortController();
    insightsRequestRef.current = { sequence, controller };
    setInsights((current) => ({ ...current, loading: true, error: '' }));
    setAgentMailbox((current) => ({ ...current, loading: true, error: '' }));
    const filters =
      view === 'reply'
        ? { reply_pending: true, limit: 500 }
        : view === 'all'
          ? { limit: 500 }
          : { importance: view, analysis_status: 'analyzed', min_confidence: 0.55, limit: 500 };
    try {
      const [insightsResult, failuresResult, mailboxResult] = await Promise.allSettled([
        api.insights(filters, controller.signal),
        view === 'all' ? api.fetchFailures(controller.signal) : Promise.resolve([]),
        api.recentMessages(100, 0, controller.signal),
      ]);
      if (insightsRequestRef.current.sequence !== sequence) return;
      const items = insightsResult.status === 'fulfilled' ? insightsResult.value : [];
      const failures = failuresResult.status === 'fulfilled' ? failuresResult.value : [];
      const mailboxItems = mailboxResult.status === 'fulfilled' ? mailboxResult.value : [];
      const errors = [
        insightsResult.status === 'rejected' ? `邮件洞察：${errorMessage(insightsResult.reason)}` : '',
        failuresResult.status === 'rejected' ? `读取失败项：${errorMessage(failuresResult.reason)}` : '',
        mailboxResult.status === 'rejected' ? `当前邮箱列表：${errorMessage(mailboxResult.reason)}` : '',
      ].filter(Boolean);
      setInsights({ data: items, loading: false, error: errors.join('；') });
      setAgentMailbox({
        data: mailboxItems,
        loading: false,
        error: mailboxResult.status === 'rejected' ? errorMessage(mailboxResult.reason) : '',
      });
      if (view === 'all') setFetchFailures(failures);
    } catch (error) {
      if (isAbortError(error) || insightsRequestRef.current.sequence !== sequence) return;
      setInsights((current) => ({ ...current, loading: false, error: errorMessage(error) }));
      setAgentMailbox((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  }

  function scheduleDesktopRefresh() {
    if (desktopRefreshTimerRef.current !== null) {
      window.clearTimeout(desktopRefreshTimerRef.current);
    }
    desktopRefreshTimerRef.current = window.setTimeout(() => {
      desktopRefreshTimerRef.current = null;
      const currentMailView = mailViewRef.current;
      const currentLeftView = leftViewRef.current;
      const listTask =
        currentLeftView === 'insights'
          ? loadInsights(currentMailView)
          : currentLeftView === 'queue'
            ? loadQueue(queueStatusRef.current)
            : currentLeftView === 'search'
              ? runSearch(appliedSearchFiltersRef.current)
              : loadRecent(0);
      void Promise.all([listTask, loadDrafts(draftFilterRef.current), loadActions()]);
    }, 120);
  }

  function selectMailView(view: MailView) {
    mailViewRef.current = view;
    setMailView(view);
    setLeftView('insights');
    leftViewRef.current = 'insights';
    void loadInsights(view);
  }

  async function loadStartupSummary() {
    setStartupSummary((current) => ({ ...current, loading: true, error: '' }));
    try {
      const summary = await api.latestStartupSummary();
      setStartupSummary({ data: summary, loading: false, error: '' });
    } catch (error) {
      setStartupSummary((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  }

  async function syncDesktopMailbox({ openSummary }: { openSummary: boolean }) {
    setStartupSummary((current) => ({ ...current, loading: true, error: '' }));
    const summary = await api.desktopSync();
    setStartupSummary({ data: summary, loading: false, error: '' });
    if (openSummary && !desktopConfigIncompleteRef.current) setStartupSummaryOpen(true);
    return summary;
  }

  async function runDesktopSync() {
    await runExclusive('desktop-sync', async () => {
      if (desktopConfigIncompleteRef.current) {
        setStartupSummaryOpen(false);
        announce('error', '请先完成桌面 Agent 配置，再整理新邮件。');
        openDesktopSettings('onboarding');
        return;
      }
      try {
        const summary = await syncDesktopMailbox({ openSummary: true });
        const currentMailView = mailViewRef.current;
        await Promise.all([
          leftViewRef.current === 'insights' ? loadInsights(currentMailView) : loadRecent(0),
          loadDrafts(draftFilterRef.current),
          loadActions(),
        ]);
        announce('success', `整理完成：新增 ${summary.new_count} 封，${summary.reply_count} 封待回复。`);
      } catch (error) {
        setStartupSummary((current) => ({ ...current, loading: false, error: errorMessage(error) }));
        announce('error', `整理失败：${errorMessage(error)}`);
      }
    });
  }

  async function runSearch(filters: SearchFilters = searchFilters) {
    searchRequestRef.current.controller?.abort();
    const sequence = searchRequestRef.current.sequence + 1;
    const controller = new AbortController();
    searchRequestRef.current = { sequence, controller };
    setSearch((current) => ({ ...current, loading: true, error: '' }));
    try {
      const items = await api.searchMessages(
        {
          keyword: filters.keyword.trim(),
          is_seen: filters.is_seen === '' ? null : filters.is_seen === 'true',
          classification: filters.classification,
          queue_status: filters.queue_status,
          limit: 100,
        },
        controller.signal,
      );
      if (searchRequestRef.current.sequence !== sequence) return;
      setSearch({ data: items, loading: false, error: '' });
      setAppliedSearchFilters(filters);
      appliedSearchFiltersRef.current = filters;
    } catch (error) {
      if (isAbortError(error) || searchRequestRef.current.sequence !== sequence) return;
      setSearch((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  }

  async function loadDrafts(
    targetFilter: DraftFilter,
    options: { preferredId?: string; preferredMailId?: string; forceEditor?: boolean } = {},
  ) {
    draftsRequestRef.current.controller?.abort();
    const sequence = draftsRequestRef.current.sequence + 1;
    const controller = new AbortController();
    draftsRequestRef.current = { sequence, controller };
    setDrafts((current) => ({ ...current, loading: true, error: '' }));
    try {
      const items = await api.drafts(targetFilter, controller.signal);
      if (draftsRequestRef.current.sequence !== sequence) return;
      setDrafts({ data: items, loading: false, error: '' });
      setDraftFilter(targetFilter);
      draftFilterRef.current = targetFilter;
      if (!isDraftEditorDirty(draftEditorRef.current) || options.forceEditor) {
        const preferred =
          items.find((item) => item.draft_id === options.preferredId) ??
          items.find((item) => sameUid(item.uid, options.preferredMailId ?? selectedIdRef.current)) ??
          items.find((item) => item.draft_id === draftEditorRef.current?.draftId) ??
          items[0];
        selectDraftLocally(preferred);
      }
    } catch (error) {
      if (isAbortError(error) || draftsRequestRef.current.sequence !== sequence) return;
      setDrafts((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  }

  function selectDraftLocally(draft: Draft | undefined) {
    setSelectedDraftId(draft?.draft_id ?? '');
    const nextEditor = draft
      ? {
          draftId: draft.draft_id,
          subject: draft.subject,
          body: draft.body,
          baselineSubject: draft.subject,
          baselineBody: draft.body,
        }
      : null;
    draftEditorRef.current = nextEditor;
    setDraftEditor(nextEditor);
  }

  function updateSeenEverywhere(uid: string) {
    setRecent((current) => ({
      ...current,
      data: current.data.map((item) => (sameUid(item.id, uid) ? { ...item, is_seen: true } : item)),
    }));
    setAgentMailbox((current) => ({
      ...current,
      data: current.data.map((item) => (sameUid(item.id, uid) ? { ...item, is_seen: true } : item)),
    }));
    setSearch((current) => ({
      ...current,
      data: current.data.map((item) => (sameUid(item.uid, uid) ? { ...item, is_seen: true } : item)),
    }));
    setInsights((current) => ({
      ...current,
      data: current.data.map((item) => (sameUid(item.uid, uid) ? { ...item, is_seen: true } : item)),
    }));
  }

  function updateInsightEverywhere(updated: MailInsight) {
    setSelectedInsight((current) =>
      current.data && sameUid(current.data.uid, updated.uid)
        ? { ...current, data: updated, loading: false, error: '' }
        : current,
    );
    setInsights((current) => ({
      ...current,
      data: current.data.map((item) => (sameUid(item.uid, updated.uid) ? updated : item)),
    }));
  }

  function refreshSearchIfInitialized() {
    return searchRequestRef.current.sequence > 0 ? runSearch(appliedSearchFiltersRef.current) : Promise.resolve();
  }

  async function selectMessage(uid: string, { markSeenOnOpen = true }: { markSeenOnOpen?: boolean } = {}) {
    if (!uid) return;
    if (sendingDraftIdRef.current) {
      announce('error', '草稿正在发送，请等待结果后再切换邮件。');
      return;
    }
    if (!(await guardDraftChanges('切换邮件'))) return;
    selectionRequestRef.current.controller?.abort();
    const sequence = selectionRequestRef.current.sequence + 1;
    const controller = new AbortController();
    selectionRequestRef.current = { sequence, controller };
    selectedIdRef.current = uid;
    setSelectedId(uid);
    setMobileStage('reading');
    setTranslation(resource(null));
    setMessageContentView('source');
    setDetail((current) => ({ ...current, loading: true, error: '' }));
    setSelectedInsight((current) => ({ ...current, loading: true, error: '' }));
    try {
      const [message, insight] = await Promise.all([
        api.messageDetail(uid, controller.signal),
        api.insight(uid, controller.signal).catch(() => null),
      ]);
      if (selectionRequestRef.current.sequence !== sequence || !sameUid(selectedIdRef.current, uid)) return;
      detailRef.current = message;
      setDetail({ data: message, loading: false, error: '' });
      setSelectedInsight({ data: insight, loading: false, error: '' });
      const matchingDraft = drafts.data.find((item) => sameUid(item.uid, uid));
      if (matchingDraft && !isDraftEditorDirty(draftEditorRef.current)) selectDraftLocally(matchingDraft);

      if (markSeenOnOpen && message.is_seen === false) {
        await Promise.resolve();
        if (selectionRequestRef.current.sequence !== sequence || !sameUid(selectedIdRef.current, uid)) return;
        try {
          await api.markSeen(uid, controller.signal);
          if (selectionRequestRef.current.sequence !== sequence || !sameUid(selectedIdRef.current, uid)) return;
          const seenMessage = { ...message, is_seen: true };
          detailRef.current = seenMessage;
          setDetail({ data: seenMessage, loading: false, error: '' });
          updateSeenEverywhere(uid);
          announce('success', '已同步标记为已读。');
          void loadActions();
          void loadQueue(queueStatusRef.current);
          void refreshSearchIfInitialized();
        } catch (error) {
          if (isAbortError(error)) return;
          if (selectionRequestRef.current.sequence === sequence && sameUid(selectedIdRef.current, uid)) {
            announce('error', `邮件已打开，但同步已读失败：${errorMessage(error)}`);
          }
        }
      }
    } catch (error) {
      if (isAbortError(error) || selectionRequestRef.current.sequence !== sequence) return;
      if (!sameUid(selectedIdRef.current, uid)) return;
      setDetail((current) => ({ ...current, loading: false, error: errorMessage(error) }));
      setSelectedInsight((current) => ({ ...current, loading: false }));
    }
  }

  function validateTarget(): { uid: string; message: MailMessage } | null {
    const uid = selectedIdRef.current;
    const message = detailRef.current;
    if (!uid || !message || !sameUid(uid, message.id)) {
      announce('error', '邮件仍在加载或选择已变化，请重新选择后再操作。');
      return null;
    }
    return { uid, message };
  }

  function targetStillValid(uid: string, message: MailMessage) {
    return sameUid(selectedIdRef.current, uid) && Boolean(detailRef.current && sameUid(detailRef.current.id, message.id));
  }

  async function translateSelected() {
    const target = validateTarget();
    if (!target) return;
    const confirmed = await askConfirm({
      title: '确认发送给 DeepSeek 翻译',
      message: '该邮件正文会发送给 DeepSeek 生成中文翻译。翻译结果只在当前页面展示。',
      confirmLabel: '确认翻译',
      tone: 'warning',
      details: <ConfirmDetail rows={[['邮件', target.message.subject], ['发件人', target.message.sender]]} />,
    });
    if (!confirmed || !targetStillValid(target.uid, target.message)) {
      if (confirmed) announce('error', '邮件选择已变化，已取消翻译。');
      return;
    }
    await runExclusive(`translate:${target.uid}`, async () => {
      setMessageContentView('translation');
      setTranslation((current) => ({ ...current, loading: true, error: '' }));
      try {
        const result = await api.translate(target.uid);
        if (!targetStillValid(target.uid, target.message) || !sameUid(result.mail_id, target.uid)) return;
        setTranslation({ data: result, loading: false, error: '' });
        announce('success', '翻译已完成。');
        await loadActions();
      } catch (error) {
        setTranslation((current) => ({ ...current, loading: false, error: errorMessage(error) }));
      }
    });
  }

  async function createDraftForSelected() {
    const target = validateTarget();
    if (!target) return;
    const confirmed = await askConfirm({
      title: '确认生成回复草稿',
      message: '邮件内容会发送给 DeepSeek。生成结果只保存到本地，发送前仍会展示最终内容并再次确认。',
      confirmLabel: '生成草稿',
      tone: 'warning',
      details: <ConfirmDetail rows={[['邮件', target.message.subject], ['发件人', target.message.sender]]} />,
    });
    if (!confirmed || !targetStillValid(target.uid, target.message)) {
      if (confirmed) announce('error', '邮件选择已变化，已取消生成草稿。');
      return;
    }
    await runExclusive(`draft-create:${target.uid}`, async () => {
      announce('loading', '正在生成回复草稿…');
      try {
        const created = await api.createDraft(target.uid);
        if (!targetStillValid(target.uid, target.message)) return;
        await loadDrafts('pending', { preferredId: created.draft_id, preferredMailId: target.uid });
        setRightView('drafts');
        setMobileStage('right');
        announce('success', '草稿已生成，请核对后再发送。');
        await Promise.all([
          loadQueue(queueStatusRef.current),
          loadActions(),
          refreshSearchIfInitialized(),
        ]);
      } catch (error) {
        announce('error', errorMessage(error));
      }
    });
  }

  async function moveSelectedToTrash() {
    const target = validateTarget();
    if (!target) return;
    const confirmed = await askConfirm({
      title: '确认移动到垃圾箱',
      message: '这会把邮件移动到 QQ 邮箱垃圾箱，不执行永久删除。请再次核对操作对象。',
      confirmLabel: '移动到垃圾箱',
      tone: 'danger',
      details: <ConfirmDetail rows={[['UID', target.uid], ['邮件', target.message.subject], ['发件人', target.message.sender]]} />,
    });
    if (!confirmed || !targetStillValid(target.uid, target.message)) {
      if (confirmed) announce('error', '邮件选择已变化，危险操作已取消。');
      return;
    }
    await runExclusive(`trash:${target.uid}`, async () => {
      try {
        await api.moveToTrash(target.uid);
        announce('success', '邮件已移动到垃圾箱。');
        clearSelection();
        await Promise.all([
          loadRecent(offset),
          loadQueue(queueStatusRef.current),
          loadActions(),
          refreshSearchIfInitialized(),
        ]);
      } catch (error) {
        announce('error', errorMessage(error));
      }
    });
  }

  async function changeQueueStatus(uid: string, status: QueueStatus) {
    if (!uid) return;
    if (sameUid(uid, selectedIdRef.current) && !validateTarget()) return;
    await runExclusive(`queue-status:${normalizeUid(uid)}`, async () => {
      try {
        await api.setQueueStatus(uid, status);
        setInsights((current) => ({
          ...current,
          data: current.data.map((item) => (sameUid(item.uid, uid) ? { ...item, queue_status: status } : item)),
        }));
        announce('success', `队列状态已更新为“${queueLabel[status]}”。`);
        await Promise.all([
          loadQueue(queueStatusRef.current),
          leftViewRef.current === 'insights' ? loadInsights(mailViewRef.current) : Promise.resolve(),
          loadActions(),
          refreshSearchIfInitialized(),
        ]);
      } catch (error) {
        announce('error', errorMessage(error));
      }
    });
  }

  async function changeInsightLabels(importance: MailImportance, needsReply: boolean) {
    const target = selectedInsight.data;
    if (!target) {
      announce('error', '当前邮件还没有本地洞察，先整理邮件后再修改标记。');
      return;
    }
    await runExclusive(`insight-labels:${normalizeUid(target.uid)}`, async () => {
      try {
        const updated = await api.updateInsightLabels(target.uid, importance, needsReply);
        updateInsightEverywhere(updated);
        announce('success', '邮件标记已更新。');
      } catch (error) {
        announce('error', `标记更新失败：${errorMessage(error)}`);
      }
    });
  }

  async function submitInsightFeedback(feedbackValue: InsightFeedback) {
    const target = selectedInsight.data;
    if (!target) {
      announce('error', '当前邮件还没有本地洞察，先整理邮件后再反馈。');
      return;
    }
    await runExclusive(`insight-feedback:${normalizeUid(target.uid)}`, async () => {
      try {
        const saved = await api.submitInsightFeedback(target.uid, feedbackValue);
        const updated = {
          ...target,
          latest_feedback: saved.feedback,
          feedback_comment: saved.comment,
          feedback_updated_at: saved.updated_at,
        };
        updateInsightEverywhere(updated);
        announce('success', '反馈已记录，会用于后续优化判断。');
      } catch (error) {
        announce('error', `反馈保存失败：${errorMessage(error)}`);
      }
    });
  }

  function validateDraftSnapshot() {
    if (!selectedDraft || !draftEditor || selectedDraft.draft_id !== draftEditor.draftId) {
      announce('error', '草稿选择已变化，请重新选择。');
      return null;
    }
    const subject = draftEditor.subject;
    const body = draftEditor.body;
    if (!subject.trim() || !body.trim()) {
      announce('error', '主题和正文不能为空。');
      return null;
    }
    return { draft: selectedDraft, subject, body };
  }

  async function persistDraftSnapshot(draft: Draft, subject: string, body: string) {
    const updated = await api.updateDraft(draft.draft_id, subject, body);
    setDrafts((current) => ({
      ...current,
      data: current.data.map((item) => (item.draft_id === updated.draft_id ? updated : item)),
    }));
    setDraftEditor((current) => {
      if (!current || current.draftId !== updated.draft_id) return current;
      const next = {
        ...current,
        baselineSubject: subject,
        baselineBody: body,
      };
      draftEditorRef.current = next;
      return next;
    });
    return updated;
  }

  async function saveCurrentDraft() {
    const snapshot = validateDraftSnapshot();
    if (!snapshot) return;
    await runExclusive(`draft-save:${snapshot.draft.draft_id}`, async () => {
      try {
        await persistDraftSnapshot(snapshot.draft, snapshot.subject, snapshot.body);
        announce('success', '草稿已保存。');
        await loadActions();
      } catch (error) {
        announce('error', `草稿保存失败：${errorMessage(error)}`);
      }
    });
  }

  async function sendCurrentDraft() {
    const snapshot = validateDraftSnapshot();
    if (!snapshot) return;
    await runExclusive(`draft-send:${snapshot.draft.draft_id}`, async () => {
      sendingDraftIdRef.current = snapshot.draft.draft_id;
      setSendingDraftId(snapshot.draft.draft_id);
      try {
        let saved: Draft;
        try {
        announce('loading', '正在保存发送快照…');
        saved = await persistDraftSnapshot(snapshot.draft, snapshot.subject, snapshot.body);
        } catch (error) {
          announce('error', `草稿保存失败，未执行发送：${errorMessage(error)}`);
          return;
        }
        const confirmed = await askConfirm({
          title: '确认发送邮件',
          message: '以下内容已经保存为本次发送快照。确认后会通过 QQ SMTP 真实发送。',
          confirmLabel: '确认发送',
          tone: 'danger',
          details: <ConfirmDraft to={saved.to_addr} subject={snapshot.subject} body={snapshot.body} />,
        });
        if (!confirmed) {
          announce('success', '当前内容已保存，本次未发送。');
          return;
        }
        const currentEditor = draftEditorForId(saved.draft_id, draftEditorRef.current);
        if (!currentEditor || currentEditor.subject !== snapshot.subject || currentEditor.body !== snapshot.body) {
          announce('error', '草稿内容已变化，发送已取消，请重新确认。');
          return;
        }
        try {
          announce('loading', '正在发送，请勿重复操作…');
          const result = await api.sendDraft(saved.draft_id);
          announce('success', result.summary);
          await Promise.all([
            loadDrafts(draftFilterRef.current, { forceEditor: true }),
            loadActions(),
            loadQueue(queueStatusRef.current),
          ]);
        } catch (error) {
          announce('error', `发送失败：${errorMessage(error)}`);
          await loadDrafts('all', { preferredId: saved.draft_id, forceEditor: true });
        }
      } finally {
        if (sendingDraftIdRef.current === snapshot.draft.draft_id) {
          sendingDraftIdRef.current = '';
          setSendingDraftId('');
        }
      }
    });
  }

  async function selectDraft(draftId: string) {
    if (sendingDraftIdRef.current) return;
    if (draftId === selectedDraftId) return;
    if (!(await guardDraftChanges('切换草稿'))) return;
    selectDraftLocally(drafts.data.find((item) => item.draft_id === draftId));
  }

  async function changeDraftFilter(filter: DraftFilter) {
    if (sendingDraftIdRef.current) return;
    if (filter === draftFilterRef.current) return;
    if (!(await guardDraftChanges('切换草稿状态'))) return;
    await loadDrafts(filter, { forceEditor: true });
  }

  async function checkExternalHealth(target: ExternalHealthTarget) {
    setHealthOpen(false);
    const confirmed = await askConfirm({
      title: `确认执行${externalHealthLabel[target]}检查`,
      message: '该检查会连接外部服务验证当前配置，但不会展示或保存授权码、密钥等敏感值。',
      confirmLabel: '开始检查',
      tone: 'warning',
      details: <ConfirmDetail rows={[['检查项', externalHealthLabel[target]], ['网络访问', '会连接对应外部服务']]} />,
    });
    setHealthOpen(true);
    if (!confirmed) return;
    await runExclusive(`health:${target}`, async () => {
      try {
        const result = await api.externalHealth(target);
        setExternalHealth((current) => ({ ...current, [target]: result }));
        announce(result.ok ? 'success' : 'error', `${externalHealthLabel[target]}：${result.detail}`);
      } catch (error) {
        announce('error', `${externalHealthLabel[target]}检查失败：${errorMessage(error)}`);
      }
    });
  }

  async function runSecretaryInspection() {
    await runExclusive('secretary-inspection', async () => {
      const reportWasOpen = inspectionOpen && Boolean(inspectionReport);
      const confirmed = await askConfirm({
        title: '确认开始秘书巡检',
        message: '将检查最新 20 封邮件；只有未读且尚未分类的邮件会发送给 DeepSeek。巡检只生成处理计划，不会自动执行任何邮件操作。',
        confirmLabel: '开始巡检',
        tone: 'warning',
        details: <ConfirmDetail rows={[['范围', '最新 20 封邮件'], ['模型处理', '仅未读且未分类'], ['执行边界', '只生成计划，不自动操作']]} />,
      });
      if (!confirmed) return;
      try {
        setInspectionError('');
        announce('loading', '秘书正在巡检最新 20 封邮件…');
        const result = await api.secretaryInspection(pageSize);
        setInspectionReport(result);
        setInspectionOpen(true);
        const failureSummary = result.failed_count > 0 ? `，${result.failed_count} 封处理失败，其他结果已保留` : '';
        announce('success', `巡检完成：当前 ${result.current_actionable_count} 封需要跟进${failureSummary}。`);
        void Promise.all([loadQueue(queueStatusRef.current), loadActions(), refreshSearchIfInitialized()]);
      } catch (error) {
        const message = errorMessage(error);
        if (reportWasOpen) {
          setInspectionError(`重新巡检失败，以下仍是上次报告：${message}`);
        }
        announce('error', `巡检失败：${message}`);
      }
    });
  }

  function openInspectionItem(item: InspectionPlanItem) {
    setInspectionOpen(false);
    void selectMessage(item.uid, { markSeenOnOpen: true });
  }

  async function refreshWorkspace() {
    if (sendingDraftIdRef.current) {
      announce('error', '草稿正在发送，请等待结果后再刷新。');
      return;
    }
    if (!(await guardDraftChanges('刷新工作台'))) return;
    announce('loading', '正在刷新当前工作台…');
    if (desktopRuntime && desktopConnected) {
      try {
        await syncDesktopMailbox({ openSummary: false });
      } catch (error) {
        setStartupSummary((current) => ({ ...current, loading: false, error: errorMessage(error) }));
        announce('error', `刷新前同步失败：${errorMessage(error)}`);
        return;
      }
    }
    const listTask =
      leftViewRef.current === 'recent'
        ? loadRecent(0)
        : leftViewRef.current === 'queue'
          ? loadQueue(queueStatusRef.current)
          : leftViewRef.current === 'insights'
            ? loadInsights(mailViewRef.current)
            : runSearch(appliedSearchFiltersRef.current);
    await Promise.all([listTask, loadLocalHealth(), loadDrafts(draftFilterRef.current, { forceEditor: true }), loadActions()]);
    announce('success', '工作台已刷新。');
  }

  function handleMailListScroll(event: UIEvent<HTMLDivElement>) {
    if (leftViewRef.current !== 'recent' || recent.loading || !hasMore) return;
    const target = event.currentTarget;
    if (target.scrollTop + target.clientHeight < target.scrollHeight - 96) return;
    void loadRecent(offset + pageSize, { append: true });
  }

  function ensureSelectedMailVisible() {
    const list = mailListRef.current;
    if (!list || !selectedId) return;
    const selectedUid = normalizeUid(selectedId);
    const card = Array.from(list.querySelectorAll<HTMLElement>('[data-mail-uid]'))
      .find((node) => node.dataset.mailUid === selectedUid);
    if (!card) return;
    const listRect = list.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    if (listRect.height <= 0 || cardRect.height <= 0) return;
    const topGap = cardRect.top - listRect.top;
    const bottomGap = cardRect.bottom - listRect.bottom;
    if (topGap >= 8 && bottomGap <= -8) return;
    const nextTop = bottomGap > 0
      ? list.scrollTop + bottomGap + 12
      : list.scrollTop + topGap - 12;
    scrollElementTo(list, Math.max(0, nextTop), 'smooth');
  }

  function scrollMailListToTop() {
    if (mailListRef.current) scrollElementTo(mailListRef.current, 0, 'smooth');
  }

  function switchLeftView(view: LeftView) {
    setLeftView(view);
    leftViewRef.current = view;
    if (view !== 'insights') {
      mailViewRef.current = 'all';
      setMailView('all');
    }
    if (view === 'queue' && queue.data.length === 0 && !queue.loading) void loadQueue(queueStatusRef.current);
    if (view === 'search' && search.data.length === 0 && !search.loading) void runSearch(searchFilters);
  }

  const listItems = useMemo<ListItem[]>(() => {
    if (leftView === 'recent') return recent.data.map(messageToListItem);
    if (leftView === 'queue') return queue.data.map(triageToListItem);
    if (leftView === 'insights') {
      const insightMap = new Map(insights.data.map((item) => [normalizeUid(item.uid), item]));
      const currentUids = new Set(agentMailbox.data.map((item) => normalizeUid(item.id)));
      if (mailView !== 'all') {
        return sortAgentMailboxItems(
          insights.data
            .filter((item) => currentUids.has(normalizeUid(item.uid)))
            .map(insightToListItem)
            .filter(isVisibleAgentItem),
        );
      }
      const mailboxItems = sortAgentMailboxItems(
        agentMailbox.data
          .map((message) => messageWithInsightToListItem(message, insightMap.get(normalizeUid(message.id))))
          .filter(isVisibleAgentItem),
      );
      const mailboxUids = new Set(mailboxItems.map((item) => normalizeUid(item.uid)));
      return [
        ...fetchFailures
          .filter((failure) => !mailboxUids.has(normalizeUid(`uid:${failure.uid}`)))
          .map(fetchFailureToListItem),
        ...mailboxItems,
      ];
    }
    return search.data.map(searchToListItem);
  }, [agentMailbox.data, fetchFailures, insights.data, leftView, mailView, queue.data, recent.data, search.data]);
  const activeListResource = leftView === 'recent' ? recent : leftView === 'queue' ? queue : leftView === 'insights' ? insights : search;
  const selectedInsightRequiresReview = Boolean(
    selectedInsight.data &&
      (selectedInsight.data.analysis_status !== 'analyzed' || selectedInsight.data.confidence < 0.55),
  );

  useEffect(() => {
    ensureSelectedMailVisible();
  }, [listItems, selectedId, leftView, mailView]);

  return (
    <div className={`app-shell theme-${theme} mobile-stage-${mobileStage}`}>
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-icon"><img src={miaogentLogo} alt="" /></div>
          <div>
            <h1><button className="brand-title-button" type="button" onClick={handleTitleClick}>MiaoGent</button></h1>
            <p>邮件工作台</p>
          </div>
        </div>
        <div className="topbar-actions">
          <button
            className={`health-trigger ${health.loading ? 'is-loading' : healthOk ? 'is-ok' : 'is-warning'}`}
            onClick={() => setHealthOpen(true)}
            aria-label={`打开配置体检，当前状态：${health.loading ? '检查中' : healthOk ? '正常' : '异常'}`}
          >
            <Badge tone={healthOk ? 'success' : 'warning'}>{health.loading ? '配置检查中' : healthOk ? '配置正常' : '配置待检查'}</Badge>
          </button>
          <IconButton icon={theme === 'dark' ? 'sun-2-outline' : 'moon-outline'} label="切换主题" onClick={() => setTheme((value) => (value === 'dark' ? 'light' : 'dark'))} />
          {desktopRuntime && <IconButton icon="settings-outline" label="桌面 Agent 设置" onClick={() => openDesktopSettings('settings')} />}
          <IconButton icon="refresh-outline" label="刷新工作台" onClick={() => void runExclusive('refresh-workspace', refreshWorkspace)} disabled={Boolean(sendingDraftId) || isPending('refresh-workspace')} />
          <button
            className="btn btn-primary topbar-primary"
            aria-label={
              desktopRuntime
                ? desktopConnected
                  ? isPending('desktop-sync') ? '整理中' : '立即整理邮件'
                  : '打开桌面 Agent 设置'
                : isPending('secretary-inspection') ? '巡检中' : '开始巡检'
            }
            onClick={() => {
              if (desktopRuntime && !desktopConnected) openDesktopSettings();
              else void (desktopConnected ? runDesktopSync() : runSecretaryInspection());
            }}
            disabled={desktopRuntime ? desktopConnected && isPending('desktop-sync') : isPending('secretary-inspection')}
          >
            <AppIcon icon="magic-stick-3-outline" />
            <span>
              {desktopRuntime
                ? desktopConnected
                  ? isPending('desktop-sync') ? '整理中…' : '立即整理'
                  : '配置桌面 Agent'
                : isPending('secretary-inspection') ? '巡检中…' : '开始巡检'}
            </span>
          </button>
        </div>
      </header>

      {desktopRuntime && desktopConfigIncomplete && (
        <div className="onboarding-banner" role="status">
          <div>
            <strong>桌面 Agent 配置未完成</strong>
            <span>补齐 QQ 授权码和 DeepSeek Key 后，才能后台巡检、判断重要邮件并生成草稿。</span>
          </div>
          <button className="btn btn-secondary" type="button" onClick={() => openDesktopSettings('onboarding')}>
            继续配置
          </button>
        </div>
      )}

      <div className="feedback-region" aria-live="polite" aria-atomic="true">
        {feedback && (
          <div className={`toast-strip is-${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>
            <span className="toast-icon">
              <AppIcon icon={feedback.kind === 'error' ? 'danger-triangle-outline' : feedback.kind === 'success' ? 'check-circle-outline' : 'refresh-outline'} />
            </span>
            <span>{feedback.message}</span>
            {feedback.kind !== 'loading' && <button className="toast-close" aria-label="关闭提示" onClick={() => setFeedback(null)}>×</button>}
          </div>
        )}
      </div>

      <main className="workbench-grid">
        <aside className="panel sidebar-panel">
          <div className="mail-view-tabs" role="tablist" aria-label="Agent 邮件视图">
            {([
              ['all', '全部'],
              ['reply', '待回复'],
              ['important', '重要'],
              ['urgent', '紧急'],
              ['general', '一般'],
            ] as Array<[MailView, string]>).map(([value, label]) => (
              <button
                key={value}
                role="tab"
                aria-selected={mailView === value}
                className={mailView === value ? 'is-active' : ''}
                onClick={() => selectMailView(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <SegmentedTabs
            label="邮件列表视图"
            value={leftView}
            options={[
              { value: 'recent', label: '最近' },
              { value: 'queue', label: 'AI 待办' },
              { value: 'search', label: '搜索' },
            ]}
            onChange={switchLeftView}
          />

          {leftView === 'recent' && (
            <PanelHeader
              title="最近邮件"
              meta={`第 ${pageNumber} 页 · ${recent.data.length} 封`}
              metaInline
              actions={
                <>
                  <IconButton icon="alt-arrow-left-outline" label="上一页" disabled={offset === 0 || recent.loading} onClick={() => void loadRecent(Math.max(0, offset - pageSize))} />
                  <IconButton icon="alt-arrow-right-outline" label="下一页" disabled={!hasMore || recent.loading} onClick={() => void loadRecent(offset + pageSize)} />
                </>
              }
            />
          )}

          {leftView === 'queue' && (
            <div className="list-controls-block">
              <SegmentedTabs
                label="AI 队列状态"
                value={queueStatus}
                compact
                options={[
                  { value: 'pending', label: '待处理' },
                  { value: 'later', label: '稍后' },
                  { value: 'done', label: '已处理' },
                  { value: 'skipped', label: '已跳过' },
                ]}
                onChange={(status) => void loadQueue(status)}
              />
            </div>
          )}

          {leftView === 'search' && (
            <SearchForm
              filters={searchFilters}
              loading={search.loading}
              onChange={setSearchFilters}
              onSubmit={() => void runSearch(searchFilters)}
              onClear={() => {
                setSearchFilters(emptySearchFilters);
                void runSearch(emptySearchFilters);
              }}
            />
          )}

          {leftView === 'insights' && (
            <PanelHeader
              title={{ reply: '待回复邮件', important: '重要邮件', urgent: '紧急邮件', general: '一般邮件', all: '全部邮件' }[mailView]}
              meta={`${listItems.length} 项`}
              metaInline
              className="mail-count-header"
            />
          )}

          <LoadingLine active={activeListResource.loading} />
          {activeListResource.error && (
            <InlineError
              message={activeListResource.error}
              onRetry={() => {
                if (leftView === 'recent') void loadRecent(offset);
                else if (leftView === 'queue') void loadQueue(queueStatus);
                else if (leftView === 'insights') void loadInsights(mailView);
                else void runSearch(appliedSearchFilters);
              }}
            />
          )}
          <div className="mail-list-shell">
            <div ref={mailListRef} className="mail-list scroll-area" aria-busy={activeListResource.loading} onScroll={handleMailListScroll}>
              {listItems.map((item) => (
                <MailListCard
                  key={`${leftView}-${item.uid}`}
                  item={item}
                  selected={sameUid(item.uid, selectedId)}
                  pending={detail.loading && sameUid(item.uid, selectedId)}
                  showRestore={leftView === 'queue' && queueStatus !== 'pending'}
                  restorePending={isPending(`queue-status:${normalizeUid(item.uid)}`)}
                  onOpen={() => void selectMessage(item.uid)}
                  onRestore={() => void changeQueueStatus(item.uid, 'pending')}
                />
              ))}
              {!activeListResource.loading && listItems.length === 0 && (
                <EmptyState
                  icon={leftView === 'search' ? 'inbox-unread-outline' : 'clipboard-remove-outline'}
                  title={leftView === 'recent' ? '当前页没有邮件' : leftView === 'queue' ? `暂无${queueLabel[queueStatus]}事项` : leftView === 'insights' ? '当前视图没有邮件' : '没有匹配结果'}
                  detail={leftView === 'recent' && offset > 0 ? '可以返回上一页' : undefined}
                />
              )}
              {leftView === 'recent' && recent.loading && recent.data.length > 0 && (
                <div className="list-tail-status" role="status">正在加载更多邮件…</div>
              )}
              {leftView === 'recent' && !recent.loading && recent.data.length > 0 && !hasMore && (
                <div className="list-tail-status">已加载全部可见邮件</div>
              )}
            </div>
            <button className="mail-list-float-button" type="button" onClick={scrollMailListToTop} aria-label="回到邮件列表顶部">
              <AppIcon icon="alt-arrow-left-outline" width={15} />
            </button>
          </div>
        </aside>

        <section className="panel reading-panel">
          <div className="mobile-panel-toolbar">
            <button className="text-button" onClick={() => setMobileStage('list')}>← 返回列表</button>
            <button className="text-button" onClick={() => setMobileStage('right')} disabled={!selectedDetail}>操作与草稿 →</button>
          </div>
          <LoadingLine active={detail.loading} />
          <div className="message-head">
            <div className="message-badges">
              {selectedDetail && <Badge tone={selectedDetail.is_seen ? 'neutral' : 'warning'}>{selectedDetail.is_seen ? '已读' : '未读'}</Badge>}
              {selectedQueue && <Badge tone="info">{queueLabel[selectedQueue.queue_status] ?? selectedQueue.queue_status}</Badge>}
              {selectedQueue?.classification && <Badge tone={classificationTone(selectedQueue.classification)}>{classificationLabel[selectedQueue.classification] ?? selectedQueue.classification}</Badge>}
              {selectedInsight.data && (selectedInsightRequiresReview ? (
                <Badge tone="warning">待人工查看</Badge>
              ) : (
                <Badge tone={importanceTone(selectedInsight.data.importance)}>{importanceLabel[selectedInsight.data.importance] ?? selectedInsight.data.importance}</Badge>
              ))}
              {selectedInsight.data?.needs_reply && !['sent', 'not_needed'].includes(selectedInsight.data.reply_status) && <Badge tone="info">需要回复</Badge>}
              {selectedInsight.data?.reply_status === 'sent' && <Badge tone="success">已回复</Badge>}
            </div>
            <h2>{selectedDetail?.subject ?? (detail.loading ? '正在读取邮件…' : '请选择邮件')}</h2>
            {selectedDetail && (
              <div className="message-meta-grid">
                <span><strong>发件人</strong>{selectedDetail.sender}</span>
                <span><strong>收件人</strong>{selectedDetail.recipient}</span>
                <span><strong>时间</strong>{formatMailDate(selectedDetail.date, 'detail') || '-'}</span>
              </div>
            )}
          </div>
          <div className="message-body scroll-area">
            {detail.error && <InlineError message={detail.error} onRetry={() => selectedId && void selectMessage(selectedId)} />}
            {selectedDetail ? (
              <>
                {selectedInsight.data && <InsightSummary item={selectedInsight.data} />}
                {translationVisible && (
                  <SegmentedTabs
                    label="邮件正文视图"
                    value={messageContentView}
                    compact
                    options={[
                      { value: 'source', label: '原文' },
                      { value: 'translation', label: translation.loading ? '译文生成中' : '译文' },
                    ]}
                    onChange={setMessageContentView}
                  />
                )}
                {messageContentView === 'translation' && translationVisible ? (
                  <>
                    {translation.loading && <div className="translation-panel" role="status">正在生成中文翻译…</div>}
                    {translation.error && <InlineError message={translation.error} onRetry={() => void translateSelected()} />}
                    {selectedTranslation && (
                      <section className="translation-panel">
                        <div className="section-title"><AppIcon icon="translation-2-outline" /><span>中文翻译</span></div>
                        <h3>{selectedTranslation.subject_zh}</h3>
                        <pre>{selectedTranslation.body_zh}</pre>
                      </section>
                    )}
                  </>
                ) : (
                  <>
                    <article className="mail-content">{selectedDetail.body || selectedDetail.snippet || '无正文'}</article>
                    <ResourceBar message={selectedDetail} />
                  </>
                )}
              </>
            ) : !detail.loading && !detail.error ? (
              <EmptyState icon="inbox-unread-outline" title="选择一封邮件开始处理" detail="打开邮件后会自动同步标记为已读" />
            ) : null}
          </div>
        </section>

        <aside className="panel action-panel">
          <div className="mobile-panel-toolbar">
            <button className="text-button" onClick={() => setMobileStage(selectedDetail ? 'reading' : 'list')}>← 返回阅读</button>
          </div>
          <SegmentedTabs
            label="右侧工作区"
            value={rightView}
            options={[
              { value: 'actions', label: '操作' },
              { value: 'drafts', label: '草稿', count: drafts.data.length },
              { value: 'history', label: '记录', count: actions.data.length },
            ]}
            onChange={setRightView}
          />

          {rightView === 'actions' && (
            <MailActions
              detail={selectedDetail}
              triage={selectedQueue}
              insight={selectedInsight.data}
              locked={Boolean(sendingDraftId)}
              pending={(key) => Boolean(selectedId && isPending(`${key}:${key === 'queue-status' ? normalizeUid(selectedId) : selectedId}`))}
              labelPending={Boolean(selectedInsight.data && isPending(`insight-labels:${normalizeUid(selectedInsight.data.uid)}`))}
              feedbackPending={Boolean(selectedInsight.data && isPending(`insight-feedback:${normalizeUid(selectedInsight.data.uid)}`))}
              onTranslate={() => void translateSelected()}
              onDraft={() => void createDraftForSelected()}
              onLabelsChange={(importance, needsReply) => void changeInsightLabels(importance, needsReply)}
              onFeedback={(value) => void submitInsightFeedback(value)}
              onStatus={(status) => selectedId && void changeQueueStatus(selectedId, status)}
              onTrash={() => void moveSelectedToTrash()}
            />
          )}

          {rightView === 'drafts' && (
            <DraftWorkspace
              drafts={drafts.data}
              selectedDraft={selectedDraft}
              editor={draftEditor}
              dirty={draftDirty}
              filter={draftFilter}
              loading={drafts.loading}
              error={drafts.error}
              currentMailId={selectedId}
              isSaving={Boolean(selectedDraft && isPending(`draft-save:${selectedDraft.draft_id}`))}
              isSending={Boolean(sendingDraftId)}
              locked={Boolean(sendingDraftId)}
              onFilterChange={(filter) => void changeDraftFilter(filter)}
              onSelect={(draftId) => void selectDraft(draftId)}
              onEditorChange={(patch) =>
                setDraftEditor((current) => {
                  const next = current ? { ...current, ...patch } : current;
                  draftEditorRef.current = next;
                  return next;
                })
              }
              onSave={() => void saveCurrentDraft()}
              onSend={() => void sendCurrentDraft()}
              onRetry={() => void loadDrafts(draftFilterRef.current, { forceEditor: !draftDirty })}
            />
          )}

          {rightView === 'history' && (
            <ActivityPanel resource={actions} onRetry={() => void loadActions()} />
          )}
        </aside>
      </main>

      <nav className="mobile-bottom-nav" aria-label="移动端工作区">
        <button className={mobileStage === 'list' ? 'is-active' : ''} onClick={() => setMobileStage('list')}>列表</button>
        <button className={mobileStage === 'reading' ? 'is-active' : ''} onClick={() => setMobileStage('reading')} disabled={!selectedId}>阅读</button>
        <button className={mobileStage === 'right' ? 'is-active' : ''} onClick={() => setMobileStage('right')} disabled={!selectedId}>操作/草稿</button>
      </nav>

      <ConfirmDialog state={confirmState} onCancel={() => closeConfirm(false)} onConfirm={() => closeConfirm(true)} />
      <DevtoolsPasswordDialog
        open={devtoolsUnlockOpen}
        error={devtoolsUnlockError}
        pending={isPending('open-devtools')}
        onCancel={() => setDevtoolsUnlockOpen(false)}
        onUnlock={(password) => void unlockDevtools(password)}
      />
      <HealthDrawer
        open={healthOpen}
        localItems={health.data}
        localLoading={health.loading}
        localError={health.error}
        externalItems={externalHealth}
        isChecking={(target) => isPending(`health:${target}`)}
        onClose={() => setHealthOpen(false)}
        onRetryLocal={() => void loadLocalHealth()}
        onCheck={(target) => void checkExternalHealth(target)}
      />
      <InspectionReport
        open={inspectionOpen}
        focusEnabled={!confirmState}
        report={inspectionReport}
        error={inspectionError}
        pending={isPending('secretary-inspection')}
        onClose={() => setInspectionOpen(false)}
        onRerun={() => void runSecretaryInspection()}
        onSelect={openInspectionItem}
      />
      <StartupSummaryDrawer
        open={startupSummaryOpen}
        summary={startupSummary.data}
        loading={startupSummary.loading}
        error={startupSummary.error}
        onClose={() => setStartupSummaryOpen(false)}
        onRetry={() => void runDesktopSync()}
        onSelect={(uid) => {
          setStartupSummaryOpen(false);
          void selectMessage(uid, { markSeenOnOpen: false });
        }}
      />
      <DesktopSettings
        open={desktopSettingsOpen}
        mode={desktopSettingsMode}
        onClose={() => setDesktopSettingsOpen(false)}
        onSaved={() => {
          setDesktopSettingsOpen(false);
          setDesktopConnected(false);
          setDesktopConfigIncomplete(false);
          void refreshDesktopConfigState();
          announce('success', '桌面设置已保存，后台 Agent 正在重新连接。');
        }}
        onCleared={(report) => {
          setDesktopConnected(false);
          setDesktopConfigIncomplete(true);
          setDesktopSettingsMode('onboarding');
          const failedCount = report.failedPaths.length;
          announce(
            failedCount > 0 ? 'error' : 'success',
            failedCount > 0
              ? `本机数据已部分清除，${failedCount} 个路径清理失败，请退出应用后重试或卸载时清理。`
              : '本机密钥和数据已清除，请重新配置 MiaoGent。',
            failedCount > 0 ? { persist: true } : undefined,
          );
        }}
      />
    </div>
  );
}

function SearchForm({
  filters,
  loading,
  onChange,
  onSubmit,
  onClear,
}: {
  filters: SearchFilters;
  loading: boolean;
  onChange: (filters: SearchFilters) => void;
  onSubmit: () => void;
  onClear: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <form
      className="search-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label className="sr-only" htmlFor="message-search">搜索发件人或主题</label>
      <div className="search-control">
        <span className="search-icon" aria-hidden="true" />
        <input
          ref={inputRef}
          id="message-search"
          type="text"
          value={filters.keyword}
          placeholder="搜索发件人或主题"
          onChange={(event) => onChange({ ...filters, keyword: event.target.value })}
        />
        <button
          type="button"
          className="search-clear"
          aria-label="清空搜索"
          disabled={!filters.keyword && filters.is_seen === '' && filters.classification === '' && filters.queue_status === ''}
          onClick={() => {
            onClear();
            inputRef.current?.focus();
          }}
        >
          ×
        </button>
      </div>
      <div className="search-filter-grid">
        <CustomDropdown
          label="已读状态"
          value={filters.is_seen}
          className="search-filter-dropdown"
          options={[
            { value: '', label: '全部' },
            { value: 'false', label: '未读' },
            { value: 'true', label: '已读' },
          ]}
          onChange={(is_seen) => onChange({ ...filters, is_seen })}
        />
        <CustomDropdown
          label="AI 分类"
          value={filters.classification}
          className="search-filter-dropdown"
          options={[
            { value: '', label: '全部' },
            { value: 'respond', label: '需回复' },
            { value: 'notify', label: '通知' },
            { value: 'ignore', label: '忽略' },
          ]}
          onChange={(classification) => onChange({ ...filters, classification })}
        />
        <CustomDropdown
          label="队列状态"
          value={filters.queue_status}
          className="search-filter-dropdown"
          options={[
            { value: '', label: '全部' },
            { value: 'pending', label: '待处理' },
            { value: 'later', label: '稍后' },
            { value: 'done', label: '已处理' },
            { value: 'skipped', label: '已跳过' },
          ]}
          onChange={(queue_status) => onChange({ ...filters, queue_status })}
        />
      </div>
      <button className="btn btn-primary search-submit" type="submit" disabled={loading}>{loading ? '搜索中…' : '搜索'}</button>
    </form>
  );
}

function MailListCard({
  item,
  selected,
  pending,
  showRestore,
  restorePending,
  onOpen,
  onRestore,
}: {
  item: ListItem;
  selected: boolean;
  pending: boolean;
  showRestore: boolean;
  restorePending: boolean;
  onOpen: () => void;
  onRestore: () => void;
}) {
  const requiresReview = Boolean(
    item.analysisStatus &&
      (item.analysisStatus !== 'analyzed' || (item.confidence ?? 0) < 0.55),
  );
  return (
    <article
      className={`mail-card ${selected ? 'is-active' : ''} ${item.isSeen === false ? 'is-unread' : ''}`}
      data-mail-uid={normalizeUid(item.uid)}
    >
      <button className="mail-card-main" onClick={onOpen} aria-current={selected ? 'true' : undefined}>
        <div className="mail-card-top">
          <span className="mail-sender">{item.sender || '未知发件人'}</span>
          {item.isSeen !== null && <Badge tone={item.isSeen ? 'neutral' : 'warning'}>{item.isSeen ? '已读' : '未读'}</Badge>}
        </div>
        <div className="mail-subject">{item.subject || '(无主题)'}</div>
        {item.summary && <div className="mail-summary">{item.summary}</div>}
        <div className="mail-meta-row">
          <div className="mail-meta">{formatMailDate(item.date) || item.uid}</div>
          <div className="queue-tags">
            {item.classification && <Badge tone={classificationTone(item.classification)}>{classificationLabel[item.classification] ?? item.classification}</Badge>}
            {item.importance && !requiresReview && <Badge tone={importanceTone(item.importance)}>{importanceLabel[item.importance] ?? item.importance}</Badge>}
            {item.needsReply && !['sent', 'not_needed'].includes(item.replyStatus ?? '') && <Badge tone="info">待回复</Badge>}
            {item.replyStatus === 'sent' && <Badge tone="success">已回复</Badge>}
            {requiresReview && <Badge tone="warning">待人工查看</Badge>}
            {item.draftId && item.replyStatus === 'draft_ready' && <Badge tone="success">草稿就绪</Badge>}
            {item.suggestedAction && <Badge tone="info">{actionLabel[item.suggestedAction] ?? item.suggestedAction}</Badge>}
            {item.queueStatus && <Badge>{queueLabel[item.queueStatus] ?? item.queueStatus}</Badge>}
            {pending && <Badge tone="info">读取中</Badge>}
          </div>
        </div>
      </button>
      {showRestore && (
        <button className="restore-button" onClick={onRestore} disabled={restorePending}>
          {restorePending ? '恢复中…' : '恢复待处理'}
        </button>
      )}
    </article>
  );
}

function MailActions({
  detail,
  triage,
  insight,
  locked,
  pending,
  labelPending,
  feedbackPending,
  onTranslate,
  onDraft,
  onLabelsChange,
  onFeedback,
  onStatus,
  onTrash,
}: {
  detail: MailMessage | null;
  triage: TriageItem | undefined;
  insight: MailInsight | null;
  locked: boolean;
  pending: (key: string) => boolean;
  labelPending: boolean;
  feedbackPending: boolean;
  onTranslate: () => void;
  onDraft: () => void;
  onLabelsChange: (importance: MailImportance, needsReply: boolean) => void;
  onFeedback: (feedback: InsightFeedback) => void;
  onStatus: (status: QueueStatus) => void;
  onTrash: () => void;
}) {
  const disabled = !detail || locked;
  return (
    <section className="mail-actions-panel">
      <PanelHeader title="邮件操作" meta={detail ? `UID ${detail.id}` : '先选择邮件'} />
      <InsightLabelEditor
        insight={insight}
        disabled={disabled}
        pending={labelPending}
        feedbackPending={feedbackPending}
        onChange={onLabelsChange}
        onFeedback={onFeedback}
      />
      {triage && (
        <div className="advice-box">
          <div className="section-title"><AppIcon icon="lightbulb-bolt-outline" /><span>AI 建议：{actionLabel[triage.suggested_action] ?? triage.suggested_action}</span></div>
          <p>{triage.action_reason || triage.reason || '暂无补充说明'}</p>
        </div>
      )}
      <div className="action-group">
        <div className="action-group-title">理解与生成</div>
        <div className="button-grid">
          <ActionButton icon="translation-2-outline" label={pending('translate') ? '翻译中…' : '翻译'} disabled={disabled || pending('translate')} onClick={onTranslate} />
          <ActionButton icon="pen-new-square-outline" label={pending('draft-create') ? '生成中…' : '生成草稿'} disabled={disabled || pending('draft-create')} onClick={onDraft} />
        </div>
      </div>
      <div className="action-group">
        <div className="action-group-title">状态处理</div>
        <div className="button-grid status-button-grid">
          <SmallButton label="已处理" disabled={disabled || pending('queue-status')} onClick={() => onStatus('done')} />
          <SmallButton label="稍后" disabled={disabled || pending('queue-status')} onClick={() => onStatus('later')} />
          <SmallButton label="跳过" disabled={disabled || pending('queue-status')} onClick={() => onStatus('skipped')} />
        </div>
      </div>
      <div className="action-group danger-zone">
        <div className="action-group-title">危险操作</div>
        <ActionButton icon="trash-bin-trash-outline" label={pending('trash') ? '移动中…' : '移动到垃圾箱'} danger disabled={disabled || pending('trash')} onClick={onTrash} />
      </div>
    </section>
  );
}

function InsightLabelEditor({
  insight,
  disabled,
  pending,
  feedbackPending,
  onChange,
  onFeedback,
}: {
  insight: MailInsight | null;
  disabled: boolean;
  pending: boolean;
  feedbackPending: boolean;
  onChange: (importance: MailImportance, needsReply: boolean) => void;
  onFeedback: (feedback: InsightFeedback) => void;
}) {
  const currentImportance = insight?.importance ?? 'general';
  const currentNeedsReply = Boolean(insight?.needs_reply);
  const currentFeedback = insight?.latest_feedback ?? null;
  return (
    <div className="insight-label-editor">
      <div className="section-title"><AppIcon icon="mailbox-outline" /><span>邮件标记</span></div>
      {!insight ? (
        <p className="muted-hint">当前邮件还没有本地洞察，整理后可修改重要性和待回复状态。</p>
      ) : (
        <>
          <div className="label-button-row" role="group" aria-label="重要性标记">
            {([
              ['general', '一般'],
              ['important', '重要'],
              ['urgent', '紧急'],
            ] as Array<[MailImportance, string]>).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={currentImportance === value ? 'is-active' : ''}
                disabled={disabled || pending}
                onClick={() => onChange(value, currentNeedsReply)}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="label-toggle">
            <input
              type="checkbox"
              checked={currentNeedsReply}
              disabled={disabled || pending}
              onChange={(event) => onChange(currentImportance, event.target.checked)}
            />
            <span>待回复</span>
          </label>
          {pending && <p className="muted-hint">正在保存标记…</p>}
          <div className="insight-feedback-box">
            <div>
              <strong>AI 判断是否准确？</strong>
              <span>
                {currentFeedback === 'correct'
                  ? '已标记为判断正确'
                  : currentFeedback === 'wrong'
                    ? '已标记为不准确'
                    : '反馈会保存在本地，用于后续优化判断。'}
              </span>
            </div>
            <div className="label-button-row compact" role="group" aria-label="AI 判断反馈">
              <button
                type="button"
                className={currentFeedback === 'correct' ? 'is-active' : ''}
                disabled={disabled || feedbackPending}
                onClick={() => onFeedback('correct')}
              >
                正确
              </button>
              <button
                type="button"
                className={currentFeedback === 'wrong' ? 'is-active' : ''}
                disabled={disabled || feedbackPending}
                onClick={() => onFeedback('wrong')}
              >
                不准确
              </button>
            </div>
            {feedbackPending && <p className="muted-hint">正在保存反馈…</p>}
          </div>
        </>
      )}
    </div>
  );
}

function ActivityPanel({ resource: actionResource, onRetry }: { resource: Resource<ActionLog[]>; onRetry: () => void }) {
  return (
    <section className="activity-block">
      <PanelHeader title="操作记录" meta={`${actionResource.data.length} 条`} actions={<IconButton icon="refresh-outline" label="刷新记录" onClick={onRetry} disabled={actionResource.loading} />} />
      <LoadingLine active={actionResource.loading} />
      {actionResource.error && <InlineError message={actionResource.error} onRetry={onRetry} />}
      <div className="activity-list scroll-area">
        {actionResource.data.map((item) => (
          <div key={item.id} className="activity-item">
            <div><strong>{item.action}</strong><span>{item.uid ?? 'system'}</span></div>
            <p title={item.detail}>{item.detail || item.created_at}</p>
            <time>{item.created_at}</time>
          </div>
        ))}
        {!actionResource.loading && actionResource.data.length === 0 && <EmptyState icon="history-outline" title="暂无操作记录" />}
      </div>
    </section>
  );
}

function ResourceBar({ message }: { message: MailMessage }) {
  const items: Array<[IconName, string, string]> = [
    ['code-square-outline', 'HTML', message.html_body ? '有' : '无'],
    ['gallery-wide-outline', '远程图片', String(message.remote_images.length)],
    ['gallery-outline', '内嵌图片', String(message.inline_images.length)],
    ['paperclip-outline', '附件', String(message.attachments.length)],
  ];
  return (
    <div className="resource-grid">
      {items.map(([icon, label, value]) => (
        <div key={label} className="resource-card">
          <AppIcon icon={icon} />
          <div><span>{label}</span><strong>{value}</strong></div>
        </div>
      ))}
    </div>
  );
}

function ActionButton({ icon, label, onClick, danger, disabled }: { icon: IconName; label: string; onClick: () => void; danger?: boolean; disabled?: boolean }) {
  return (
    <button className={`btn action-button ${danger ? 'btn-danger' : 'btn-secondary'}`} onClick={onClick} disabled={disabled}>
      <AppIcon icon={icon} /><span>{label}</span>
    </button>
  );
}

function SmallButton({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) {
  return <button className="btn mini-button" onClick={onClick} disabled={disabled}>{label}</button>;
}

function classificationTone(classification: string): BadgeTone {
  if (classification === 'respond') return 'info';
  if (classification === 'notify') return 'success';
  return 'neutral';
}

function importanceTone(importance: string): BadgeTone {
  if (importance === 'urgent') return 'danger';
  if (importance === 'important') return 'warning';
  return 'neutral';
}

function messageToListItem(message: MailMessage): ListItem {
  return {
    uid: message.id,
    sender: message.sender,
    subject: message.subject,
    date: message.date,
    isSeen: message.is_seen,
  };
}

function triageToListItem(item: TriageItem): ListItem {
  return {
    uid: item.uid,
    sender: item.sender ?? '',
    subject: item.subject ?? '',
    date: item.updated_at,
    isSeen: item.is_seen ?? null,
    classification: item.classification,
    suggestedAction: item.suggested_action,
    queueStatus: item.queue_status,
    reason: item.reason,
    actionReason: item.action_reason,
  };
}

function insightToListItem(item: MailInsight): ListItem {
  return {
    uid: item.uid,
    sender: item.sender ?? '',
    subject: item.subject ?? '',
    date: item.date ?? item.updated_at,
    isSeen: item.is_seen,
    importance: item.importance,
    needsReply: item.needs_reply,
    summary: item.summary_zh,
    replyStatus: item.reply_status,
    analysisStatus: item.analysis_status,
    confidence: item.confidence,
    draftId: item.draft_id,
    queueStatus: item.queue_status ?? null,
  };
}

function messageWithInsightToListItem(message: MailMessage, insight: MailInsight | undefined): ListItem {
  return {
    ...messageToListItem(message),
    importance: insight?.importance,
    needsReply: insight?.needs_reply,
    summary: insight?.summary_zh,
    replyStatus: insight?.reply_status,
    analysisStatus: insight?.analysis_status,
    confidence: insight?.confidence,
    draftId: insight?.draft_id,
    queueStatus: insight?.queue_status ?? null,
  };
}

function isVisibleAgentItem(item: ListItem) {
  return item.queueStatus !== 'done';
}

function isPendingReplyItem(item: ListItem) {
  return Boolean(item.needsReply && !['sent', 'not_needed'].includes(item.replyStatus ?? ''));
}

function agentCategoryRank(item: ListItem) {
  if (item.importance === 'urgent') return 0;
  if (item.importance === 'important') return 1;
  if (isPendingReplyItem(item)) return 2;
  return 3;
}

function agentSeenRank(item: ListItem) {
  if (item.isSeen === false) return 0;
  if (item.isSeen === true) return 1;
  return 2;
}

function listItemTimestamp(item: ListItem) {
  const parsed = parseMailDate(item.date);
  return parsed ? parsed.getTime() : 0;
}

function sortAgentMailboxItems(items: ListItem[]) {
  return [...items].sort((left, right) => {
    const seenDiff = agentSeenRank(left) - agentSeenRank(right);
    if (seenDiff !== 0) return seenDiff;
    const categoryDiff = agentCategoryRank(left) - agentCategoryRank(right);
    if (categoryDiff !== 0) return categoryDiff;
    return listItemTimestamp(right) - listItemTimestamp(left);
  });
}

function scrollElementTo(element: HTMLElement, top: number, behavior: ScrollBehavior = 'auto') {
  if (typeof element.scrollTo === 'function') {
    element.scrollTo({ top, behavior });
  } else {
    element.scrollTop = top;
  }
}

function fetchFailureToListItem(failure: FetchFailure): ListItem {
  return {
    uid: `uid:${failure.uid}`,
    sender: failure.mailbox,
    subject: `邮件读取失败（UID ${failure.uid}）`,
    date: failure.last_failed_at,
    isSeen: null,
    summary: `已失败 ${failure.failure_count} 次，需要人工查看或稍后重试。`,
    analysisStatus: 'fetch_failed',
    confidence: 0,
  };
}

function searchToListItem(item: SearchMailItem): ListItem {
  return {
    uid: item.uid,
    sender: item.sender ?? '',
    subject: item.subject ?? '',
    date: item.date,
    isSeen: item.is_seen,
    classification: item.classification,
    suggestedAction: item.suggested_action,
    queueStatus: item.queue_status,
  };
}

function searchToTriage(item: SearchMailItem): TriageItem {
  return {
    uid: item.uid,
    sender: item.sender,
    subject: item.subject,
    classification: item.classification ?? '',
    reason: '',
    suggested_action: item.suggested_action ?? '',
    action_reason: '',
    queue_status: item.queue_status ?? 'pending',
    updated_at: item.updated_at,
    is_seen: item.is_seen,
  };
}

function draftEditorForId(draftId: string, editor: DraftEditorState | null) {
  return editor?.draftId === draftId ? editor : null;
}

function isDraftEditorDirty(editor: DraftEditorState | null) {
  return Boolean(editor && (editor.subject !== editor.baselineSubject || editor.body !== editor.baselineBody));
}

export default App;

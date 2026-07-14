import type {
  ActionLog,
  Draft,
  FetchFailure,
  DraftFilter,
  HealthItem,
  InsightFeedback,
  InsightFeedbackResponse,
  MailInsight,
  MailMessage,
  QueueStatus,
  RecognitionCacheResetReport,
  SearchMailItem,
  SecretaryInspectionReport,
  SendDraftResult,
  StartupSummary,
  Translation,
  TriageItem,
  TriageRecentResult,
  UserLabelRule,
} from './types';

type RequestOptions = RequestInit & { signal?: AbortSignal };

let desktopBaseUrl = '';
let desktopToken = '';

export function configureDesktopApi(connection: { base_url: string; token: string } | null) {
  desktopBaseUrl = connection?.base_url?.replace(/\/$/, '') ?? '';
  desktopToken = connection?.token ?? '';
}

function requestUrl(path: string) {
  return desktopBaseUrl ? `${desktopBaseUrl}${path}` : path;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(requestUrl(path), {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(desktopToken ? { Authorization: `Bearer ${desktopToken}` } : {}),
      ...(options.headers ?? {}),
    },
  });
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { detail: text || `HTTP ${response.status}` };
  }
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload && 'detail' in payload ? payload.detail : `HTTP ${response.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return payload as T;
}

function withParams(path: string, values: Record<string, string | number | boolean | null | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export const api = {
  localHealth: (signal?: AbortSignal) => request<HealthItem[]>('/api/health/local', { signal }),
  externalHealth: (target: 'imap' | 'smtp' | 'deepseek') =>
    request<HealthItem>(`/api/health/${target}`, {
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
    }),
  recentMessages: (limit: number, offset: number, signal?: AbortSignal) =>
    request<MailMessage[]>(withParams('/api/messages/recent', { limit, offset }), { signal }),
  messageDetail: (uid: string, signal?: AbortSignal) =>
    request<MailMessage>(`/api/messages/${encodeURIComponent(uid)}`, { signal }),
  searchMessages: (
    filters: {
      keyword?: string;
      is_seen?: boolean | null;
      classification?: string;
      queue_status?: QueueStatus | '';
      limit?: number;
    },
    signal?: AbortSignal,
  ) => request<SearchMailItem[]>(withParams('/api/search/messages', { limit: filters.limit ?? 100, ...filters }), { signal }),
  triageRecent: (limit: number, offset: number) =>
    request<TriageRecentResult>('/api/triage/recent', {
      method: 'POST',
      body: JSON.stringify({ confirmed: true, limit, offset, unread_only: true, skip_triaged: true }),
    }),
  secretaryInspection: (limit = 20) =>
    request<SecretaryInspectionReport>('/api/secretary/inspection', {
      method: 'POST',
      body: JSON.stringify({ confirmed: true, limit }),
    }),
  triageQueue: (statuses: QueueStatus[] = ['pending', 'later'], signal?: AbortSignal) => {
    const params = new URLSearchParams({ limit: '100' });
    statuses.forEach((status) => params.append('statuses', status));
    return request<TriageItem[]>(`/api/triage/queue?${params.toString()}`, { signal });
  },
  setQueueStatus: (uid: string, status: QueueStatus) =>
    request<{ ok: boolean; detail: string }>(`/api/triage/${encodeURIComponent(uid)}/status`, {
      method: 'POST',
      body: JSON.stringify({ status }),
    }),
  translate: (uid: string) =>
    request<Translation>(`/api/messages/${encodeURIComponent(uid)}/translate`, {
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
    }),
  createDraft: (uid: string) =>
    request<Draft>(`/api/messages/${encodeURIComponent(uid)}/draft`, {
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
    }),
  generateSummary: (uid: string, confirmed = false) =>
    request<MailInsight>(`/api/messages/${encodeURIComponent(uid)}/summary`, {
      method: 'POST',
      body: JSON.stringify({ confirmed }),
    }),
  markSeen: (uid: string, signal?: AbortSignal) =>
    request<{ ok: boolean; detail: string }>(`/api/messages/${encodeURIComponent(uid)}/mark-seen`, {
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
      signal,
    }),
  moveToTrash: (uid: string) =>
    request<{ ok: boolean; detail: string }>(`/api/messages/${encodeURIComponent(uid)}/move-to-trash`, {
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
    }),
  drafts: (status: DraftFilter = 'pending', signal?: AbortSignal) =>
    request<Draft[]>(withParams('/api/drafts', { status, limit: 100 }), { signal }),
  updateDraft: (draftId: string, subject: string, body: string) =>
    request<Draft>(`/api/drafts/${encodeURIComponent(draftId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ subject, body }),
    }),
  sendDraft: (draftId: string) =>
    request<SendDraftResult>(`/api/drafts/${encodeURIComponent(draftId)}/send`, {
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
    }),
  actions: (signal?: AbortSignal) => request<ActionLog[]>('/api/actions?limit=50', { signal }),
  insights: (
    filters: {
      importance?: string;
      needs_reply?: boolean;
      reply_pending?: boolean;
      analysis_status?: string;
      min_confidence?: number;
      reply_status?: string;
      notification_status?: string;
      limit?: number;
    } = {},
    signal?: AbortSignal,
  ) => request<MailInsight[]>(withParams('/api/insights', { limit: filters.limit ?? 100, ...filters }), { signal }),
  insight: (uid: string, signal?: AbortSignal) =>
    request<MailInsight>(`/api/insights/${encodeURIComponent(uid)}`, { signal }),
  updateInsightLabels: (uid: string, importance: string, needsReply: boolean, privacyLevel: string) =>
    request<MailInsight>(`/api/insights/${encodeURIComponent(uid)}/labels`, {
      method: 'PATCH',
      body: JSON.stringify({ importance, needs_reply: needsReply, privacy_level: privacyLevel }),
    }),
  submitInsightFeedback: (uid: string, feedback: InsightFeedback, comment = '') =>
    request<InsightFeedbackResponse>(`/api/insights/${encodeURIComponent(uid)}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ feedback, comment }),
    }),
  labelRules: (signal?: AbortSignal) => request<UserLabelRule[]>('/api/rules/label', { signal }),
  createLabelRule: (rule: {
    uid: string;
    mailbox: string;
    sender_pattern: string;
    subject_keyword: string;
    importance: string;
    needs_reply: boolean;
    privacy_level: string;
    source_subject: string;
    source_sender: string;
  }) =>
    request<UserLabelRule>('/api/rules/label', {
      method: 'POST',
      body: JSON.stringify(rule),
    }),
  deleteLabelRule: (ruleId: number) =>
    request<{ ok: boolean; detail: string }>(`/api/rules/label/${ruleId}`, { method: 'DELETE' }),
  setInsightNotificationStatus: (uid: string, status: string) =>
    request<{ ok: boolean; detail: string }>(`/api/insights/${encodeURIComponent(uid)}/notification-status`, {
      method: 'POST',
      body: JSON.stringify({ status }),
    }),
  latestStartupSummary: (signal?: AbortSignal) =>
    request<StartupSummary>('/api/desktop/startup-summary/latest', { signal }),
  fetchFailures: (signal?: AbortSignal) =>
    request<FetchFailure[]>('/api/desktop/fetch-failures?limit=100', { signal }),
  resetRecognitionCache: () =>
    request<RecognitionCacheResetReport>('/api/desktop/reset-recognition-cache', { method: 'POST' }),
  desktopSync: () => request<StartupSummary>('/api/desktop/sync', { method: 'POST' }),
};

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

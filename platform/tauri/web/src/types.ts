export type QueueStatus = 'pending' | 'later' | 'done' | 'skipped';
export type DraftFilter = 'pending' | 'sent' | 'all';
export type DraftSendStatus = 'pending' | 'sending' | 'sent' | 'failed' | 'unknown';
export type MailImportance = 'general' | 'important' | 'urgent';
export type MailView = 'all' | 'reply' | MailImportance;
export type InsightFeedback = 'correct' | 'wrong';

export type MailMessage = {
  id: string;
  sender: string;
  recipient: string;
  subject: string;
  body: string;
  date: string | null;
  snippet: string;
  html_body: string;
  remote_images: string[];
  inline_images: string[];
  attachments: Array<{ filename: string; content_type: string; size: number | null }>;
  is_seen: boolean | null;
  message_id: string;
  references: string;
};

export type TriageItem = {
  uid: string;
  sender: string | null;
  subject: string | null;
  classification: string;
  reason: string;
  suggested_action: string;
  action_reason: string;
  queue_status: QueueStatus | string;
  updated_at: string | null;
  is_seen?: boolean | null;
};

export type SearchMailItem = {
  uid: string;
  sender: string | null;
  subject: string | null;
  date: string | null;
  is_seen: boolean | null;
  classification: string | null;
  suggested_action: string | null;
  queue_status: QueueStatus | string | null;
  updated_at: string;
};

export type Draft = {
  draft_id: string;
  uid: string;
  to_addr: string;
  subject: string;
  body: string;
  body_preview: string;
  reply_to_message_id: string;
  references: string;
  created_at: string | null;
  sent_at: string | null;
  send_status?: DraftSendStatus;
  send_error?: string | null;
  send_started_at?: string | null;
  send_finished_at?: string | null;
  supersedes_id?: string | null;
  base_draft_id?: string | null;
  draft_version?: number | null;
};

export type Translation = {
  mail_id: string;
  subject_zh: string;
  body_zh: string;
};

export type HealthItem = {
  name: string;
  ok: boolean;
  detail: string;
};

export type ActionLog = {
  id: number;
  uid: string | null;
  action: string;
  detail: string;
  created_at: string;
};

export type TriageRecentResult = {
  processed: TriageItem[];
  skipped_seen: number;
  skipped_triaged: number;
  failures: Array<{
    uid: string;
    subject: string;
    error: string;
  }>;
};

export type InspectionGroupKey = 'reply' | 'review' | 'status' | 'no_action';

export type InspectionPlanItem = {
  uid: string;
  sender: string | null;
  subject: string | null;
  classification: string;
  reason: string;
  suggested_action: string;
  action_reason: string;
  queue_status: QueueStatus | string;
  updated_at: string | null;
};

export type InspectionGroup = {
  key: InspectionGroupKey;
  title: string;
  items: InspectionPlanItem[];
};

export type InspectionFailure = {
  uid: string;
  subject: string | null;
  error: string;
};

export type SecretaryInspectionReport = {
  inspected_at: string;
  scanned_count: number;
  processed_count: number;
  skipped_seen: number;
  skipped_triaged: number;
  failed_count: number;
  current_actionable_count: number;
  groups: InspectionGroup[];
  failures: InspectionFailure[];
};

export type SendDraftResult = {
  draft_id?: string;
  to?: string;
  saved_to_sent?: boolean;
  sent_mailbox?: string | null;
  save_error?: string | null;
  send_status?: DraftSendStatus;
  summary: string;
};

export type MailInsight = {
  mail_key: string;
  uid: string;
  mailbox: string;
  source_uidvalidity: number;
  sender: string | null;
  subject: string | null;
  date: string | null;
  is_seen: boolean | null;
  importance: MailImportance;
  needs_reply: boolean;
  summary_zh: string;
  action_items: string[];
  confidence: number;
  priority_reason: string;
  analysis_status: 'pending' | 'analyzing' | 'analyzed' | 'failed' | string;
  reply_status: 'not_needed' | 'review_required' | 'needs_reply' | 'draft_ready' | 'sent' | string;
  notification_status: 'pending' | 'not_required' | 'event_emitted' | 'notified' | string;
  analysis_error: string | null;
  draft_id: string | null;
  latest_feedback: InsightFeedback | null;
  feedback_comment: string;
  feedback_updated_at: string | null;
  analyzed_at: string | null;
  updated_at: string;
  queue_status?: QueueStatus | string | null;
  ai_audit: MailAiAudit;
};

export type MailAiAuditSection = {
  status: string;
  label: string;
  description: string;
  sent_to_ai: boolean;
};

export type MailAiAudit = {
  privacy_level: 'normal' | 'sensitive' | 'private' | string;
  privacy_label: string;
  privacy_reason: string;
  title_classification: MailAiAuditSection;
  body_summary: MailAiAuditSection;
  reply_draft: MailAiAuditSection;
  body_policy: MailAiAuditSection;
};

export type UserLabelRule = {
  id: number;
  enabled: boolean;
  mailbox: string;
  sender_pattern: string;
  subject_keyword: string;
  importance: MailImportance;
  needs_reply: boolean;
  privacy_level: 'normal' | 'sensitive' | 'private' | string;
  source_uid: string;
  source_subject: string;
  source_sender: string;
  match_count: number;
  last_matched_at: string | null;
  created_at: string;
  updated_at: string;
};

export type InsightFeedbackResponse = {
  id: number;
  mail_key: string;
  uid: string;
  feedback: InsightFeedback;
  comment: string;
  importance_at_feedback: string | null;
  needs_reply_at_feedback: boolean | null;
  created_at: string;
  updated_at: string;
};

export type StartupSummaryItem = {
  uid: string;
  sender: string | null;
  subject: string | null;
  importance: MailImportance | null;
  needs_reply: boolean | null;
  summary_zh: string;
  priority_reason: string;
  confidence: number;
  analysis_status: string;
  analysis_error: string | null;
  reply_status: string;
  notification_status: string;
  draft_id: string | null;
};

export type StartupSummary = {
  id?: number | null;
  trigger: string;
  generated_at?: string | null;
  created_at?: string | null;
  new_count: number;
  processed_count: number;
  important_count: number;
  urgent_count: number;
  reply_count: number;
  draft_ready_count: number;
  general_count: number;
  failed_count: number;
  has_more: boolean;
  items: StartupSummaryItem[];
  failures: Array<{ uid: string; stage: string; error: string }>;
};

export type FetchFailure = {
  mail_key: string;
  mailbox: string;
  uid_validity: number;
  uid: number;
  failure_count: number;
  quarantined: boolean;
  attention_status: string;
  last_failed_at: string;
  resolved_at: string | null;
};

export type RecognitionCacheResetReport = {
  mail_insights: number;
  triage_results: number;
  mail_insight_feedback: number;
  mail_fetch_failures: number;
  desktop_summaries: number;
  mailbox_sync_state: number;
  sync_leases: number;
  total_removed: number;
};

export type DesktopBackendConnection = {
  base_url: string;
  token: string;
};

export type DesktopEvent = {
  event:
    | 'ready'
    | 'startup_summary'
    | 'important_mail'
    | 'attention_required'
    | 'mail_processed'
    | 'sync_summary'
    | 'watcher_status'
    | string;
  payload: Record<string, unknown>;
};

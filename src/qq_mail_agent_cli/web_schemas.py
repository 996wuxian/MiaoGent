from __future__ import annotations

from pydantic import BaseModel, Field

from qq_mail_agent_cli.models import Draft, DraftSendResult, MailMessage, MailTranslation, TriageResult
from qq_mail_agent_cli.services.inspection_service import SecretaryInspectionReport
from qq_mail_agent_cli.storage import (
    ActionLogEntry,
    FetchFailureState,
    MailboxSyncState,
    RecognitionCacheResetReport,
    StoredDraft,
    StoredMailInsight,
    StoredMailInsightFeedback,
    StoredMailSearchResult,
    StoredStartupSummary,
    StoredTriage,
    StoredUserLabelRule,
)


class ConfirmRequest(BaseModel):
    confirmed: bool = False


class RecentMessagesQuery(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class TriageRecentRequest(ConfirmRequest):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    unread_only: bool = True
    skip_triaged: bool = True


class SecretaryInspectionRequest(ConfirmRequest):
    limit: int = Field(default=20, ge=1, le=100)


class QueueStatusRequest(BaseModel):
    status: str


class NotificationStatusRequest(BaseModel):
    status: str


class InsightLabelsRequest(BaseModel):
    importance: str
    needs_reply: bool
    privacy_level: str | None = None


class InsightFeedbackRequest(BaseModel):
    feedback: str
    comment: str = ""


class UserLabelRuleCreateRequest(BaseModel):
    uid: str = ""
    mailbox: str = "INBOX"
    sender_pattern: str = ""
    subject_keyword: str = ""
    importance: str
    needs_reply: bool
    privacy_level: str = "normal"
    source_subject: str = ""
    source_sender: str = ""


class DesktopNotificationStatusRequest(BaseModel):
    mail_key: str = Field(min_length=1)
    status: str


class DraftUpdateRequest(BaseModel):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


class MessageResponse(BaseModel):
    id: str
    sender: str
    recipient: str
    subject: str
    body: str = ""
    date: str | None = None
    snippet: str = ""
    html_body: str = ""
    remote_images: list[str] = []
    inline_images: list[str] = []
    attachments: list[dict[str, object | None]] = []
    is_seen: bool | None = None
    message_id: str = ""
    references: str = ""


class TriageResponse(BaseModel):
    uid: str
    sender: str | None = None
    subject: str | None = None
    classification: str
    reason: str
    suggested_action: str
    action_reason: str
    queue_status: str = "pending"
    updated_at: str | None = None
    importance: str = "general"
    needs_reply: bool = False
    summary_zh: str = ""
    action_items: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    priority_reason: str = ""


class DraftResponse(BaseModel):
    draft_id: str
    uid: str
    to_addr: str
    subject: str
    body: str
    body_preview: str = ""
    reply_to_message_id: str = ""
    references: str = ""
    created_at: str | None = None
    sent_at: str | None = None
    send_status: str = "pending"
    send_error: str | None = None
    send_started_at: str | None = None
    send_finished_at: str | None = None
    base_draft_id: str = ""
    supersedes_id: str | None = None
    draft_version: int = 1
    mail_key: str | None = None
    mailbox: str = "INBOX"
    source_uidvalidity: int = 0


class TranslationResponse(BaseModel):
    mail_id: str
    subject_zh: str
    body_zh: str


class SendDraftResponse(BaseModel):
    draft_id: str
    to: str
    saved_to_sent: bool
    sent_mailbox: str | None = None
    save_error: str | None = None
    summary: str
    send_status: str = "sent"


class ActionLogResponse(BaseModel):
    id: int
    uid: str | None
    action: str
    detail: str
    created_at: str


class HealthItemResponse(BaseModel):
    name: str
    ok: bool
    detail: str


class StatusResponse(BaseModel):
    ok: bool
    detail: str


class TriageRecentResponse(BaseModel):
    processed: list[TriageResponse]
    skipped_seen: int = 0
    skipped_triaged: int = 0


class SearchMailResponse(BaseModel):
    uid: str
    sender: str | None = None
    subject: str | None = None
    date: str | None = None
    is_seen: bool | None = None
    classification: str | None = None
    suggested_action: str | None = None
    queue_status: str | None = None
    updated_at: str


class SecretaryInspectionItemResponse(BaseModel):
    uid: str
    sender: str | None = None
    subject: str | None = None
    classification: str
    reason: str
    suggested_action: str
    action_reason: str
    queue_status: str
    updated_at: str | None = None


class SecretaryInspectionGroupResponse(BaseModel):
    key: str
    title: str
    items: list[SecretaryInspectionItemResponse] = Field(default_factory=list)


class SecretaryInspectionFailureResponse(BaseModel):
    uid: str
    subject: str
    error: str


class SecretaryInspectionResponse(BaseModel):
    inspected_at: str
    scanned_count: int
    processed_count: int
    skipped_seen: int
    skipped_triaged: int
    failed_count: int
    current_actionable_count: int
    groups: list[SecretaryInspectionGroupResponse] = Field(default_factory=list)
    failures: list[SecretaryInspectionFailureResponse] = Field(default_factory=list)


class MailAiAuditSectionResponse(BaseModel):
    status: str
    label: str
    description: str
    sent_to_ai: bool = False


class MailAiAuditResponse(BaseModel):
    privacy_level: str = "normal"
    privacy_label: str = "普通"
    privacy_reason: str = ""
    title_classification: MailAiAuditSectionResponse
    body_summary: MailAiAuditSectionResponse
    reply_draft: MailAiAuditSectionResponse
    body_policy: MailAiAuditSectionResponse


class MailInsightResponse(BaseModel):
    mail_key: str
    uid: str
    mailbox: str
    source_uidvalidity: int
    sender: str | None = None
    subject: str | None = None
    date: str | None = None
    is_seen: bool | None = None
    importance: str
    needs_reply: bool
    summary_zh: str
    action_items: list[str] = Field(default_factory=list)
    confidence: float
    priority_reason: str
    analysis_status: str
    reply_status: str
    notification_status: str
    analysis_error: str | None = None
    draft_id: str | None = None
    latest_feedback: str | None = None
    feedback_comment: str = ""
    feedback_updated_at: str | None = None
    analyzed_at: str | None = None
    updated_at: str
    queue_status: str | None = None
    ai_audit: MailAiAuditResponse


class InsightFeedbackResponse(BaseModel):
    id: int
    mail_key: str
    uid: str
    feedback: str
    comment: str = ""
    importance_at_feedback: str | None = None
    needs_reply_at_feedback: bool | None = None
    created_at: str
    updated_at: str


class UserLabelRuleResponse(BaseModel):
    id: int
    enabled: bool
    mailbox: str
    sender_pattern: str
    subject_keyword: str
    importance: str
    needs_reply: bool
    privacy_level: str
    source_uid: str
    source_subject: str
    source_sender: str
    match_count: int
    last_matched_at: str | None = None
    created_at: str
    updated_at: str


class SyncStateResponse(BaseModel):
    mailbox: str
    uid_validity: int
    last_processed_uid: int
    last_sync_at: str
    updated_at: str


class FetchFailureResponse(BaseModel):
    mail_key: str
    mailbox: str
    uid_validity: int
    uid: int
    failure_count: int
    quarantined: bool
    attention_status: str
    last_failed_at: str
    resolved_at: str | None = None


class StartupSummaryItemResponse(BaseModel):
    uid: str
    sender: str | None = None
    subject: str | None = None
    importance: str | None = None
    needs_reply: bool | None = None
    summary_zh: str = ""
    priority_reason: str = ""
    confidence: float = 0
    analysis_status: str = "analyzed"
    analysis_error: str | None = None
    reply_status: str = "not_needed"
    notification_status: str = "not_required"
    draft_id: str | None = None


class StartupSummaryFailureResponse(BaseModel):
    uid: str
    stage: str
    error: str


class StartupSummaryResponse(BaseModel):
    id: int | None = None
    trigger: str
    generated_at: str | None = None
    created_at: str | None = None
    delivery_status: str | None = None
    emitted_at: str | None = None
    acknowledged_at: str | None = None
    new_count: int
    processed_count: int
    important_count: int
    urgent_count: int
    reply_count: int
    draft_ready_count: int
    general_count: int
    failed_count: int
    has_more: bool
    items: list[StartupSummaryItemResponse] = Field(default_factory=list)
    failures: list[StartupSummaryFailureResponse] = Field(default_factory=list)


class RecognitionCacheResetResponse(BaseModel):
    mail_insights: int
    triage_results: int
    mail_insight_feedback: int
    mail_fetch_failures: int
    desktop_summaries: int
    mailbox_sync_state: int
    sync_leases: int
    total_removed: int


def message_to_response(message: MailMessage, *, include_body: bool) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        sender=message.sender,
        recipient=message.recipient,
        subject=message.subject,
        body=message.body if include_body else "",
        date=message.date,
        snippet=message.snippet,
        html_body=message.html_body if include_body else "",
        remote_images=list(message.remote_images),
        inline_images=list(message.inline_images),
        attachments=[
            {"filename": item.filename, "content_type": item.content_type, "size": item.size}
            for item in message.attachments
        ],
        is_seen=message.is_seen,
        message_id=message.message_id,
        references=message.references,
    )


def triage_to_response(result: StoredTriage | TriageResult, *, message: MailMessage | None = None) -> TriageResponse:
    if isinstance(result, StoredTriage):
        return TriageResponse(
            uid=result.uid,
            sender=result.sender,
            subject=result.subject,
            classification=result.classification,
            reason=result.reason,
            suggested_action=result.suggested_action,
            action_reason=result.action_reason,
            queue_status=result.queue_status,
            updated_at=result.updated_at,
        )
    return TriageResponse(
        uid=result.mail_id,
        sender=message.sender if message else None,
        subject=message.subject if message else None,
        classification=result.classification.value,
        reason=result.reason,
        suggested_action=result.suggested_action.value,
        action_reason=result.action_reason,
        queue_status="pending",
        importance=result.importance.value,
        needs_reply=result.needs_reply,
        summary_zh=result.summary_zh,
        action_items=list(result.action_items),
        confidence=result.confidence,
        priority_reason=result.priority_reason,
    )


def draft_to_response(draft: StoredDraft | Draft) -> DraftResponse:
    if isinstance(draft, StoredDraft):
        return DraftResponse(
            draft_id=draft.draft_id,
            uid=draft.uid,
            to_addr=draft.to_addr,
            subject=draft.subject,
            body=draft.body,
            body_preview=draft.body_preview,
            reply_to_message_id=draft.reply_to_message_id,
            references=draft.references,
            created_at=draft.created_at,
            sent_at=draft.sent_at,
            send_status=draft.send_status,
            send_error=draft.send_error,
            send_started_at=draft.send_started_at,
            send_finished_at=draft.send_finished_at,
            base_draft_id=draft.base_draft_id,
            supersedes_id=draft.supersedes_id,
            draft_version=draft.draft_version,
            mail_key=draft.mail_key,
            mailbox=draft.mailbox,
            source_uidvalidity=draft.source_uidvalidity,
        )
    return DraftResponse(
        draft_id=draft.id,
        uid=draft.mail_id,
        to_addr=draft.to,
        subject=draft.subject,
        body=draft.body,
        body_preview=" ".join(draft.body.split())[:300],
        reply_to_message_id=draft.reply_to_message_id,
        references=draft.references,
        base_draft_id=draft.id,
    )


def translation_to_response(translation: MailTranslation) -> TranslationResponse:
    return TranslationResponse(
        mail_id=translation.mail_id,
        subject_zh=translation.subject_zh,
        body_zh=translation.body_zh,
    )


def send_result_to_response(result: DraftSendResult) -> SendDraftResponse:
    return SendDraftResponse(
        draft_id=result.draft_id,
        to=result.to,
        saved_to_sent=result.saved_to_sent,
        sent_mailbox=result.sent_mailbox,
        save_error=result.save_error,
        summary=result.summary(),
    )


def action_to_response(entry: ActionLogEntry) -> ActionLogResponse:
    return ActionLogResponse(
        id=entry.id,
        uid=entry.uid,
        action=entry.action,
        detail=entry.detail,
        created_at=entry.created_at,
    )


def search_result_to_response(result: StoredMailSearchResult) -> SearchMailResponse:
    return SearchMailResponse(
        uid=result.uid,
        sender=result.sender,
        subject=result.subject,
        date=result.date,
        is_seen=result.is_seen,
        classification=result.classification,
        suggested_action=result.suggested_action,
        queue_status=result.queue_status,
        updated_at=result.updated_at,
    )


def secretary_inspection_to_response(report: SecretaryInspectionReport) -> SecretaryInspectionResponse:
    return SecretaryInspectionResponse(
        inspected_at=report.inspected_at,
        scanned_count=report.scanned_count,
        processed_count=report.processed_count,
        skipped_seen=report.skipped_seen,
        skipped_triaged=report.skipped_triaged,
        failed_count=report.failed_count,
        current_actionable_count=report.current_actionable_count,
        groups=[
            SecretaryInspectionGroupResponse(
                key=group.key,
                title=group.title,
                items=[SecretaryInspectionItemResponse(**vars(item)) for item in group.items],
            )
            for group in report.groups
        ],
        failures=[SecretaryInspectionFailureResponse(**vars(item)) for item in report.failures],
    )


def mail_insight_to_response(
    insight: StoredMailInsight,
    feedback: StoredMailInsightFeedback | None = None,
) -> MailInsightResponse:
    return MailInsightResponse(
        mail_key=insight.mail_key,
        uid=insight.uid,
        mailbox=insight.mailbox,
        source_uidvalidity=insight.source_uidvalidity,
        sender=insight.sender,
        subject=insight.subject,
        date=insight.date,
        is_seen=insight.is_seen,
        importance=insight.importance,
        needs_reply=insight.needs_reply,
        summary_zh=insight.summary_zh,
        action_items=list(insight.action_items),
        confidence=insight.confidence,
        priority_reason=insight.priority_reason,
        analysis_status=insight.analysis_status,
        reply_status=insight.reply_status,
        notification_status=insight.notification_status,
        analysis_error=insight.analysis_error,
        draft_id=insight.draft_id,
        latest_feedback=feedback.feedback if feedback else None,
        feedback_comment=feedback.comment if feedback else "",
        feedback_updated_at=feedback.updated_at if feedback else None,
        analyzed_at=insight.analyzed_at,
        updated_at=insight.updated_at,
        queue_status=insight.queue_status,
        ai_audit=_build_mail_ai_audit(insight),
    )


def _build_mail_ai_audit(insight: StoredMailInsight) -> MailAiAuditResponse:
    privacy_level, privacy_label = _privacy_level_from_error(insight.analysis_error)
    privacy_reason = _privacy_reason(insight.analysis_error)
    summary_generated = _has_generated_summary(insight)
    draft_generated = bool(insight.draft_id) or insight.reply_status in {"draft_ready", "sent"}

    if insight.analysis_status in {"pending", "analyzing"}:
        title_status = "pending"
        title_label = "未完成"
        title_description = "尚未完成初始分类。"
    elif insight.analysis_status == "failed":
        title_status = "failed"
        title_label = "分类失败"
        title_description = "初始分类失败，未确认标题或正文已发送给 AI。"
    else:
        title_status = "local_title_rules"
        title_label = "本地标题规则"
        title_description = "已基于邮件标题完成初始分类，当前实现未把标题发送给 DeepSeek。"

    if summary_generated:
        summary = MailAiAuditSectionResponse(
            status="generated",
            label="已生成",
            description="已生成 Agent 摘要，邮件正文已用于摘要生成。",
            sent_to_ai=True,
        )
    else:
        summary = MailAiAuditSectionResponse(
            status="not_generated",
            label="未生成",
            description="尚未生成 Agent 摘要，正文未因摘要功能发送给 AI。",
            sent_to_ai=False,
        )

    if draft_generated:
        draft = MailAiAuditSectionResponse(
            status="generated",
            label="已生成",
            description="已生成或发送过回复草稿，邮件正文已用于草稿生成。",
            sent_to_ai=True,
        )
    else:
        draft = MailAiAuditSectionResponse(
            status="not_generated",
            label="未生成",
            description="尚未生成回复草稿，正文未因草稿功能发送给 AI。",
            sent_to_ai=False,
        )

    if privacy_level == "normal":
        policy = MailAiAuditSectionResponse(
            status="allowed",
            label="允许按需处理",
            description="当前未命中敏感/隐私标题规则，摘要可按需生成。",
            sent_to_ai=summary.sent_to_ai or draft.sent_to_ai,
        )
    elif summary_generated:
        policy = MailAiAuditSectionResponse(
            status="confirmed_once",
            label="已确认过摘要",
            description="该邮件被标记为敏感/隐私；摘要已在确认后生成，后续正文 AI 操作仍需谨慎。",
            sent_to_ai=True,
        )
    else:
        policy = MailAiAuditSectionResponse(
            status="confirmation_required",
            label="需要二次确认",
            description="该邮件被标记为敏感/隐私；生成摘要会发送正文，必须二次确认。翻译和草稿默认阻止。",
            sent_to_ai=False,
        )

    return MailAiAuditResponse(
        privacy_level=privacy_level,
        privacy_label=privacy_label,
        privacy_reason=privacy_reason,
        title_classification=MailAiAuditSectionResponse(
            status=title_status,
            label=title_label,
            description=title_description,
            sent_to_ai=False,
        ),
        body_summary=summary,
        reply_draft=draft,
        body_policy=policy,
    )


def _privacy_level_from_error(error: str | None) -> tuple[str, str]:
    if error == "privacy_private":
        return "private", "隐私"
    if error == "privacy_sensitive":
        return "sensitive", "敏感"
    if error == "privacy_normal":
        return "normal", "普通"
    return "normal", "普通"


def _privacy_reason(error: str | None) -> str:
    if error == "privacy_private":
        return "命中身份、财务、地址或联系方式等隐私规则。"
    if error == "privacy_sensitive":
        return "命中录用、入职、薪资、合同或附件等敏感规则。"
    if error == "privacy_normal":
        return "已人工标记为普通邮件。"
    return "未命中当前本地敏感/隐私标题规则。"


def _has_generated_summary(insight: StoredMailInsight) -> bool:
    summary = (insight.summary_zh or "").strip()
    if not summary:
        return False
    if "已按隐私保护模式阻止发送给 DeepSeek" in summary:
        return False
    return insight.analysis_status == "analyzed"


def insight_feedback_to_response(feedback: StoredMailInsightFeedback) -> InsightFeedbackResponse:
    return InsightFeedbackResponse(
        id=feedback.id,
        mail_key=feedback.mail_key,
        uid=feedback.uid,
        feedback=feedback.feedback,
        comment=feedback.comment,
        importance_at_feedback=feedback.importance_at_feedback,
        needs_reply_at_feedback=feedback.needs_reply_at_feedback,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


def user_label_rule_to_response(rule: StoredUserLabelRule) -> UserLabelRuleResponse:
    return UserLabelRuleResponse(**vars(rule))


def sync_state_to_response(state: MailboxSyncState) -> SyncStateResponse:
    return SyncStateResponse(**vars(state))


def fetch_failure_to_response(failure: FetchFailureState) -> FetchFailureResponse:
    return FetchFailureResponse(**vars(failure))


def startup_summary_to_response(summary: StoredStartupSummary) -> StartupSummaryResponse:
    return StartupSummaryResponse(
        id=summary.id,
        created_at=summary.created_at,
        delivery_status=summary.delivery_status,
        emitted_at=summary.emitted_at,
        acknowledged_at=summary.acknowledged_at,
        **summary.payload,
    )


def recognition_cache_reset_to_response(report: RecognitionCacheResetReport) -> RecognitionCacheResetResponse:
    return RecognitionCacheResetResponse(
        mail_insights=report.mail_insights,
        triage_results=report.triage_results,
        mail_insight_feedback=report.mail_insight_feedback,
        mail_fetch_failures=report.mail_fetch_failures,
        desktop_summaries=report.desktop_summaries,
        mailbox_sync_state=report.mailbox_sync_state,
        sync_leases=report.sync_leases,
        total_removed=report.total_removed,
    )

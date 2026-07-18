from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from collections.abc import Iterator
import time
import re
from uuid import uuid4

from qq_mail_agent_cli.models import (
    Draft,
    MailClassification,
    MailImportance,
    MailMessage,
    MailSummary,
    SuggestedAction,
    TriageResult,
)


@dataclass(frozen=True)
class StoredTriage:
    uid: str
    sender: str | None
    subject: str | None
    classification: str
    reason: str
    suggested_action: str
    action_reason: str
    queue_status: str
    updated_at: str


@dataclass(frozen=True)
class ActionLogEntry:
    id: int
    uid: str | None
    action: str
    detail: str
    created_at: str


@dataclass(frozen=True)
class StoredDraft:
    draft_id: str
    uid: str
    to_addr: str
    subject: str
    body: str
    body_preview: str
    reply_to_message_id: str
    references: str
    created_at: str
    sent_at: str | None
    send_status: str = "pending"
    send_error: str | None = None
    send_attempt_id: str | None = None
    send_started_at: str | None = None
    send_finished_at: str | None = None
    base_draft_id: str = ""
    supersedes_id: str | None = None
    draft_version: int = 1
    mail_key: str | None = None
    mailbox: str = "INBOX"
    source_uidvalidity: int = 0


@dataclass(frozen=True)
class StoredMailSearchResult:
    uid: str
    sender: str | None
    subject: str | None
    date: str | None
    is_seen: bool | None
    classification: str | None
    suggested_action: str | None
    queue_status: str | None
    updated_at: str


@dataclass(frozen=True)
class StoredMailInsight:
    mail_key: str
    uid: str
    mailbox: str
    source_uidvalidity: int
    sender: str | None
    subject: str | None
    date: str | None
    is_seen: bool | None
    importance: str
    needs_reply: bool
    summary_zh: str
    action_items: tuple[str, ...]
    confidence: float
    priority_reason: str
    analysis_status: str
    reply_status: str
    notification_status: str
    analysis_error: str | None
    draft_id: str | None
    analyzed_at: str | None
    updated_at: str
    queue_status: str | None = None


@dataclass(frozen=True)
class StoredMailInsightFeedback:
    id: int
    mail_key: str
    uid: str
    feedback: str
    comment: str
    importance_at_feedback: str | None
    needs_reply_at_feedback: bool | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MailboxSyncState:
    mailbox: str
    uid_validity: int
    last_processed_uid: int
    last_sync_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredStartupSummary:
    id: int
    payload: dict[str, object]
    created_at: str
    delivery_status: str = "pending"
    emitted_at: str | None = None
    acknowledged_at: str | None = None


@dataclass(frozen=True)
class FetchFailureState:
    mail_key: str
    mailbox: str
    uid_validity: int
    uid: int
    failure_count: int
    quarantined: bool
    attention_status: str
    last_failed_at: str
    resolved_at: str | None


@dataclass(frozen=True)
class RecognitionCacheResetReport:
    mail_insights: int
    triage_results: int
    mail_insight_feedback: int
    mail_fetch_failures: int
    desktop_summaries: int
    mailbox_sync_state: int
    sync_leases: int

    @property
    def total_removed(self) -> int:
        return (
            self.mail_insights
            + self.triage_results
            + self.mail_insight_feedback
            + self.mail_fetch_failures
            + self.desktop_summaries
            + self.mailbox_sync_state
            + self.sync_leases
        )


@dataclass(frozen=True)
class StoredUserLabelRule:
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
    last_matched_at: str | None
    created_at: str
    updated_at: str


class StateStore:
    _SCHEMA_VERSION = 8

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._backup_before_migration()
        self._init_db()

    def upsert_mail(
        self,
        message: MailMessage,
        *,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mail_items(uid, sender, recipient, subject, date, is_seen, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    sender=excluded.sender,
                    recipient=excluded.recipient,
                    subject=excluded.subject,
                    date=excluded.date,
                    is_seen=excluded.is_seen,
                    updated_at=excluded.updated_at
                """,
                (
                    message.id,
                    message.sender,
                    message.recipient,
                    message.subject,
                    message.date,
                    _bool_to_int(message.is_seen),
                    now,
                    now,
                ),
            )
            if uid_validity is not None:
                mail_key = _mail_key(mailbox, uid_validity, message.id)
                conn.execute(
                    """
                INSERT INTO mail_generation_items(
                        mail_key, uid, mailbox, source_uidvalidity, sender,
                        recipient, subject, date, is_seen, message_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(mail_key) DO UPDATE SET
                        sender=excluded.sender,
                        recipient=excluded.recipient,
                        subject=excluded.subject,
                        date=excluded.date,
                        is_seen=excluded.is_seen,
                        message_id=excluded.message_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        mail_key,
                        message.id,
                        mailbox,
                        uid_validity,
                        message.sender,
                        message.recipient,
                        message.subject,
                        message.date,
                        _bool_to_int(message.is_seen),
                        message.message_id or "",
                        now,
                        now,
                    ),
                )

    def mark_mail_seen(self, uid: str) -> bool:
        uid_values = _uid_lookup_values(uid)
        placeholders = ", ".join("?" for _ in uid_values)
        now = _now()
        with self._connect() as conn:
            mail_items = conn.execute(
                f"""
                UPDATE mail_items
                SET is_seen = 1, updated_at = ?
                WHERE uid IN ({placeholders})
                """,
                (now, *uid_values),
            ).rowcount
            generation_items = conn.execute(
                f"""
                UPDATE mail_generation_items
                SET is_seen = 1, updated_at = ?
                WHERE uid IN ({placeholders})
                """,
                (now, *uid_values),
            ).rowcount
        return (mail_items + generation_items) > 0

    def save_triage(
        self,
        message: MailMessage,
        result: TriageResult,
        *,
        model: str,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
        analysis_error: str | None = None,
    ) -> None:
        now = _now()
        importance, needs_reply = _effective_insight(result)
        source_uidvalidity = uid_validity or 0
        mail_key = _mail_key(mailbox, source_uidvalidity, message.id)
        label_source = "user" if model in {"user-label-manual", "user-label-rule"} else "ai"
        self.upsert_mail(
            message,
            uid_validity=source_uidvalidity,
            mailbox=mailbox,
        )
        with self._connect() as conn:
            if label_source != "user" and _has_matching_user_label_decision(conn, message, mailbox):
                _copy_matching_user_label_decision(conn, message, mailbox=mailbox, uid_validity=source_uidvalidity, now=now)
                return
            conn.execute(
                """
                INSERT INTO triage_results(
                    uid,
                    classification,
                    reason,
                    suggested_action,
                    action_reason,
                    mailbox,
                    source_uidvalidity,
                    model,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    classification=excluded.classification,
                    reason=excluded.reason,
                    suggested_action=excluded.suggested_action,
                    action_reason=excluded.action_reason,
                    queue_status=CASE
                        WHEN COALESCE(triage_results.source_uidvalidity, 0) != excluded.source_uidvalidity
                          OR COALESCE(triage_results.mailbox, 'INBOX') != excluded.mailbox
                        THEN 'pending'
                        ELSE triage_results.queue_status
                    END,
                    queue_status_updated_at=CASE
                        WHEN COALESCE(triage_results.source_uidvalidity, 0) != excluded.source_uidvalidity
                          OR COALESCE(triage_results.mailbox, 'INBOX') != excluded.mailbox
                        THEN NULL
                        ELSE triage_results.queue_status_updated_at
                    END,
                    mailbox=excluded.mailbox,
                    source_uidvalidity=excluded.source_uidvalidity,
                    model=excluded.model,
                    updated_at=excluded.updated_at
                """,
                (
                    message.id,
                    result.classification.value,
                    result.reason,
                    result.suggested_action.value,
                    result.action_reason,
                    mailbox,
                    source_uidvalidity,
                    model,
                    now,
                    now,
                ),
            )
            previous = conn.execute(
                """
                SELECT reply_status, notification_status, draft_id
                FROM mail_insights
                WHERE mail_key = ?
                """,
                (mail_key,),
            ).fetchone()
            previous_reply = previous[0] if previous else None
            previous_notification = previous[1] if previous else None
            previous_draft_id = previous[2] if previous else None
            if not needs_reply:
                reply_status = "not_needed"
            elif previous_reply in {"draft_ready", "sent"}:
                reply_status = previous_reply
            else:
                reply_status = "needs_reply"
            if importance == MailImportance.GENERAL:
                notification_status = "not_required"
            elif previous_notification in {"event_emitted", "notified"}:
                notification_status = previous_notification
            else:
                notification_status = "pending"
            conn.execute(
                """
                INSERT INTO mail_insights(
                    mail_key,
                    uid,
                    mailbox,
                    source_uidvalidity,
                    importance,
                    needs_reply,
                    summary_zh,
                    action_items_json,
                    confidence,
                    priority_reason,
                    analysis_status,
                    reply_status,
                    notification_status,
                    analysis_error,
                    label_source,
                    draft_id,
                    analyzed_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'analyzed', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mail_key) DO UPDATE SET
                    importance=excluded.importance,
                    needs_reply=excluded.needs_reply,
                    summary_zh=excluded.summary_zh,
                    action_items_json=excluded.action_items_json,
                    confidence=excluded.confidence,
                    priority_reason=excluded.priority_reason,
                    analysis_status='analyzed',
                    reply_status=excluded.reply_status,
                    notification_status=excluded.notification_status,
                    analysis_error=excluded.analysis_error,
                    label_source=excluded.label_source,
                    draft_id=COALESCE(mail_insights.draft_id, excluded.draft_id),
                    analyzed_at=excluded.analyzed_at,
                    updated_at=excluded.updated_at
                """,
                (
                    mail_key,
                    message.id,
                    mailbox,
                    source_uidvalidity,
                    importance.value,
                    _bool_to_int(needs_reply),
                    result.summary_zh or result.reason,
                    json.dumps(list(result.action_items), ensure_ascii=False),
                    _clamp_confidence(result.confidence),
                    result.priority_reason or result.reason,
                    reply_status,
                    notification_status,
                    analysis_error,
                    label_source,
                    previous_draft_id,
                    now,
                    now,
                    now,
                ),
            )

    def record_analysis_started(
        self,
        message: MailMessage,
        *,
        uid_validity: int,
        mailbox: str = "INBOX",
    ) -> None:
        self.upsert_mail(message, uid_validity=uid_validity, mailbox=mailbox)
        now = _now()
        mail_key = _mail_key(mailbox, uid_validity, message.id)
        with self._connect() as conn:
            if _has_matching_user_label_decision(conn, message, mailbox):
                _copy_matching_user_label_decision(conn, message, mailbox=mailbox, uid_validity=uid_validity, now=now)
                return
            conn.execute(
                """
                INSERT INTO mail_insights(
                    mail_key, uid, mailbox, source_uidvalidity, importance,
                    needs_reply, summary_zh, action_items_json, confidence,
                    priority_reason, analysis_status, reply_status,
                    notification_status, analysis_error, draft_id, analyzed_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'general', 0, '', '[]', 0, '',
                        'analyzing', 'review_required', 'pending', NULL, NULL, NULL, ?, ?)
                ON CONFLICT(mail_key) DO UPDATE SET
                    analysis_status='analyzing',
                    analysis_error=NULL,
                    updated_at=excluded.updated_at
                """,
                (mail_key, message.id, mailbox, uid_validity, now, now),
            )

    def save_title_classification(
        self,
        message: MailMessage,
        result: TriageResult,
        *,
        model: str,
        uid_validity: int,
        mailbox: str = "INBOX",
        analysis_error: str | None = None,
        write_triage: bool = True,
    ) -> None:
        self.upsert_mail(message, uid_validity=uid_validity, mailbox=mailbox)
        now = _now()
        mail_key = _mail_key(mailbox, uid_validity, message.id)
        importance, needs_reply = _effective_insight(result)
        with self._connect() as conn:
            if (
                write_triage
                and model not in {"user-label-manual", "user-label-rule"}
                and _has_matching_user_label_decision(conn, message, mailbox)
            ):
                _copy_matching_user_label_decision(conn, message, mailbox=mailbox, uid_validity=uid_validity, now=now)
                return
            if write_triage:
                conn.execute(
                    """
                    INSERT INTO triage_results(
                        uid,
                        classification,
                        reason,
                        suggested_action,
                        action_reason,
                        mailbox,
                        source_uidvalidity,
                        model,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uid) DO UPDATE SET
                        classification=excluded.classification,
                        reason=excluded.reason,
                        suggested_action=excluded.suggested_action,
                        action_reason=excluded.action_reason,
                        mailbox=excluded.mailbox,
                        source_uidvalidity=excluded.source_uidvalidity,
                        model=excluded.model,
                        updated_at=excluded.updated_at
                    """,
                    (
                        message.id,
                        result.classification.value,
                        result.reason,
                        result.suggested_action.value,
                        result.action_reason,
                        mailbox,
                        uid_validity,
                        model,
                        now,
                        now,
                    ),
                )
            previous = conn.execute(
                """
                SELECT reply_status, notification_status, draft_id
                FROM mail_insights
                WHERE mail_key = ?
                """,
                (mail_key,),
            ).fetchone()
            previous_reply = previous[0] if previous else None
            previous_notification = previous[1] if previous else None
            previous_draft_id = previous[2] if previous else None
            if not needs_reply:
                reply_status = "not_needed"
            elif previous_reply in {"draft_ready", "sent"}:
                reply_status = previous_reply
            else:
                reply_status = "needs_reply"
            if importance == MailImportance.GENERAL:
                notification_status = "not_required"
            elif previous_notification in {"event_emitted", "notified"}:
                notification_status = previous_notification
            else:
                notification_status = "pending"
            conn.execute(
                """
                INSERT INTO mail_insights(
                    mail_key,
                    uid,
                    mailbox,
                    source_uidvalidity,
                    importance,
                    needs_reply,
                    summary_zh,
                    action_items_json,
                    confidence,
                    priority_reason,
                    analysis_status,
                    reply_status,
                    notification_status,
                    analysis_error,
                    draft_id,
                    analyzed_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, '', '[]', ?, ?, 'title_classified', ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(mail_key) DO UPDATE SET
                    importance=excluded.importance,
                    needs_reply=excluded.needs_reply,
                    summary_zh=mail_insights.summary_zh,
                    action_items_json=mail_insights.action_items_json,
                    confidence=CASE
                        WHEN mail_insights.summary_zh != '' THEN mail_insights.confidence
                        ELSE excluded.confidence
                    END,
                    priority_reason=excluded.priority_reason,
                    analysis_status=CASE
                        WHEN mail_insights.summary_zh != '' AND mail_insights.analysis_status = 'analyzed'
                        THEN mail_insights.analysis_status
                        ELSE 'title_classified'
                    END,
                    reply_status=excluded.reply_status,
                    notification_status=excluded.notification_status,
                    analysis_error=excluded.analysis_error,
                    draft_id=COALESCE(mail_insights.draft_id, excluded.draft_id),
                    updated_at=excluded.updated_at
                """,
                (
                    mail_key,
                    message.id,
                    mailbox,
                    uid_validity,
                    importance.value,
                    _bool_to_int(needs_reply),
                    _clamp_confidence(result.confidence),
                    result.priority_reason or result.reason,
                    reply_status,
                    notification_status,
                    analysis_error,
                    previous_draft_id,
                    now,
                    now,
                ),
            )

    def record_generated_summary(
        self,
        message: MailMessage,
        summary: MailSummary,
        *,
        uid_validity: int = 0,
        mailbox: str = "INBOX",
    ) -> StoredMailInsight:
        self.upsert_mail(message, uid_validity=uid_validity, mailbox=mailbox)
        now = _now()
        mail_key = _mail_key(mailbox, uid_validity, message.id)
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT importance, needs_reply, reply_status, notification_status, analysis_error, draft_id
                FROM mail_insights
                WHERE mail_key = ?
                """,
                (mail_key,),
            ).fetchone()
            importance = str(existing[0]) if existing else MailImportance.GENERAL.value
            needs_reply = int(existing[1]) if existing else 0
            reply_status = str(existing[2]) if existing else "not_needed"
            notification_status = str(existing[3]) if existing else "not_required"
            analysis_error = existing[4] if existing and isinstance(existing[4], str) else None
            draft_id = existing[5] if existing and isinstance(existing[5], str) else None
            conn.execute(
                """
                INSERT INTO mail_insights(
                    mail_key,
                    uid,
                    mailbox,
                    source_uidvalidity,
                    importance,
                    needs_reply,
                    summary_zh,
                    action_items_json,
                    confidence,
                    priority_reason,
                    analysis_status,
                    reply_status,
                    notification_status,
                    analysis_error,
                    draft_id,
                    analyzed_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'analyzed', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mail_key) DO UPDATE SET
                    summary_zh=excluded.summary_zh,
                    action_items_json=excluded.action_items_json,
                    confidence=excluded.confidence,
                    priority_reason=excluded.priority_reason,
                    analysis_status='analyzed',
                    analyzed_at=excluded.analyzed_at,
                    updated_at=excluded.updated_at
                """,
                (
                    mail_key,
                    message.id,
                    mailbox,
                    uid_validity,
                    importance,
                    needs_reply,
                    summary.summary_zh,
                    json.dumps(list(summary.action_items), ensure_ascii=False),
                    _clamp_confidence(summary.confidence),
                    summary.reason,
                    reply_status,
                    notification_status,
                    analysis_error,
                    draft_id,
                    now,
                    now,
                    now,
                ),
            )
        insight = self.get_mail_insight(message.id, uid_validity=uid_validity, mailbox=mailbox)
        assert insight is not None
        return insight

    def record_analysis_failure(
        self,
        message: MailMessage,
        *,
        uid_validity: int,
        error: Exception,
        mailbox: str = "INBOX",
    ) -> None:
        self.upsert_mail(message, uid_validity=uid_validity, mailbox=mailbox)
        now = _now()
        mail_key = _mail_key(mailbox, uid_validity, message.id)
        safe_error = f"{error.__class__.__name__}: 本封邮件分析失败，请稍后重试"
        with self._connect() as conn:
            if _has_matching_user_label_decision(conn, message, mailbox):
                _copy_matching_user_label_decision(conn, message, mailbox=mailbox, uid_validity=uid_validity, now=now)
                return
            conn.execute(
                """
                INSERT INTO mail_insights(
                    mail_key, uid, mailbox, source_uidvalidity, importance,
                    needs_reply, summary_zh, action_items_json, confidence,
                    priority_reason, analysis_status, reply_status,
                    notification_status, analysis_error, draft_id, analyzed_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'general', 0, '邮件分析失败，需要人工查看', '[]', 0,
                        '重要性判断失败，未自动归为一般邮件', 'failed', 'review_required',
                        'attention_pending', ?, NULL, NULL, ?, ?)
                ON CONFLICT(mail_key) DO UPDATE SET
                    analysis_status='failed',
                    reply_status='review_required',
                    notification_status=CASE
                        WHEN mail_insights.notification_status IN (
                            'event_emitted', 'notified', 'attention_emitted'
                        )
                        THEN mail_insights.notification_status
                        ELSE 'attention_pending'
                    END,
                    analysis_error=excluded.analysis_error,
                    summary_zh=excluded.summary_zh,
                    priority_reason=excluded.priority_reason,
                    confidence=0,
                    updated_at=excluded.updated_at
                """,
                (mail_key, message.id, mailbox, uid_validity, safe_error, now, now),
            )

    def record_analysis_review_required(
        self,
        message: MailMessage,
        *,
        uid_validity: int,
        summary_zh: str,
        reason: str,
        error_code: str,
        mailbox: str = "INBOX",
    ) -> None:
        self.upsert_mail(message, uid_validity=uid_validity, mailbox=mailbox)
        now = _now()
        mail_key = _mail_key(mailbox, uid_validity, message.id)
        with self._connect() as conn:
            if _has_matching_user_label_decision(conn, message, mailbox):
                _copy_matching_user_label_decision(conn, message, mailbox=mailbox, uid_validity=uid_validity, now=now)
                return
            conn.execute(
                """
                INSERT INTO mail_insights(
                    mail_key, uid, mailbox, source_uidvalidity, importance,
                    needs_reply, summary_zh, action_items_json, confidence,
                    priority_reason, analysis_status, reply_status,
                    notification_status, analysis_error, draft_id, analyzed_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'general', 0, ?, '[]', 0, ?,
                        'review_required', 'review_required', 'attention_pending',
                        ?, NULL, NULL, ?, ?)
                ON CONFLICT(mail_key) DO UPDATE SET
                    summary_zh=excluded.summary_zh,
                    priority_reason=excluded.priority_reason,
                    analysis_status='review_required',
                    reply_status='review_required',
                    notification_status=CASE
                        WHEN mail_insights.notification_status = 'attention_emitted'
                        THEN 'attention_emitted'
                        ELSE 'attention_pending'
                    END,
                    analysis_error=excluded.analysis_error,
                    confidence=0,
                    updated_at=excluded.updated_at
                """,
                (
                    mail_key,
                    message.id,
                    mailbox,
                    uid_validity,
                    summary_zh,
                    reason,
                    error_code,
                    now,
                    now,
                ),
            )

    def get_mail_insight(
        self,
        uid: str,
        *,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> StoredMailInsight | None:
        where = "i.uid = ? AND i.mailbox = ?"
        params: list[object] = [uid, mailbox]
        if uid_validity is not None:
            where += " AND i.source_uidvalidity = ?"
            params.append(uid_validity)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                {self._insight_select_sql()}
                WHERE {where}
                ORDER BY
                    CASE WHEN i.source_uidvalidity = s.uid_validity THEN 0 ELSE 1 END,
                    i.updated_at DESC,
                    i.rowid DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return _stored_insight(row) if row else None

    def list_mail_insights(
        self,
        limit: int = 100,
        *,
        importance: str | None = None,
        needs_reply: bool | None = None,
        reply_pending: bool | None = None,
        analysis_status: str | None = None,
        min_confidence: float | None = None,
        reply_status: str | None = None,
        notification_status: str | None = None,
        include_stale: bool = False,
    ) -> list[StoredMailInsight]:
        where: list[str] = []
        params: list[object] = []
        if not include_stale:
            where.append("(s.uid_validity IS NULL OR i.source_uidvalidity = s.uid_validity)")
        if importance is not None:
            _validate_importance(importance)
            where.append("i.importance = ?")
            params.append(importance)
        if needs_reply is not None:
            where.append("i.needs_reply = ?")
            params.append(_bool_to_int(needs_reply))
        if reply_pending is not None:
            if reply_pending:
                where.append(
                    "(i.needs_reply = 1 AND i.reply_status IN "
                    "('needs_reply', 'draft_ready', 'review_required'))"
                )
            else:
                where.append(
                    "(i.needs_reply = 0 OR i.reply_status IN ('not_needed', 'sent'))"
                )
        if analysis_status is not None:
            _validate_analysis_status(analysis_status)
            where.append("i.analysis_status = ?")
            params.append(analysis_status)
        if min_confidence is not None:
            if not 0 <= min_confidence <= 1:
                raise ValueError("min_confidence must be between 0 and 1")
            where.append("i.confidence >= ?")
            params.append(min_confidence)
        if reply_status is not None:
            _validate_reply_status(reply_status)
            where.append("i.reply_status = ?")
            params.append(reply_status)
        if notification_status is not None:
            _validate_notification_status(notification_status)
            where.append("i.notification_status = ?")
            params.append(notification_status)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                {self._insight_select_sql()}
                {where_sql}
                ORDER BY i.updated_at DESC, i.rowid DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_stored_insight(row) for row in rows]

    def list_retryable_mail_insights(
        self,
        *,
        uid_validity: int,
        mailbox: str = "INBOX",
        limit: int = 20,
    ) -> list[StoredMailInsight]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                {self._insight_select_sql()}
                WHERE i.source_uidvalidity = ? AND i.mailbox = ? AND (
                    i.analysis_status = 'failed'
                    OR (
                        i.analysis_status = 'analyzed'
                        AND i.needs_reply = 1
                        AND i.reply_status IN ('needs_reply', 'review_required')
                    )
                )
                ORDER BY i.updated_at ASC, i.rowid ASC
                LIMIT ?
                """,
                (uid_validity, mailbox, limit),
            ).fetchall()
        return [_stored_insight(row) for row in rows]

    def list_notification_outbox(
        self,
        *,
        uid_validity: int,
        mailbox: str = "INBOX",
        include_emitted: bool = False,
        limit: int = 100,
    ) -> list[StoredMailInsight]:
        statuses = ("pending", "failed", "event_emitted") if include_emitted else ("pending", "failed")
        placeholders = ", ".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                {self._insight_select_sql()}
                WHERE i.source_uidvalidity = ?
                  AND i.mailbox = ?
                  AND i.analysis_status IN ('analyzed', 'title_classified')
                  AND i.confidence >= 0.55
                  AND i.importance IN ('important', 'urgent')
                  AND i.notification_status IN ({placeholders})
                  AND COALESCE(g.is_seen, 0) != 1
                  AND COALESCE(m.is_seen, 0) != 1
                ORDER BY i.updated_at ASC, i.rowid ASC
                LIMIT ?
                """,
                (uid_validity, mailbox, *statuses, limit),
            ).fetchall()
        return [_stored_insight(row) for row in rows]

    def list_attention_outbox(
        self,
        *,
        uid_validity: int,
        mailbox: str = "INBOX",
        limit: int = 100,
    ) -> list[StoredMailInsight]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                {self._insight_select_sql()}
                WHERE i.source_uidvalidity = ?
                  AND i.mailbox = ?
                  AND i.notification_status IN ('attention_pending', 'attention_failed')
                ORDER BY i.updated_at ASC, i.rowid ASC
                LIMIT ?
                """,
                (uid_validity, mailbox, limit),
            ).fetchall()
        return [_stored_insight(row) for row in rows]

    @staticmethod
    def _insight_select_sql() -> str:
        return """
                SELECT
                    i.mail_key,
                    i.uid,
                    i.mailbox,
                    i.source_uidvalidity,
                    g.sender,
                    g.subject,
                    g.date,
                    CASE
                        WHEN COALESCE(g.is_seen, 0) = 1 OR COALESCE(m.is_seen, 0) = 1 THEN 1
                        WHEN g.is_seen = 0 OR m.is_seen = 0 THEN 0
                        ELSE NULL
                    END,
                    i.importance,
                    i.needs_reply,
                    i.summary_zh,
                    i.action_items_json,
                    i.confidence,
                    i.priority_reason,
                    i.analysis_status,
                    i.reply_status,
                    i.notification_status,
                    i.analysis_error,
                    i.draft_id,
                    i.analyzed_at,
                    i.updated_at,
                    t.queue_status
                FROM mail_insights i
                LEFT JOIN mail_generation_items g ON g.mail_key = i.mail_key
                LEFT JOIN mail_items m ON m.uid = i.uid
                LEFT JOIN triage_results t ON t.uid = i.uid
                LEFT JOIN mailbox_sync_state s ON s.mailbox = i.mailbox
        """

    def set_reply_status(
        self,
        uid: str,
        status: str,
        *,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
        draft_id: str | None = None,
    ) -> bool:
        _validate_reply_status(status)
        mail_key = self._latest_mail_key(uid, uid_validity=uid_validity, mailbox=mailbox)
        if mail_key is None:
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE mail_insights
                SET reply_status = ?, draft_id = COALESCE(?, draft_id), updated_at = ?
                WHERE mail_key = ?
                """,
                (status, draft_id, _now(), mail_key),
            )
            return cursor.rowcount > 0

    def update_mail_insight_labels(
        self,
        uid: str,
        *,
        importance: str,
        needs_reply: bool,
        privacy_level: str | None = None,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> StoredMailInsight | None:
        _validate_importance(importance)
        analysis_error = _analysis_error_from_privacy_level(privacy_level)
        update_privacy = privacy_level is not None
        mail_key = self._latest_mail_key(uid, uid_validity=uid_validity, mailbox=mailbox)
        if mail_key is None:
            return None
        now = _now()
        classification = _classification_from_labels(importance=MailImportance(importance), needs_reply=needs_reply)
        suggested_action = _suggested_action_for_classification(classification)
        queue_status = "pending" if classification != MailClassification.IGNORE else "done"
        manual_reason = _manual_label_reason(
            importance=importance,
            needs_reply=needs_reply,
            privacy_level=privacy_level,
        )
        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT reply_status, notification_status, mailbox, source_uidvalidity
                FROM mail_insights
                WHERE mail_key = ?
                """,
                (mail_key,),
            ).fetchone()
            if current is None:
                return None
            reply_status = str(current[0])
            notification_status = str(current[1])
            current_mailbox = str(current[2] or mailbox)
            current_uidvalidity = int(current[3] or 0)
            if needs_reply and reply_status == "not_needed":
                reply_status = "needs_reply"
            elif not needs_reply and reply_status != "sent":
                reply_status = "not_needed"
            if importance == MailImportance.GENERAL.value and notification_status in {"pending", "failed"}:
                notification_status = "not_required"
            elif importance in {MailImportance.IMPORTANT.value, MailImportance.URGENT.value} and notification_status == "not_required":
                notification_status = "pending"
            conn.execute(
                """
                UPDATE mail_insights
                SET importance = ?,
                    needs_reply = ?,
                    confidence = MAX(confidence, 0.95),
                    priority_reason = ?,
                    reply_status = ?,
                    notification_status = ?,
                    analysis_error = CASE WHEN ? THEN ? ELSE analysis_error END,
                    label_source = 'user',
                    updated_at = ?
                WHERE mail_key = ?
                """,
                (
                    importance,
                    _bool_to_int(needs_reply),
                    manual_reason,
                    reply_status,
                    notification_status,
                    _bool_to_int(update_privacy),
                    analysis_error,
                    now,
                    mail_key,
                ),
            )
            conn.execute(
                """
                INSERT INTO triage_results(
                    uid,
                    classification,
                    reason,
                    suggested_action,
                    action_reason,
                    queue_status,
                    queue_status_updated_at,
                    mailbox,
                    source_uidvalidity,
                    model,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    classification=excluded.classification,
                    reason=excluded.reason,
                    suggested_action=excluded.suggested_action,
                    action_reason=excluded.action_reason,
                    queue_status=excluded.queue_status,
                    queue_status_updated_at=excluded.queue_status_updated_at,
                    mailbox=excluded.mailbox,
                    source_uidvalidity=excluded.source_uidvalidity,
                    model=excluded.model,
                    updated_at=excluded.updated_at
                """,
                (
                    uid,
                    classification.value,
                    manual_reason,
                    suggested_action.value,
                    manual_reason,
                    queue_status,
                    now,
                    current_mailbox,
                    current_uidvalidity,
                    "user-label-manual",
                    now,
                    now,
                ),
            )
            identity = conn.execute(
                """
                SELECT
                    COALESCE(g.sender, m.sender, ''),
                    COALESCE(g.subject, m.subject, ''),
                    COALESCE(g.message_id, '')
                FROM mail_insights i
                LEFT JOIN mail_generation_items g ON g.mail_key = i.mail_key
                LEFT JOIN mail_items m ON m.uid = i.uid
                WHERE i.mail_key = ?
                """,
                (mail_key,),
            ).fetchone()
            _upsert_user_mail_label_decision(
                conn,
                uid=uid,
                mailbox=current_mailbox,
                mail_key=mail_key,
                sender=str(identity[0] or "") if identity else "",
                subject=str(identity[1] or "") if identity else "",
                message_id=str(identity[2] or "") if identity else "",
                importance=importance,
                needs_reply=needs_reply,
                privacy_level=privacy_level or "normal",
                now=now,
            )
        return self.get_mail_insight(uid, uid_validity=uid_validity, mailbox=mailbox)

    def create_user_label_rule(
        self,
        *,
        mailbox: str = "INBOX",
        sender_pattern: str = "",
        subject_keyword: str = "",
        importance: str,
        needs_reply: bool,
        privacy_level: str,
        source_uid: str = "",
        source_subject: str = "",
        source_sender: str = "",
    ) -> StoredUserLabelRule:
        _validate_importance(importance)
        _validate_privacy_level(privacy_level)
        clean_sender = _clean_rule_text(sender_pattern)
        clean_subject = _clean_rule_text(subject_keyword)
        if not clean_sender and not clean_subject:
            raise ValueError("规则至少需要发件人或主题关键词")
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO user_label_rules(
                    enabled,
                    mailbox,
                    sender_pattern,
                    subject_keyword,
                    importance,
                    needs_reply,
                    privacy_level,
                    source_uid,
                    source_subject,
                    source_sender,
                    created_at,
                    updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mailbox or "INBOX",
                    clean_sender,
                    clean_subject,
                    importance,
                    _bool_to_int(needs_reply),
                    privacy_level,
                    source_uid or "",
                    source_subject or "",
                    source_sender or "",
                    now,
                    now,
                ),
            )
            rule_id = int(cursor.lastrowid)
        rule = self.get_user_label_rule(rule_id)
        assert rule is not None
        return rule

    def get_user_label_rule(self, rule_id: int) -> StoredUserLabelRule | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, enabled, mailbox, sender_pattern, subject_keyword,
                       importance, needs_reply, privacy_level, source_uid,
                       source_subject, source_sender, match_count, last_matched_at,
                       created_at, updated_at
                FROM user_label_rules
                WHERE id = ?
                """,
                (rule_id,),
            ).fetchone()
        return _stored_user_label_rule(row) if row else None

    def list_user_label_rules(self, *, include_disabled: bool = False, limit: int = 100) -> list[StoredUserLabelRule]:
        where = "" if include_disabled else "WHERE enabled = 1"
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, enabled, mailbox, sender_pattern, subject_keyword,
                       importance, needs_reply, privacy_level, source_uid,
                       source_subject, source_sender, match_count, last_matched_at,
                       created_at, updated_at
                FROM user_label_rules
                {where}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_stored_user_label_rule(row) for row in rows]

    def delete_user_label_rule(self, rule_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM user_label_rules WHERE id = ?", (rule_id,))
            return cursor.rowcount > 0

    def match_user_label_rule(self, message: MailMessage, *, mailbox: str = "INBOX") -> StoredUserLabelRule | None:
        candidates = self.list_user_label_rules(limit=500)
        sender = (message.sender or "").lower()
        subject = (message.subject or "").lower()
        for rule in candidates:
            if rule.mailbox not in {"", "*", mailbox}:
                continue
            sender_ok = not rule.sender_pattern or rule.sender_pattern.lower() in sender
            subject_ok = not rule.subject_keyword or rule.subject_keyword.lower() in subject
            if sender_ok and subject_ok:
                now = _now()
                with self._connect() as conn:
                    conn.execute(
                        """
                        UPDATE user_label_rules
                        SET match_count = match_count + 1,
                            last_matched_at = ?,
                            updated_at = updated_at
                        WHERE id = ?
                        """,
                        (now, rule.id),
                    )
                return self.get_user_label_rule(rule.id) or rule
        return None

    def save_mail_insight_feedback(
        self,
        uid: str,
        *,
        feedback: str,
        comment: str = "",
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> StoredMailInsightFeedback | None:
        _validate_insight_feedback(feedback)
        mail_key = self._latest_mail_key(uid, uid_validity=uid_validity, mailbox=mailbox)
        if mail_key is None:
            return None
        now = _now()
        clean_comment = comment.strip()
        with self._connect() as conn:
            insight = conn.execute(
                """
                SELECT uid, importance, needs_reply
                FROM mail_insights
                WHERE mail_key = ?
                """,
                (mail_key,),
            ).fetchone()
            if insight is None:
                return None
            existing = conn.execute(
                """
                SELECT id, created_at
                FROM mail_insight_feedback
                WHERE mail_key = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (mail_key,),
            ).fetchone()
            if existing:
                feedback_id = int(existing[0])
                created_at = str(existing[1])
                conn.execute(
                    """
                    UPDATE mail_insight_feedback
                    SET uid = ?,
                        feedback = ?,
                        comment = ?,
                        importance_at_feedback = ?,
                        needs_reply_at_feedback = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(insight[0]),
                        feedback,
                        clean_comment,
                        str(insight[1]),
                        _bool_to_int(bool(insight[2])),
                        now,
                        feedback_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO mail_insight_feedback(
                        mail_key,
                        uid,
                        feedback,
                        comment,
                        importance_at_feedback,
                        needs_reply_at_feedback,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mail_key,
                        str(insight[0]),
                        feedback,
                        clean_comment,
                        str(insight[1]),
                        _bool_to_int(bool(insight[2])),
                        now,
                        now,
                    ),
                )
                feedback_id = int(cursor.lastrowid)
                created_at = now
        return StoredMailInsightFeedback(
            id=feedback_id,
            mail_key=mail_key,
            uid=str(insight[0]),
            feedback=feedback,
            comment=clean_comment,
            importance_at_feedback=str(insight[1]),
            needs_reply_at_feedback=bool(insight[2]),
            created_at=created_at,
            updated_at=now,
        )

    def get_latest_mail_insight_feedback(
        self,
        uid: str,
        *,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> StoredMailInsightFeedback | None:
        mail_key = self._latest_mail_key(uid, uid_validity=uid_validity, mailbox=mailbox)
        if mail_key is None:
            return None
        return self.get_latest_mail_insight_feedback_by_mail_key(mail_key)

    def get_latest_mail_insight_feedback_by_mail_key(self, mail_key: str) -> StoredMailInsightFeedback | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    mail_key,
                    uid,
                    feedback,
                    comment,
                    importance_at_feedback,
                    needs_reply_at_feedback,
                    created_at,
                    updated_at
                FROM mail_insight_feedback
                WHERE mail_key = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (mail_key,),
            ).fetchone()
        return _stored_insight_feedback(row) if row else None

    def set_notification_status(
        self,
        uid: str,
        status: str,
        *,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> bool:
        _validate_notification_status(status)
        mail_key = self._latest_mail_key(uid, uid_validity=uid_validity, mailbox=mailbox)
        if mail_key is None:
            return False
        return self.set_notification_status_by_mail_key(mail_key, status)

    def set_notification_status_by_mail_key(self, mail_key: str, status: str) -> bool:
        _validate_notification_status(status)
        with self._connect() as conn:
            if status == "notified":
                cursor = conn.execute(
                    """
                    UPDATE mail_insights
                    SET notification_status = 'notified', updated_at = ?
                    WHERE mail_key = ?
                    """,
                    (_now(), mail_key),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE mail_insights
                    SET notification_status = ?, updated_at = ?
                    WHERE mail_key = ? AND notification_status != 'notified'
                    """,
                    (status, _now(), mail_key),
                )
            return cursor.rowcount > 0

    def _latest_mail_key(
        self,
        uid: str,
        *,
        uid_validity: int | None,
        mailbox: str,
    ) -> str | None:
        if uid_validity is not None:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT mail_key FROM mail_insights
                    WHERE uid = ? AND mailbox = ? AND source_uidvalidity = ?
                    ORDER BY updated_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (uid, mailbox, uid_validity),
                ).fetchone()
        else:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT i.mail_key
                    FROM mail_insights i
                    LEFT JOIN mailbox_sync_state s ON s.mailbox = i.mailbox
                    WHERE i.uid = ? AND i.mailbox = ?
                    ORDER BY
                        CASE WHEN i.source_uidvalidity = s.uid_validity THEN 0 ELSE 1 END,
                        i.updated_at DESC,
                        i.rowid DESC
                    LIMIT 1
                    """,
                    (uid, mailbox),
                ).fetchone()
        return row[0] if row else None

    def get_latest_draft_for_uid(
        self,
        uid: str,
        *,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> StoredDraft | None:
        where = "uid = ?"
        params: list[object] = [uid]
        if uid_validity is not None:
            where += " AND source_uidvalidity = ? AND mailbox = ?"
            params.extend([uid_validity, mailbox])
        with self._connect() as conn:
            row = conn.execute(
                f"""
                {self._draft_select_sql()}
                FROM drafts
                WHERE {where}
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return StoredDraft(*row) if row else None

    def get_sync_state(self, mailbox: str = "INBOX") -> MailboxSyncState | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT mailbox, uid_validity, last_processed_uid, last_sync_at, updated_at
                FROM mailbox_sync_state
                WHERE mailbox = ?
                """,
                (mailbox,),
            ).fetchone()
        return MailboxSyncState(*row) if row else None

    def record_fetch_failure(
        self,
        mailbox: str,
        *,
        uid_validity: int,
        uid: int,
        quarantine_after: int = 3,
    ) -> FetchFailureState:
        if quarantine_after < 1:
            raise ValueError("quarantine_after must be positive")
        now = _now()
        mail_key = _mail_key(mailbox, uid_validity, f"uid:{uid}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mail_fetch_failures(
                    mail_key, mailbox, uid_validity, uid, failure_count,
                    quarantined, attention_status, first_failed_at,
                    last_failed_at, resolved_at
                )
                VALUES (?, ?, ?, ?, 1, ?, 'pending', ?, ?, NULL)
                ON CONFLICT(mail_key) DO UPDATE SET
                    failure_count=CASE
                        WHEN mail_fetch_failures.resolved_at IS NOT NULL THEN 1
                        ELSE mail_fetch_failures.failure_count + 1
                    END,
                    quarantined=CASE
                        WHEN (
                            CASE
                                WHEN mail_fetch_failures.resolved_at IS NOT NULL THEN 1
                                ELSE mail_fetch_failures.failure_count + 1
                            END
                        ) >= ? THEN 1 ELSE 0
                    END,
                    attention_status=CASE
                        WHEN mail_fetch_failures.resolved_at IS NOT NULL THEN 'pending'
                        ELSE mail_fetch_failures.attention_status
                    END,
                    first_failed_at=CASE
                        WHEN mail_fetch_failures.resolved_at IS NOT NULL THEN excluded.first_failed_at
                        ELSE mail_fetch_failures.first_failed_at
                    END,
                    last_failed_at=excluded.last_failed_at,
                    resolved_at=NULL
                """,
                (
                    mail_key,
                    mailbox,
                    uid_validity,
                    uid,
                    _bool_to_int(quarantine_after <= 1),
                    now,
                    now,
                    quarantine_after,
                ),
            )
            row = conn.execute(
                """
                SELECT mail_key, mailbox, uid_validity, uid, failure_count,
                       quarantined, attention_status, last_failed_at, resolved_at
                FROM mail_fetch_failures
                WHERE mail_key = ?
                """,
                (mail_key,),
            ).fetchone()
        assert row is not None
        return _fetch_failure_state(row)

    def mark_fetch_failure_attention(self, mail_key: str, status: str) -> bool:
        if status not in {"emitted", "failed"}:
            raise ValueError(f"Unknown fetch failure attention status: {status}")
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE mail_fetch_failures SET attention_status = ? WHERE mail_key = ?",
                (status, mail_key),
            )
            return cursor.rowcount > 0

    def resolve_fetch_failure(
        self,
        mailbox: str,
        *,
        uid_validity: int,
        uid: int,
    ) -> None:
        mail_key = _mail_key(mailbox, uid_validity, f"uid:{uid}")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mail_fetch_failures
                SET resolved_at = ?, quarantined = 0
                WHERE mail_key = ? AND resolved_at IS NULL
                """,
                (_now(), mail_key),
            )

    def list_quarantined_fetch_failures(
        self,
        *,
        uid_validity: int,
        mailbox: str = "INBOX",
        attention_statuses: tuple[str, ...] | None = None,
        limit: int = 100,
    ) -> list[FetchFailureState]:
        where = [
            "uid_validity = ?",
            "mailbox = ?",
            "quarantined = 1",
            "resolved_at IS NULL",
        ]
        params: list[object] = [uid_validity, mailbox]
        if attention_statuses:
            placeholders = ", ".join("?" for _ in attention_statuses)
            where.append(f"attention_status IN ({placeholders})")
            params.extend(attention_statuses)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT mail_key, mailbox, uid_validity, uid, failure_count,
                       quarantined, attention_status, last_failed_at, resolved_at
                FROM mail_fetch_failures
                WHERE {' AND '.join(where)}
                ORDER BY last_failed_at ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_fetch_failure_state(row) for row in rows]

    def save_sync_state(
        self,
        mailbox: str,
        *,
        uid_validity: int,
        last_processed_uid: int,
    ) -> MailboxSyncState:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mailbox_sync_state(
                    mailbox, uid_validity, last_processed_uid, last_sync_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mailbox) DO UPDATE SET
                    uid_validity=excluded.uid_validity,
                    last_processed_uid=CASE
                        WHEN mailbox_sync_state.uid_validity = excluded.uid_validity
                        THEN MAX(mailbox_sync_state.last_processed_uid, excluded.last_processed_uid)
                        ELSE excluded.last_processed_uid
                    END,
                    last_sync_at=excluded.last_sync_at,
                    updated_at=excluded.updated_at
                """,
                (mailbox, uid_validity, last_processed_uid, now, now),
            )
        state = self.get_sync_state(mailbox)
        assert state is not None
        return state

    def acquire_sync_lease(
        self,
        owner: str,
        *,
        lease_name: str = "mail-sync",
        ttl_seconds: float = 180,
    ) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("sync lease ttl must be positive")
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                INSERT INTO sync_leases(lease_name, owner, expires_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(lease_name) DO UPDATE SET
                    owner=excluded.owner,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at
                WHERE sync_leases.expires_at <= ? OR sync_leases.owner = excluded.owner
                """,
                (lease_name, owner, now + ttl_seconds, _now(), now),
            )
            return cursor.rowcount > 0

    def release_sync_lease(self, owner: str, *, lease_name: str = "mail-sync") -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sync_leases WHERE lease_name = ? AND owner = ?",
                (lease_name, owner),
            )

    def touch_sync_state(self, mailbox: str = "INBOX") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE mailbox_sync_state SET last_sync_at = ?, updated_at = ? WHERE mailbox = ?",
                (_now(), _now(), mailbox),
            )

    def reset_mail_recognition_cache(self) -> RecognitionCacheResetReport:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            counts: dict[str, int] = {}
            cursor = conn.execute("DELETE FROM mail_insight_feedback")
            counts["mail_insight_feedback"] = max(cursor.rowcount, 0)
            cursor = conn.execute(
                "DELETE FROM triage_results WHERE COALESCE(model, '') NOT IN ('user-label-manual', 'user-label-rule')"
            )
            counts["triage_results"] = max(cursor.rowcount, 0)
            cursor = conn.execute("DELETE FROM mail_insights WHERE COALESCE(label_source, 'ai') != 'user'")
            counts["mail_insights"] = max(cursor.rowcount, 0)
            cursor = conn.execute("DELETE FROM mail_fetch_failures")
            counts["mail_fetch_failures"] = max(cursor.rowcount, 0)
            cursor = conn.execute("DELETE FROM desktop_summaries")
            counts["desktop_summaries"] = max(cursor.rowcount, 0)
            cursor = conn.execute("DELETE FROM mailbox_sync_state")
            counts["mailbox_sync_state"] = max(cursor.rowcount, 0)
            cursor = conn.execute("DELETE FROM sync_leases")
            counts["sync_leases"] = max(cursor.rowcount, 0)
            conn.execute(
                "INSERT INTO action_log(uid, action, detail, created_at) VALUES (?, ?, ?, ?)",
                (
                    None,
                    "reset_recognition_cache",
                    "Cleared local AI labels, reply markers, privacy markers, queue state, feedback, fetch failures and sync cursor; preserved manual label decisions.",
                    _now(),
                ),
            )
        return RecognitionCacheResetReport(
            mail_insights=counts["mail_insights"],
            triage_results=counts["triage_results"],
            mail_insight_feedback=counts["mail_insight_feedback"],
            mail_fetch_failures=counts["mail_fetch_failures"],
            desktop_summaries=counts["desktop_summaries"],
            mailbox_sync_state=counts["mailbox_sync_state"],
            sync_leases=counts["sync_leases"],
        )

    def save_startup_summary(self, payload: dict[str, object]) -> StoredStartupSummary:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO desktop_summaries(
                    payload_json, created_at, delivery_status, emitted_at, acknowledged_at
                )
                VALUES (?, ?, 'pending', NULL, NULL)
                """,
                (json.dumps(payload, ensure_ascii=False), now),
            )
            summary_id = int(cursor.lastrowid)
        return StoredStartupSummary(id=summary_id, payload=dict(payload), created_at=now)

    def get_latest_startup_summary(self) -> StoredStartupSummary | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, payload_json, created_at, delivery_status, emitted_at, acknowledged_at
                FROM desktop_summaries
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return _stored_startup_summary(row)

    def list_unacknowledged_startup_summaries(self, limit: int = 10) -> list[StoredStartupSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, payload_json, created_at, delivery_status, emitted_at, acknowledged_at
                FROM desktop_summaries
                WHERE delivery_status != 'acknowledged'
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_stored_startup_summary(row) for row in rows]

    def mark_startup_summary_delivery(self, summary_id: int, status: str) -> bool:
        if status not in {"emitted", "acknowledged", "failed"}:
            raise ValueError(f"Unknown startup summary delivery status: {status}")
        now = _now()
        with self._connect() as conn:
            if status == "acknowledged":
                cursor = conn.execute(
                    """
                    UPDATE desktop_summaries
                    SET delivery_status = 'acknowledged', acknowledged_at = ?
                    WHERE id = ?
                    """,
                    (now, summary_id),
                )
            elif status == "emitted":
                cursor = conn.execute(
                    """
                    UPDATE desktop_summaries
                    SET delivery_status = 'emitted', emitted_at = ?
                    WHERE id = ? AND delivery_status != 'acknowledged'
                    """,
                    (now, summary_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE desktop_summaries
                    SET delivery_status = 'failed'
                    WHERE id = ? AND delivery_status != 'acknowledged'
                    """,
                    (summary_id,),
                )
            return cursor.rowcount > 0

    def save_draft(
        self,
        draft: Draft,
        *,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> StoredDraft:
        now = _now()
        target_mail_key = self._latest_mail_key(
            draft.mail_id,
            uid_validity=uid_validity,
            mailbox=mailbox,
        )
        source_uidvalidity = uid_validity or 0
        if uid_validity is None and target_mail_key is not None:
            target_insight = self.get_mail_insight(draft.mail_id, mailbox=mailbox)
            if target_insight is not None and target_insight.mail_key == target_mail_key:
                source_uidvalidity = target_insight.source_uidvalidity
                mailbox = target_insight.mailbox
        base_draft_id = (
            draft.id
            if source_uidvalidity == 0
            else f"{draft.id}--u{source_uidvalidity}"
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous_rows = conn.execute(
                """
                SELECT draft_id, COALESCE(draft_version, 1)
                FROM drafts
                WHERE base_draft_id = ? OR draft_id = ?
                ORDER BY COALESCE(draft_version, 1) DESC, rowid DESC
                """,
                (base_draft_id, base_draft_id),
            ).fetchall()
            supersedes_id = previous_rows[0][0] if previous_rows else None
            version = max((int(row[1]) for row in previous_rows), default=0) + 1
            draft_id = base_draft_id if version == 1 else f"{base_draft_id}--v{version}"
            while conn.execute("SELECT 1 FROM drafts WHERE draft_id = ?", (draft_id,)).fetchone():
                version += 1
                draft_id = f"{base_draft_id}--v{version}"
            conn.execute(
                """
                INSERT INTO drafts(
                    draft_id,
                    uid,
                    to_addr,
                    subject,
                    body,
                    body_preview,
                    reply_to_message_id,
                    reference_ids,
                    created_at,
                    sent_at,
                    send_status,
                    send_error,
                    send_attempt_id,
                    send_started_at,
                    send_finished_at,
                    base_draft_id,
                    supersedes_id,
                    draft_version,
                    mail_key,
                    mailbox,
                    source_uidvalidity
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'pending', NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    draft.mail_id,
                    draft.to,
                    draft.subject,
                    draft.body,
                    _preview(draft.body),
                    draft.reply_to_message_id,
                    draft.references,
                    now,
                    base_draft_id,
                    supersedes_id,
                    version,
                    target_mail_key,
                    mailbox,
                    source_uidvalidity,
                ),
            )
            if target_mail_key is not None:
                conn.execute(
                    """
                    UPDATE mail_insights
                    SET reply_status = 'draft_ready', draft_id = ?, updated_at = ?
                    WHERE mail_key = ?
                    """,
                    (draft_id, now, target_mail_key),
                )
            row = self._select_draft(conn, draft_id)
        assert row is not None
        stored = StoredDraft(*row)
        return stored

    def list_drafts(self, limit: int = 20, *, include_sent: bool = False, status: str = "pending") -> list[StoredDraft]:
        if include_sent:
            status = "all"
        if status == "pending":
            where = "WHERE COALESCE(send_status, CASE WHEN sent_at IS NULL THEN 'pending' ELSE 'sent' END) IN ('pending', 'failed')"
        elif status == "sent":
            where = "WHERE COALESCE(send_status, CASE WHEN sent_at IS NULL THEN 'pending' ELSE 'sent' END) = 'sent'"
        elif status in {"sending", "failed", "unknown"}:
            where = "WHERE COALESCE(send_status, 'pending') = ?"
        elif status == "all":
            where = ""
        else:
            raise ValueError(f"Unknown draft status: {status}")
        params: list[object] = []
        if status in {"sending", "failed", "unknown"}:
            params.append(status)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                {self._draft_select_sql()}
                FROM drafts
                {where}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [StoredDraft(*row) for row in rows]

    def get_draft(self, draft_id: str) -> StoredDraft | None:
        with self._connect() as conn:
            row = self._select_draft(conn, draft_id)
        return StoredDraft(*row) if row else None

    def update_draft(self, draft_id: str, *, subject: str, body: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE drafts
                SET subject = ?, body = ?, body_preview = ?
                WHERE draft_id = ?
                  AND COALESCE(send_status, CASE WHEN sent_at IS NULL THEN 'pending' ELSE 'sent' END)
                      IN ('pending', 'failed')
                """,
                (subject, body, _preview(body), draft_id),
            )
            return cursor.rowcount > 0

    def mark_draft_sent(self, draft_id: str) -> None:
        """Compatibility helper for older callers and migrations.

        New real-send paths must use claim/complete methods below so SMTP can
        never be invoked concurrently for the same draft.
        """
        with self._connect() as conn:
            now = _now()
            conn.execute(
                """
                UPDATE drafts
                SET sent_at = ?, send_status = 'sent', send_finished_at = ?, send_error = NULL
                WHERE draft_id = ?
                """,
                (now, now, draft_id),
            )
            conn.execute(
                """
                UPDATE mail_insights
                SET reply_status = 'sent', updated_at = ?
                WHERE draft_id = ?
                """,
                (now, draft_id),
            )

    def claim_draft_for_send(self, draft_id: str, *, attempt_id: str) -> StoredDraft | None:
        """Atomically move a retryable draft to ``sending`` and return its snapshot."""
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE drafts
                SET send_status = 'sending',
                    send_attempt_id = ?,
                    send_started_at = ?,
                    send_finished_at = NULL,
                    send_error = NULL
                WHERE draft_id = ?
                  AND COALESCE(send_status, CASE WHEN sent_at IS NULL THEN 'pending' ELSE 'sent' END)
                      IN ('pending', 'failed')
                """,
                (attempt_id, now, draft_id),
            )
            if cursor.rowcount == 0:
                return None
            row = self._select_draft(conn, draft_id)
        return StoredDraft(*row) if row else None

    def complete_draft_send(
        self,
        draft_id: str,
        *,
        attempt_id: str,
        warning: str | None = None,
    ) -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE drafts
                SET send_status = 'sent',
                    sent_at = ?,
                    send_finished_at = ?,
                    send_error = ?
                WHERE draft_id = ? AND send_status = 'sending' AND send_attempt_id = ?
                """,
                (now, now, warning, draft_id, attempt_id),
            )
            if cursor.rowcount > 0:
                conn.execute(
                    """
                    UPDATE mail_insights
                    SET reply_status = 'sent', updated_at = ?
                    WHERE draft_id = ?
                    """,
                    (now, draft_id),
                )
            return cursor.rowcount > 0

    def fail_draft_send(self, draft_id: str, *, attempt_id: str, error: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE drafts
                SET send_status = 'failed', send_finished_at = ?, send_error = ?
                WHERE draft_id = ? AND send_status = 'sending' AND send_attempt_id = ?
                """,
                (_now(), error, draft_id, attempt_id),
            )
            return cursor.rowcount > 0

    def mark_draft_send_unknown(self, draft_id: str, *, attempt_id: str, error: str) -> bool:
        """Lock a possibly delivered draft so it cannot be retried automatically."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE drafts
                SET send_status = 'unknown', send_finished_at = ?, send_error = ?
                WHERE draft_id = ? AND send_status = 'sending' AND send_attempt_id = ?
                """,
                (_now(), error, draft_id, attempt_id),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _draft_select_sql() -> str:
        return """
                SELECT
                    draft_id,
                    uid,
                    to_addr,
                    subject,
                    COALESCE(body, body_preview, ''),
                    COALESCE(body_preview, ''),
                    COALESCE(reply_to_message_id, ''),
                    COALESCE(reference_ids, ''),
                    created_at,
                    sent_at,
                    COALESCE(send_status, CASE WHEN sent_at IS NULL THEN 'pending' ELSE 'sent' END),
                    send_error,
                    send_attempt_id,
                    send_started_at,
                    send_finished_at,
                    COALESCE(base_draft_id, draft_id),
                    supersedes_id,
                    COALESCE(draft_version, 1),
                    mail_key,
                    COALESCE(mailbox, 'INBOX'),
                    COALESCE(source_uidvalidity, 0)
        """

    def _select_draft(self, conn: sqlite3.Connection, draft_id: str):
        return conn.execute(
            f"""
            {self._draft_select_sql()}
            FROM drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

    def log_action(self, action: str, *, uid: str | None = None, detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO action_log(uid, action, detail, created_at) VALUES (?, ?, ?, ?)",
                (uid, action, detail, _now()),
            )

    def list_triage_results(self, limit: int = 20, *, classification: str | None = None) -> list[StoredTriage]:
        where = ""
        params: list[object] = []
        if classification:
            where = "WHERE t.classification = ?"
            params.append(classification)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    t.uid,
                    m.sender,
                    m.subject,
                    t.classification,
                    t.reason,
                    COALESCE(t.suggested_action, 'read_full'),
                    COALESCE(t.action_reason, ''),
                    COALESCE(t.queue_status, 'pending'),
                    t.updated_at
                FROM triage_results t
                LEFT JOIN mail_items m ON m.uid = t.uid
                {where}
                ORDER BY t.updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [StoredTriage(*row) for row in rows]

    def list_suggested_triage_queue(self, limit: int = 20, *, statuses: tuple[str, ...] = ("pending", "later")) -> list[StoredTriage]:
        if not statuses:
            return []
        for status in statuses:
            _validate_queue_status(status)
        placeholders = ", ".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    t.uid,
                    m.sender,
                    m.subject,
                    t.classification,
                    t.reason,
                    COALESCE(t.suggested_action, 'read_full'),
                    COALESCE(t.action_reason, ''),
                    COALESCE(t.queue_status, 'pending'),
                    t.updated_at
                FROM triage_results t
                LEFT JOIN mail_items m ON m.uid = t.uid
                WHERE COALESCE(t.queue_status, 'pending') IN ({placeholders})
                ORDER BY
                    CASE COALESCE(t.queue_status, 'pending')
                        WHEN 'pending' THEN 1
                        WHEN 'later' THEN 2
                        WHEN 'done' THEN 3
                        WHEN 'skipped' THEN 4
                        ELSE 5
                    END,
                    CASE COALESCE(t.suggested_action, 'read_full')
                        WHEN 'draft_reply' THEN 1
                        WHEN 'translate' THEN 2
                        WHEN 'read_full' THEN 3
                        WHEN 'mark_seen' THEN 4
                        WHEN 'move_to_trash' THEN 5
                        WHEN 'no_action' THEN 6
                        ELSE 7
                    END,
                    t.updated_at DESC
                LIMIT ?
                """,
                (*statuses, limit),
            ).fetchall()
        return [StoredTriage(*row) for row in rows]

    def set_triage_queue_status(self, uid: str, status: str) -> bool:
        _validate_queue_status(status)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE triage_results
                SET queue_status = ?, queue_status_updated_at = ?
                WHERE uid = ?
                """,
                (status, _now(), uid),
            )
            return cursor.rowcount > 0

    def get_triage_result(self, uid: str) -> StoredTriage | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.uid,
                    m.sender,
                    m.subject,
                    t.classification,
                    t.reason,
                    COALESCE(t.suggested_action, 'read_full'),
                    COALESCE(t.action_reason, ''),
                    COALESCE(t.queue_status, 'pending'),
                    t.updated_at
                FROM triage_results t
                LEFT JOIN mail_items m ON m.uid = t.uid
                WHERE t.uid = ?
                """,
                (uid,),
            ).fetchone()
        return StoredTriage(*row) if row else None

    def get_triaged_uids(self, uids: list[str]) -> set[str]:
        unique_uids = list(dict.fromkeys(uid for uid in uids if uid))
        if not unique_uids:
            return set()
        placeholders = ", ".join("?" for _ in unique_uids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT uid FROM triage_results WHERE uid IN ({placeholders})",
                unique_uids,
            ).fetchall()
        return {row[0] for row in rows}

    def search_mail_items(
        self,
        limit: int = 20,
        *,
        keyword: str | None = None,
        is_seen: bool | None = None,
        classification: str | None = None,
        queue_status: str | None = None,
    ) -> list[StoredMailSearchResult]:
        where = []
        params: list[object] = []
        if keyword:
            pattern = f"%{keyword.strip()}%"
            where.append("(m.sender LIKE ? OR m.subject LIKE ?)")
            params.extend([pattern, pattern])
        if is_seen is not None:
            where.append("m.is_seen = ?")
            params.append(_bool_to_int(is_seen))
        if classification:
            where.append("t.classification = ?")
            params.append(classification)
        if queue_status:
            _validate_queue_status(queue_status)
            where.append("t.uid IS NOT NULL AND COALESCE(t.queue_status, 'pending') = ?")
            params.append(queue_status)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    m.uid,
                    m.sender,
                    m.subject,
                    m.date,
                    m.is_seen,
                    t.classification,
                    COALESCE(t.suggested_action, NULL),
                    CASE
                        WHEN t.uid IS NULL THEN NULL
                        ELSE COALESCE(t.queue_status, 'pending')
                    END,
                    m.updated_at
                FROM mail_items m
                LEFT JOIN triage_results t ON t.uid = m.uid
                {where_sql}
                ORDER BY m.updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            StoredMailSearchResult(
                uid=row[0],
                sender=row[1],
                subject=row[2],
                date=row[3],
                is_seen=_int_to_bool(row[4]),
                classification=row[5],
                suggested_action=row[6],
                queue_status=row[7],
                updated_at=row[8],
            )
            for row in rows
        ]

    def list_actions(self, limit: int = 30) -> list[ActionLogEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, uid, action, detail, created_at
                FROM action_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [ActionLogEntry(*row) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _backup_before_migration(self) -> None:
        if not self._db_path.exists() or self._db_path.stat().st_size == 0:
            return
        with closing(sqlite3.connect(self._db_path, timeout=5.0)) as source:
            current_version = int(source.execute("PRAGMA user_version").fetchone()[0])
            has_tables = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
            ).fetchone()
            if current_version >= self._SCHEMA_VERSION or has_tables is None:
                return
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = self._db_path.with_name(
                f"{self._db_path.name}.pre-v{self._SCHEMA_VERSION}-{timestamp}-{uuid4().hex[:8]}.backup"
            )
            with closing(sqlite3.connect(backup_path)) as destination:
                source.backup(destination)
                destination.commit()

    def _init_db(self) -> None:
        with self._connect() as conn:
            current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current_version > self._SCHEMA_VERSION:
                raise RuntimeError(
                    f"State database schema v{current_version} is newer than supported v{self._SCHEMA_VERSION}."
                )
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mail_items (
                    uid TEXT PRIMARY KEY,
                    sender TEXT,
                    recipient TEXT,
                    subject TEXT,
                    date TEXT,
                    is_seen INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS triage_results (
                    uid TEXT PRIMARY KEY,
                    classification TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS drafts (
                    draft_id TEXT PRIMARY KEY,
                    uid TEXT,
                    to_addr TEXT,
                    subject TEXT,
                    body TEXT,
                    body_preview TEXT,
                    reply_to_message_id TEXT,
                    reference_ids TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    send_status TEXT NOT NULL DEFAULT 'pending',
                    send_error TEXT,
                    send_attempt_id TEXT,
                    send_started_at TEXT,
                    send_finished_at TEXT,
                    base_draft_id TEXT,
                    supersedes_id TEXT,
                    draft_version INTEGER NOT NULL DEFAULT 1,
                    mail_key TEXT,
                    mailbox TEXT NOT NULL DEFAULT 'INBOX',
                    source_uidvalidity INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS action_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT,
                    action TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mail_insights (
                    mail_key TEXT PRIMARY KEY,
                    uid TEXT NOT NULL,
                    mailbox TEXT NOT NULL,
                    source_uidvalidity INTEGER NOT NULL,
                    importance TEXT NOT NULL DEFAULT 'general',
                    needs_reply INTEGER NOT NULL DEFAULT 0,
                    summary_zh TEXT NOT NULL DEFAULT '',
                    action_items_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0,
                    priority_reason TEXT NOT NULL DEFAULT '',
                    analysis_status TEXT NOT NULL DEFAULT 'pending',
                    reply_status TEXT NOT NULL DEFAULT 'review_required',
                    notification_status TEXT NOT NULL DEFAULT 'pending',
                    analysis_error TEXT,
                    label_source TEXT NOT NULL DEFAULT 'ai',
                    draft_id TEXT,
                    analyzed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mailbox, source_uidvalidity, uid)
                );

                CREATE TABLE IF NOT EXISTS mail_insight_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mail_key TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    feedback TEXT NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    importance_at_feedback TEXT,
                    needs_reply_at_feedback INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mail_key)
                );

                CREATE TABLE IF NOT EXISTS mail_generation_items (
                    mail_key TEXT PRIMARY KEY,
                    uid TEXT NOT NULL,
                    mailbox TEXT NOT NULL,
                    source_uidvalidity INTEGER NOT NULL,
                    sender TEXT,
                    recipient TEXT,
                    subject TEXT,
                    date TEXT,
                    is_seen INTEGER,
                    message_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mailbox, source_uidvalidity, uid)
                );

                CREATE INDEX IF NOT EXISTS idx_mail_insights_filters
                ON mail_insights(importance, needs_reply, analysis_status, reply_status, updated_at);

                CREATE INDEX IF NOT EXISTS idx_mail_insight_feedback_uid
                ON mail_insight_feedback(uid, updated_at);

                CREATE TABLE IF NOT EXISTS mailbox_sync_state (
                    mailbox TEXT PRIMARY KEY,
                    uid_validity INTEGER NOT NULL,
                    last_processed_uid INTEGER NOT NULL DEFAULT 0,
                    last_sync_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_leases (
                    lease_name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS desktop_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivery_status TEXT NOT NULL DEFAULT 'pending',
                    emitted_at TEXT,
                    acknowledged_at TEXT
                );

                CREATE TABLE IF NOT EXISTS mail_fetch_failures (
                    mail_key TEXT PRIMARY KEY,
                    mailbox TEXT NOT NULL,
                    uid_validity INTEGER NOT NULL,
                    uid INTEGER NOT NULL,
                    failure_count INTEGER NOT NULL,
                    quarantined INTEGER NOT NULL DEFAULT 0,
                    attention_status TEXT NOT NULL DEFAULT 'pending',
                    first_failed_at TEXT NOT NULL,
                    last_failed_at TEXT NOT NULL,
                    resolved_at TEXT,
                    UNIQUE(mailbox, uid_validity, uid)
                );

                CREATE TABLE IF NOT EXISTS user_label_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    mailbox TEXT NOT NULL DEFAULT 'INBOX',
                    sender_pattern TEXT NOT NULL DEFAULT '',
                    subject_keyword TEXT NOT NULL DEFAULT '',
                    importance TEXT NOT NULL DEFAULT 'general',
                    needs_reply INTEGER NOT NULL DEFAULT 0,
                    privacy_level TEXT NOT NULL DEFAULT 'normal',
                    source_uid TEXT NOT NULL DEFAULT '',
                    source_subject TEXT NOT NULL DEFAULT '',
                    source_sender TEXT NOT NULL DEFAULT '',
                    match_count INTEGER NOT NULL DEFAULT 0,
                    last_matched_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_user_label_rules_enabled
                ON user_label_rules(enabled, mailbox, updated_at);

                CREATE TABLE IF NOT EXISTS user_mail_label_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    mailbox TEXT NOT NULL DEFAULT 'INBOX',
                    uid TEXT NOT NULL,
                    message_id TEXT NOT NULL DEFAULT '',
                    sender_key TEXT NOT NULL DEFAULT '',
                    subject_key TEXT NOT NULL DEFAULT '',
                    importance TEXT NOT NULL DEFAULT 'general',
                    needs_reply INTEGER NOT NULL DEFAULT 0,
                    privacy_level TEXT NOT NULL DEFAULT 'normal',
                    source_mail_key TEXT NOT NULL DEFAULT '',
                    apply_count INTEGER NOT NULL DEFAULT 0,
                    last_applied_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mailbox, uid)
                );

                CREATE INDEX IF NOT EXISTS idx_user_mail_label_decisions_lookup
                ON user_mail_label_decisions(enabled, mailbox, uid, updated_at);
                """
            )
            _ensure_column(conn, "drafts", "body", "TEXT")
            _ensure_column(conn, "drafts", "reply_to_message_id", "TEXT")
            _ensure_column(conn, "drafts", "reference_ids", "TEXT")
            _ensure_column(conn, "drafts", "sent_at", "TEXT")
            _ensure_column(conn, "drafts", "send_status", "TEXT DEFAULT 'pending'")
            _ensure_column(conn, "drafts", "send_error", "TEXT")
            _ensure_column(conn, "drafts", "send_attempt_id", "TEXT")
            _ensure_column(conn, "drafts", "send_started_at", "TEXT")
            _ensure_column(conn, "drafts", "send_finished_at", "TEXT")
            _ensure_column(conn, "drafts", "base_draft_id", "TEXT")
            _ensure_column(conn, "drafts", "supersedes_id", "TEXT")
            _ensure_column(conn, "drafts", "draft_version", "INTEGER DEFAULT 1")
            _ensure_column(conn, "drafts", "mail_key", "TEXT")
            _ensure_column(conn, "drafts", "mailbox", "TEXT DEFAULT 'INBOX'")
            _ensure_column(conn, "drafts", "source_uidvalidity", "INTEGER DEFAULT 0")
            _ensure_column(conn, "triage_results", "suggested_action", "TEXT DEFAULT 'read_full'")
            _ensure_column(conn, "triage_results", "action_reason", "TEXT DEFAULT ''")
            _ensure_column(conn, "triage_results", "queue_status", "TEXT DEFAULT 'pending'")
            _ensure_column(conn, "triage_results", "queue_status_updated_at", "TEXT")
            _ensure_column(conn, "triage_results", "mailbox", "TEXT DEFAULT 'INBOX'")
            _ensure_column(conn, "triage_results", "source_uidvalidity", "INTEGER DEFAULT 0")
            _ensure_column(conn, "mail_generation_items", "message_id", "TEXT DEFAULT ''")
            _ensure_column(conn, "desktop_summaries", "delivery_status", "TEXT DEFAULT 'pending'")
            _ensure_column(conn, "desktop_summaries", "emitted_at", "TEXT")
            _ensure_column(conn, "desktop_summaries", "acknowledged_at", "TEXT")
            _ensure_column(conn, "mail_insight_feedback", "comment", "TEXT DEFAULT ''")
            _ensure_column(conn, "mail_insight_feedback", "importance_at_feedback", "TEXT")
            _ensure_column(conn, "mail_insight_feedback", "needs_reply_at_feedback", "INTEGER")
            _ensure_column(conn, "mail_insights", "label_source", "TEXT DEFAULT 'ai'")
            _ensure_column(conn, "user_label_rules", "enabled", "INTEGER DEFAULT 1")
            _ensure_column(conn, "user_label_rules", "mailbox", "TEXT DEFAULT 'INBOX'")
            _ensure_column(conn, "user_label_rules", "sender_pattern", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_label_rules", "subject_keyword", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_label_rules", "importance", "TEXT DEFAULT 'general'")
            _ensure_column(conn, "user_label_rules", "needs_reply", "INTEGER DEFAULT 0")
            _ensure_column(conn, "user_label_rules", "privacy_level", "TEXT DEFAULT 'normal'")
            _ensure_column(conn, "user_label_rules", "source_uid", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_label_rules", "source_subject", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_label_rules", "source_sender", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_label_rules", "match_count", "INTEGER DEFAULT 0")
            _ensure_column(conn, "user_label_rules", "last_matched_at", "TEXT")
            _ensure_column(conn, "user_mail_label_decisions", "enabled", "INTEGER DEFAULT 1")
            _ensure_column(conn, "user_mail_label_decisions", "mailbox", "TEXT DEFAULT 'INBOX'")
            _ensure_column(conn, "user_mail_label_decisions", "uid", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_mail_label_decisions", "message_id", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_mail_label_decisions", "sender_key", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_mail_label_decisions", "subject_key", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_mail_label_decisions", "importance", "TEXT DEFAULT 'general'")
            _ensure_column(conn, "user_mail_label_decisions", "needs_reply", "INTEGER DEFAULT 0")
            _ensure_column(conn, "user_mail_label_decisions", "privacy_level", "TEXT DEFAULT 'normal'")
            _ensure_column(conn, "user_mail_label_decisions", "source_mail_key", "TEXT DEFAULT ''")
            _ensure_column(conn, "user_mail_label_decisions", "apply_count", "INTEGER DEFAULT 0")
            _ensure_column(conn, "user_mail_label_decisions", "last_applied_at", "TEXT")
            conn.execute(
                """
                UPDATE drafts
                SET send_status = CASE
                        WHEN sent_at IS NOT NULL THEN 'sent'
                        WHEN send_status IS NULL OR send_status = '' THEN 'pending'
                        ELSE send_status
                    END,
                    base_draft_id = COALESCE(NULLIF(base_draft_id, ''), draft_id),
                    draft_version = COALESCE(draft_version, 1)
                """
            )
            conn.execute(f"PRAGMA user_version = {self._SCHEMA_VERSION}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _uid_lookup_values(uid: str) -> tuple[str, ...]:
    value = uid.strip()
    values = [value]
    if value.startswith("uid:"):
        values.append(value[4:])
    elif value:
        values.append(f"uid:{value}")
    return tuple(dict.fromkeys(item for item in values if item))


def _int_to_bool(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _preview(value: str, limit: int = 300) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _validate_queue_status(status: str) -> None:
    if status not in {"pending", "later", "done", "skipped"}:
        raise ValueError(f"Unknown queue status: {status}")


def _validate_importance(value: str) -> None:
    if value not in {item.value for item in MailImportance}:
        raise ValueError(f"Unknown importance: {value}")


def _validate_privacy_level(value: str) -> None:
    if value not in {"normal", "sensitive", "private"}:
        raise ValueError(f"Unknown privacy level: {value}")


def _analysis_error_from_privacy_level(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "normal":
        return "privacy_normal"
    if value == "sensitive":
        return "privacy_sensitive"
    if value == "private":
        return "privacy_private"
    raise ValueError(f"Unknown privacy level: {value}")


def _validate_analysis_status(value: str) -> None:
    if value not in {"pending", "analyzing", "analyzed", "failed", "review_required"}:
        raise ValueError(f"Unknown analysis status: {value}")


def _validate_reply_status(value: str) -> None:
    if value not in {"not_needed", "review_required", "needs_reply", "draft_ready", "sent"}:
        raise ValueError(f"Unknown reply status: {value}")


def _validate_notification_status(value: str) -> None:
    if value not in {
        "not_required",
        "pending",
        "event_emitted",
        "notified",
        "failed",
        "attention_pending",
        "attention_emitted",
        "attention_failed",
    }:
        raise ValueError(f"Unknown notification status: {value}")


def _validate_insight_feedback(value: str) -> None:
    if value not in {"correct", "wrong"}:
        raise ValueError(f"Unknown AI feedback: {value}")


def _effective_insight(result: TriageResult) -> tuple[MailImportance, bool]:
    needs_reply = result.needs_reply or result.classification == MailClassification.RESPOND
    importance = result.importance
    if importance == MailImportance.GENERAL and result.classification == MailClassification.NOTIFY:
        importance = MailImportance.IMPORTANT
    return importance, needs_reply


def apply_user_label_rule(result: TriageResult, rule: StoredUserLabelRule) -> TriageResult:
    importance = MailImportance(rule.importance)
    classification = _classification_from_labels(importance=importance, needs_reply=rule.needs_reply)
    reason = f"命中本地用户规则：{_rule_match_label(rule)}。"
    priority_reason = reason if not result.priority_reason else f"{reason} 原判断：{result.priority_reason}"
    return TriageResult(
        mail_id=result.mail_id,
        classification=classification,
        reason=reason,
        suggested_action=_suggested_action_for_classification(classification),
        action_reason=reason,
        importance=importance,
        needs_reply=rule.needs_reply,
        summary_zh=result.summary_zh,
        action_items=result.action_items,
        confidence=max(result.confidence, 0.95),
        priority_reason=priority_reason,
    )


def analysis_error_from_privacy_level(value: str | None) -> str | None:
    return _analysis_error_from_privacy_level(value)


def _classification_from_labels(*, importance: MailImportance, needs_reply: bool) -> MailClassification:
    if needs_reply:
        return MailClassification.RESPOND
    if importance != MailImportance.GENERAL:
        return MailClassification.NOTIFY
    return MailClassification.IGNORE


def _suggested_action_for_classification(classification: MailClassification) -> SuggestedAction:
    if classification == MailClassification.RESPOND:
        return SuggestedAction.DRAFT_REPLY
    if classification == MailClassification.NOTIFY:
        return SuggestedAction.READ_FULL
    return SuggestedAction.NO_ACTION


def _manual_label_reason(*, importance: str, needs_reply: bool, privacy_level: str | None) -> str:
    parts = [
        f"重要性={importance}",
        f"回复={'待回复' if needs_reply else '不需回复'}",
    ]
    if privacy_level:
        parts.append(f"隐私={privacy_level}")
    return "用户手动标记：" + "，".join(parts) + "。"


def _rule_match_label(rule: StoredUserLabelRule) -> str:
    parts = []
    if rule.sender_pattern:
        parts.append("发件人")
    if rule.subject_keyword:
        parts.append("主题关键词")
    return " + ".join(parts) or f"规则 #{rule.id}"


def _clamp_confidence(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _mail_key(mailbox: str, uid_validity: int, uid: str) -> str:
    return f"{mailbox}\x1f{uid_validity}\x1f{uid}"


def _clean_rule_text(value: str) -> str:
    return " ".join((value or "").strip().split())[:160]


def _upsert_user_mail_label_decision(
    conn: sqlite3.Connection,
    *,
    uid: str,
    mailbox: str,
    mail_key: str,
    sender: str,
    subject: str,
    message_id: str,
    importance: str,
    needs_reply: bool,
    privacy_level: str,
    now: str,
) -> None:
    _validate_importance(importance)
    _validate_privacy_level(privacy_level)
    conn.execute(
        """
        INSERT INTO user_mail_label_decisions(
            enabled,
            mailbox,
            uid,
            message_id,
            sender_key,
            subject_key,
            importance,
            needs_reply,
            privacy_level,
            source_mail_key,
            created_at,
            updated_at
        )
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mailbox, uid) DO UPDATE SET
            enabled=1,
            message_id=excluded.message_id,
            sender_key=excluded.sender_key,
            subject_key=excluded.subject_key,
            importance=excluded.importance,
            needs_reply=excluded.needs_reply,
            privacy_level=excluded.privacy_level,
            source_mail_key=excluded.source_mail_key,
            updated_at=excluded.updated_at
        """,
        (
            mailbox or "INBOX",
            uid,
            _normalized_mail_message_id_key(message_id),
            _normalized_mail_sender_key(sender),
            _normalized_mail_subject_key(subject),
            importance,
            _bool_to_int(needs_reply),
            privacy_level,
            mail_key,
            now,
            now,
        ),
    )


def _has_matching_user_label_decision(conn: sqlite3.Connection, message: MailMessage, mailbox: str) -> bool:
    return _matching_user_label_decision_row(conn, message, mailbox) is not None


def _matching_user_label_decision_row(
    conn: sqlite3.Connection,
    message: MailMessage,
    mailbox: str,
) -> tuple[object, ...] | None:
    decision = _matching_user_mail_label_decision_row(conn, message, mailbox)
    if decision is not None:
        return _user_mail_label_decision_to_label_row(decision)

    sender = _normalized_mail_sender_key(message.sender)
    subject = _normalized_mail_subject_key(message.subject)
    message_id = _normalized_mail_message_id_key(message.message_id)
    if not message_id and not sender and not subject:
        return None
    rows = conn.execute(
        """
        SELECT
            i.importance,
            i.needs_reply,
            i.summary_zh,
            i.action_items_json,
            i.confidence,
            i.priority_reason,
            i.reply_status,
            i.notification_status,
            i.analysis_error,
            i.draft_id,
            COALESCE(t.queue_status, 'pending'),
            COALESCE(g.message_id, ''),
            COALESCE(g.sender, m.sender, '') AS stored_sender,
            COALESCE(g.subject, m.subject, '') AS stored_subject
        FROM mail_insights i
        LEFT JOIN mail_generation_items g ON g.mail_key = i.mail_key
        LEFT JOIN mail_items m ON m.uid = i.uid
        LEFT JOIN triage_results t ON t.uid = i.uid
        WHERE i.uid = ?
          AND i.mailbox = ?
          AND COALESCE(i.label_source, 'ai') = 'user'
        ORDER BY i.updated_at DESC, i.rowid DESC
        LIMIT 50
        """,
        (message.id, mailbox),
    ).fetchall()
    for row in rows:
        stored_message_id = _normalized_mail_message_id_key(str(row[11] or ""))
        stored_sender = _normalized_mail_sender_key(str(row[12] or ""))
        stored_subject = _normalized_mail_subject_key(str(row[13] or ""))
        if (message_id and stored_message_id and stored_message_id == message_id) or (
            stored_sender == sender and stored_subject == subject
        ):
            return row[:11]
    return None


def _matching_user_mail_label_decision_row(
    conn: sqlite3.Connection,
    message: MailMessage,
    mailbox: str,
) -> tuple[object, ...] | None:
    current_message_id = _normalized_mail_message_id_key(message.message_id)
    current_sender = _normalized_mail_sender_key(message.sender)
    current_subject = _normalized_mail_subject_key(message.subject)
    rows = conn.execute(
        """
        SELECT
            id,
            mailbox,
            uid,
            message_id,
            sender_key,
            subject_key,
            importance,
            needs_reply,
            privacy_level
        FROM user_mail_label_decisions
        WHERE enabled = 1
          AND uid = ?
          AND mailbox IN (?, '', '*')
        ORDER BY updated_at DESC, id DESC
        LIMIT 20
        """,
        (message.id, mailbox),
    ).fetchall()
    fallback_uid_only: tuple[object, ...] | None = None
    for row in rows:
        stored_message_id = str(row[3] or "")
        stored_sender = str(row[4] or "")
        stored_subject = str(row[5] or "")
        if current_message_id and stored_message_id:
            if stored_message_id == current_message_id:
                return row
            continue
        if stored_message_id:
            continue
        has_stored_identity = bool(stored_sender or stored_subject)
        has_current_identity = bool(current_sender or current_subject)
        if has_stored_identity and has_current_identity:
            sender_ok = not stored_sender or stored_sender == current_sender
            subject_ok = not stored_subject or stored_subject == current_subject
            if sender_ok and subject_ok:
                return row
            continue
        if not has_stored_identity:
            fallback_uid_only = fallback_uid_only or row
    return fallback_uid_only


def _user_mail_label_decision_to_label_row(row: tuple[object, ...]) -> tuple[object, ...]:
    importance = str(row[6] or MailImportance.GENERAL.value)
    needs_reply = bool(row[7])
    privacy_level = str(row[8] or "normal")
    classification = _classification_from_labels(importance=MailImportance(importance), needs_reply=needs_reply)
    reason = _manual_label_reason(importance=importance, needs_reply=needs_reply, privacy_level=privacy_level)
    return (
        importance,
        _bool_to_int(needs_reply),
        reason,
        "[]",
        0.95,
        reason,
        "needs_reply" if needs_reply else "not_needed",
        "pending" if importance != MailImportance.GENERAL.value else "not_required",
        _analysis_error_from_privacy_level(privacy_level),
        None,
        "pending" if classification != MailClassification.IGNORE else "done",
    )


def _copy_matching_user_label_decision(
    conn: sqlite3.Connection,
    message: MailMessage,
    *,
    mailbox: str,
    uid_validity: int,
    now: str,
) -> None:
    row = _matching_user_label_decision_row(conn, message, mailbox)
    if row is None:
        return
    importance = str(row[0] or MailImportance.GENERAL.value)
    needs_reply = bool(row[1])
    summary_zh = str(row[2] or "")
    action_items_json = str(row[3] or "[]")
    confidence = _clamp_confidence(row[4])
    priority_reason = str(row[5] or _manual_label_reason(importance=importance, needs_reply=needs_reply, privacy_level=None))
    reply_status = str(row[6] or ("needs_reply" if needs_reply else "not_needed"))
    notification_status = str(row[7] or ("pending" if importance != MailImportance.GENERAL.value else "not_required"))
    analysis_error = row[8] if isinstance(row[8], str) else None
    draft_id = row[9] if isinstance(row[9], str) else None
    queue_status = str(row[10] or "pending")
    mail_key = _mail_key(mailbox, uid_validity, message.id)
    classification = _classification_from_labels(importance=MailImportance(importance), needs_reply=needs_reply)
    suggested_action = _suggested_action_for_classification(classification)
    conn.execute(
        """
        INSERT INTO triage_results(
            uid,
            classification,
            reason,
            suggested_action,
            action_reason,
            queue_status,
            queue_status_updated_at,
            mailbox,
            source_uidvalidity,
            model,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'user-label-manual', ?, ?)
        ON CONFLICT(uid) DO UPDATE SET
            classification=excluded.classification,
            reason=excluded.reason,
            suggested_action=excluded.suggested_action,
            action_reason=excluded.action_reason,
            queue_status=excluded.queue_status,
            queue_status_updated_at=excluded.queue_status_updated_at,
            mailbox=excluded.mailbox,
            source_uidvalidity=excluded.source_uidvalidity,
            model=excluded.model,
            updated_at=excluded.updated_at
        """,
        (
            message.id,
            classification.value,
            priority_reason,
            suggested_action.value,
            priority_reason,
            queue_status,
            now,
            mailbox,
            uid_validity,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO mail_insights(
            mail_key,
            uid,
            mailbox,
            source_uidvalidity,
            importance,
            needs_reply,
            summary_zh,
            action_items_json,
            confidence,
            priority_reason,
            analysis_status,
            reply_status,
            notification_status,
            analysis_error,
            label_source,
            draft_id,
            analyzed_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'analyzed', ?, ?, ?, 'user', ?, ?, ?, ?)
        ON CONFLICT(mail_key) DO UPDATE SET
            importance=excluded.importance,
            needs_reply=excluded.needs_reply,
            summary_zh=excluded.summary_zh,
            action_items_json=excluded.action_items_json,
            confidence=excluded.confidence,
            priority_reason=excluded.priority_reason,
            analysis_status='analyzed',
            reply_status=excluded.reply_status,
            notification_status=excluded.notification_status,
            analysis_error=excluded.analysis_error,
            label_source='user',
            draft_id=COALESCE(mail_insights.draft_id, excluded.draft_id),
            analyzed_at=excluded.analyzed_at,
            updated_at=excluded.updated_at
        """,
        (
            mail_key,
            message.id,
            mailbox,
            uid_validity,
            importance,
            _bool_to_int(needs_reply),
            summary_zh,
            action_items_json,
            confidence,
            priority_reason,
            reply_status,
            notification_status,
            analysis_error,
            draft_id,
            now,
            now,
            now,
        ),
    )


def _normalized_mail_sender_key(value: str | None) -> str:
    text = " ".join((value or "").strip().split())
    if not text:
        return ""
    email = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.I)
    if email:
        return email.group(0).lower()
    text = text.replace("mailto:", "")
    return text.lower().strip('<>"\'[]()')


def _normalized_mail_subject_key(value: str | None) -> str:
    text = " ".join((value or "").strip().split())
    if not text:
        return ""
    while True:
        next_text = re.sub(r"^(re|fw|fwd)\s*:\s*", "", text, flags=re.I)
        if next_text == text:
            break
        text = next_text
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    return text.lower()


def _normalized_mail_message_id_key(value: str | None) -> str:
    text = " ".join((value or "").strip().split())
    if not text:
        return ""
    text = text.strip("<>")
    return text.lower()


def _stored_insight(row: tuple[object, ...]) -> StoredMailInsight:
    return StoredMailInsight(
        mail_key=str(row[0]),
        uid=str(row[1]),
        mailbox=str(row[2]),
        source_uidvalidity=int(row[3]),
        sender=row[4] if isinstance(row[4], str) else None,
        subject=row[5] if isinstance(row[5], str) else None,
        date=row[6] if isinstance(row[6], str) else None,
        is_seen=_int_to_bool(row[7] if isinstance(row[7], int) else None),
        importance=str(row[8]),
        needs_reply=bool(row[9]),
        summary_zh=str(row[10] or ""),
        action_items=_load_json_strings(row[11]),
        confidence=float(row[12] or 0),
        priority_reason=str(row[13] or ""),
        analysis_status=str(row[14]),
        reply_status=str(row[15]),
        notification_status=str(row[16]),
        analysis_error=row[17] if isinstance(row[17], str) else None,
        draft_id=row[18] if isinstance(row[18], str) else None,
        analyzed_at=row[19] if isinstance(row[19], str) else None,
        updated_at=str(row[20]),
        queue_status=row[21] if len(row) > 21 and isinstance(row[21], str) else None,
    )


def _stored_insight_feedback(row: tuple[object, ...]) -> StoredMailInsightFeedback:
    return StoredMailInsightFeedback(
        id=int(row[0]),
        mail_key=str(row[1]),
        uid=str(row[2]),
        feedback=str(row[3]),
        comment=str(row[4] or ""),
        importance_at_feedback=row[5] if isinstance(row[5], str) else None,
        needs_reply_at_feedback=_int_to_bool(row[6] if isinstance(row[6], int) else None),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )


def _stored_user_label_rule(row: tuple[object, ...]) -> StoredUserLabelRule:
    return StoredUserLabelRule(
        id=int(row[0]),
        enabled=bool(row[1]),
        mailbox=str(row[2] or "INBOX"),
        sender_pattern=str(row[3] or ""),
        subject_keyword=str(row[4] or ""),
        importance=str(row[5] or "general"),
        needs_reply=bool(row[6]),
        privacy_level=str(row[7] or "normal"),
        source_uid=str(row[8] or ""),
        source_subject=str(row[9] or ""),
        source_sender=str(row[10] or ""),
        match_count=int(row[11] or 0),
        last_matched_at=row[12] if isinstance(row[12], str) else None,
        created_at=str(row[13]),
        updated_at=str(row[14]),
    )


def _load_json_strings(value: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(item for raw in parsed if (item := str(raw).strip()))


def _load_json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stored_startup_summary(row: tuple[object, ...]) -> StoredStartupSummary:
    return StoredStartupSummary(
        id=int(row[0]),
        payload=_load_json_object(row[1]),
        created_at=str(row[2]),
        delivery_status=str(row[3] or "pending"),
        emitted_at=row[4] if isinstance(row[4], str) else None,
        acknowledged_at=row[5] if isinstance(row[5], str) else None,
    )


def _fetch_failure_state(row: tuple[object, ...]) -> FetchFailureState:
    return FetchFailureState(
        mail_key=str(row[0]),
        mailbox=str(row[1]),
        uid_validity=int(row[2]),
        uid=int(row[3]),
        failure_count=int(row[4]),
        quarantined=bool(row[5]),
        attention_status=str(row[6]),
        last_failed_at=str(row[7]),
        resolved_at=row[8] if isinstance(row[8], str) else None,
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in rows}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

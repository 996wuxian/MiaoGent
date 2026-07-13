from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Protocol
from uuid import uuid4

from qq_mail_agent_cli.agent import MailAgent
from qq_mail_agent_cli.desktop_events import EventSink, NullEventSink
from qq_mail_agent_cli.mail_client import IncrementalMailBatch, MailClient
from qq_mail_agent_cli.models import MailMessage
from qq_mail_agent_cli.privacy import PrivacyConfig, privacy_review_summary, should_block_ai
from qq_mail_agent_cli.services.draft_service import DraftService
from qq_mail_agent_cli.storage import StateStore, StoredMailInsight, StoredStartupSummary


class IncrementalMailClient(Protocol):
    def fetch_incremental(
        self,
        *,
        mailbox: str,
        expected_uid_validity: int | None,
        last_processed_uid: int | None,
        limit: int,
        initial_window: int,
    ) -> IncrementalMailBatch: ...


@dataclass(frozen=True)
class StartupSummaryItem:
    uid: str
    sender: str | None
    subject: str | None
    importance: str | None
    needs_reply: bool | None
    summary_zh: str
    priority_reason: str
    confidence: float
    analysis_status: str
    analysis_error: str | None
    reply_status: str
    notification_status: str
    draft_id: str | None


@dataclass(frozen=True)
class StartupSummaryFailure:
    uid: str
    stage: str
    error: str


@dataclass(frozen=True)
class StartupSummary:
    trigger: str
    generated_at: str
    new_count: int
    processed_count: int
    important_count: int
    urgent_count: int
    reply_count: int
    draft_ready_count: int
    general_count: int
    failed_count: int
    has_more: bool
    items: tuple[StartupSummaryItem, ...]
    failures: tuple[StartupSummaryFailure, ...]

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


class SyncAlreadyRunningError(RuntimeError):
    pass


class MailSyncService:
    """Incrementally analyze mail and prepare drafts without sending anything."""

    _MAX_AI_BODY_CHARS = 50_000

    def __init__(
        self,
        client: IncrementalMailClient | MailClient,
        agent: MailAgent,
        store: StateStore,
        *,
        event_sink: EventSink | None = None,
        model: str = "desktop-agent",
        mailbox: str = "INBOX",
        privacy_config: PrivacyConfig | None = None,
    ) -> None:
        self._client = client
        self._agent = agent
        self._store = store
        self._event_sink = event_sink or NullEventSink()
        self._model = model
        self._mailbox = mailbox
        self._privacy_config = privacy_config or PrivacyConfig()
        self._lock = Lock()
        self._emitted_notification_keys: set[str] = set()
        self._lease_owner = uuid4().hex

    def sync_startup(
        self,
        *,
        max_messages: int = 200,
        page_size: int = 50,
        initial_window: int = 50,
    ) -> StartupSummary:
        return self.sync(
            trigger="startup",
            max_messages=max_messages,
            page_size=page_size,
            initial_window=initial_window,
        )

    def replay_unacknowledged_startup_summaries(self) -> int:
        replayed = 0
        for summary in self._store.list_unacknowledged_startup_summaries():
            if self._emit_startup_summary(summary):
                replayed += 1
        return replayed

    def sync(
        self,
        *,
        trigger: str,
        max_messages: int = 200,
        page_size: int = 50,
        initial_window: int = 50,
    ) -> StartupSummary:
        if max_messages < 1 or page_size < 1 or initial_window < 1:
            raise ValueError("sync limits must be positive")
        if not self._lock.acquire(blocking=False):
            raise SyncAlreadyRunningError("邮件同步正在进行")
        lease_acquired = False
        try:
            lease_acquired = self._store.acquire_sync_lease(self._lease_owner)
            if not lease_acquired:
                raise SyncAlreadyRunningError("另一个桌面进程正在同步邮件")
            return self._sync_locked(
                trigger=trigger,
                max_messages=max_messages,
                page_size=min(page_size, max_messages),
                initial_window=initial_window,
            )
        finally:
            if lease_acquired:
                self._store.release_sync_lease(self._lease_owner)
            self._lock.release()

    def _sync_locked(
        self,
        *,
        trigger: str,
        max_messages: int,
        page_size: int,
        initial_window: int,
    ) -> StartupSummary:
        state = self._store.get_sync_state(self._mailbox)
        expected_uidvalidity = state.uid_validity if state else None
        cursor = state.last_processed_uid if state else None
        total_fetched = 0
        new_count = 0
        processed_count = 0
        important_count = 0
        urgent_count = 0
        reply_count = 0
        draft_ready_count = 0
        general_count = 0
        items: list[StartupSummaryItem] = []
        failures: list[StartupSummaryFailure] = []
        has_more = False
        retried_incomplete = False
        replayed_notification_outbox = False
        replayed_attention_outbox = False
        retried_quarantined_fetches = False

        def collect(insight: StoredMailInsight, *, analyzed_now: bool) -> None:
            nonlocal processed_count, important_count, urgent_count
            nonlocal reply_count, draft_ready_count, general_count
            if analyzed_now:
                processed_count += 1
            items.append(_item_from_insight(insight))
            if insight.analysis_status != "analyzed":
                return
            if insight.confidence >= 0.55:
                if insight.importance == "important":
                    important_count += 1
                elif insight.importance == "urgent":
                    urgent_count += 1
                else:
                    general_count += 1
            if insight.needs_reply:
                reply_count += 1
            if insight.reply_status == "draft_ready":
                draft_ready_count += 1

        while total_fetched < max_messages:
            if not self._store.acquire_sync_lease(self._lease_owner):
                raise SyncAlreadyRunningError("邮件同步租约已丢失")
            batch = self._client.fetch_incremental(
                mailbox=self._mailbox,
                expected_uid_validity=expected_uidvalidity,
                last_processed_uid=cursor,
                limit=min(page_size, max_messages - total_fetched),
                initial_window=initial_window,
            )
            if expected_uidvalidity != batch.uid_validity:
                expected_uidvalidity = batch.uid_validity
                cursor = None

            if not replayed_notification_outbox:
                replayed_notification_outbox = True
                for pending_notification in self._store.list_notification_outbox(
                    uid_validity=batch.uid_validity,
                    mailbox=self._mailbox,
                    include_emitted=trigger in {"startup", "manual"},
                ):
                    self._emit_important(
                        pending_notification,
                        source=trigger,
                    )

            if not replayed_attention_outbox:
                replayed_attention_outbox = True
                for pending_attention in self._store.list_attention_outbox(
                    uid_validity=batch.uid_validity,
                    mailbox=self._mailbox,
                ):
                    self._emit_attention_required(
                        pending_attention,
                        analysis_failed=pending_attention.analysis_status == "failed",
                        low_confidence=(
                            pending_attention.analysis_status == "analyzed"
                            and pending_attention.confidence < 0.55
                        ),
                        source=trigger,
                    )
                for fetch_attention in self._store.list_quarantined_fetch_failures(
                    uid_validity=batch.uid_validity,
                    mailbox=self._mailbox,
                    attention_statuses=("pending", "failed"),
                ):
                    self._emit_fetch_attention(fetch_attention, source=trigger)

            if not retried_quarantined_fetches and trigger in {"startup", "manual"}:
                retried_quarantined_fetches = True
                quarantined = self._store.list_quarantined_fetch_failures(
                    uid_validity=batch.uid_validity,
                    mailbox=self._mailbox,
                )
                retry_fetcher = getattr(self._client, "fetch_specific_uids", None)
                if quarantined and callable(retry_fetcher):
                    retry_batch = retry_fetcher(
                        [failure.uid for failure in quarantined],
                        mailbox=self._mailbox,
                        expected_uid_validity=batch.uid_validity,
                    )
                    for retry_message in retry_batch.messages:
                        retry_uid = _numeric_uid(retry_message.id)
                        if retry_uid is None:
                            continue
                        self._store.resolve_fetch_failure(
                            self._mailbox,
                            uid_validity=batch.uid_validity,
                            uid=retry_uid,
                        )
                        retry_existing = self._store.get_mail_insight(
                            retry_message.id,
                            uid_validity=batch.uid_validity,
                            mailbox=self._mailbox,
                        )
                        recovered, analyzed_now, retry_failures = self._process_message(
                            retry_message,
                            uid_validity=batch.uid_validity,
                            existing=retry_existing,
                            trigger=trigger,
                        )
                        failures.extend(retry_failures)
                        if recovered is not None:
                            collect(recovered, analyzed_now=analyzed_now)
                    for retry_uid in retry_batch.failed_uids:
                        retry_state = self._store.record_fetch_failure(
                            self._mailbox,
                            uid_validity=batch.uid_validity,
                            uid=retry_uid,
                        )
                        failures.append(
                            StartupSummaryFailure(
                                uid=f"uid:{retry_uid}",
                                stage="quarantine_retry",
                                error="RuntimeError: 隔离邮件仍无法读取，将在后续启动重试",
                            )
                        )
                        if retry_state.attention_status != "emitted":
                            self._emit_fetch_attention(retry_state, source=trigger)

            if not retried_incomplete and trigger in {"startup", "manual"}:
                retried_incomplete = True
                getter = getattr(self._client, "get_real_message", None)
                if callable(getter):
                    for stale in self._store.list_retryable_mail_insights(
                        uid_validity=batch.uid_validity,
                        mailbox=self._mailbox,
                    ):
                        try:
                            retry_message = getter(stale.uid)
                        except Exception as error:
                            failures.append(_failure(stale.uid, "retry_fetch", error))
                            continue
                        if retry_message is None:
                            failures.append(
                                StartupSummaryFailure(
                                    uid=stale.uid,
                                    stage="retry_fetch",
                                    error="RuntimeError: 待重试邮件已无法读取，请人工查看",
                                )
                            )
                            continue
                        retried, analyzed_now, retry_failures = self._process_message(
                            retry_message,
                            uid_validity=batch.uid_validity,
                            existing=stale,
                            trigger=trigger,
                        )
                        failures.extend(retry_failures)
                        if retried is not None:
                            collect(retried, analyzed_now=analyzed_now)

            blocking_failed_uids: list[int] = []
            quarantined_failed_uids: list[int] = []
            for failed_uid in batch.failed_uids:
                new_count += 1
                failure_state = self._store.record_fetch_failure(
                    self._mailbox,
                    uid_validity=batch.uid_validity,
                    uid=failed_uid,
                )
                if failure_state.quarantined:
                    quarantined_failed_uids.append(failed_uid)
                    if failure_state.attention_status != "emitted":
                        self._emit_fetch_attention(failure_state, source=trigger)
                else:
                    blocking_failed_uids.append(failed_uid)
                failures.append(
                    StartupSummaryFailure(
                        uid=f"uid:{failed_uid}",
                        stage="fetch",
                        error=(
                            "RuntimeError: 本封邮件连续读取失败，已隔离等待人工查看"
                            if failure_state.quarantined
                            else "RuntimeError: 本封邮件读取失败，将从当前游标重试"
                        ),
                    )
                )
            blocked_uid = min(blocking_failed_uids) if blocking_failed_uids else None

            if not batch.messages:
                advanceable_failures = [
                    uid
                    for uid in quarantined_failed_uids
                    if blocked_uid is None or uid < blocked_uid
                ]
                if advanceable_failures:
                    self._store.save_sync_state(
                        self._mailbox,
                        uid_validity=batch.uid_validity,
                        last_processed_uid=max([cursor or 0, *advanceable_failures]),
                    )
                elif state is None or state.uid_validity != batch.uid_validity:
                    self._store.save_sync_state(
                        self._mailbox,
                        uid_validity=batch.uid_validity,
                        last_processed_uid=cursor or 0,
                    )
                else:
                    self._store.touch_sync_state(self._mailbox)
                has_more = batch.has_more or bool(blocking_failed_uids)
                break

            for message in batch.messages:
                total_fetched += 1
                numeric_uid = _numeric_uid(message.id)
                if numeric_uid is None:
                    failures.append(_failure(message.id, "sync", ValueError("invalid uid")))
                    continue
                self._store.resolve_fetch_failure(
                    self._mailbox,
                    uid_validity=batch.uid_validity,
                    uid=numeric_uid,
                )

                existing = self._store.get_mail_insight(
                    message.id,
                    uid_validity=batch.uid_validity,
                    mailbox=self._mailbox,
                )
                complete = existing is not None and (
                    _processing_complete(existing) or _privacy_review_recorded(existing)
                )
                if complete and existing is not None and _requires_privacy_reclassification(
                    message,
                    existing,
                    self._privacy_config,
                ):
                    complete = False
                if not complete:
                    new_count += 1
                    insight, analyzed_now, item_failures = self._process_message(
                        message,
                        uid_validity=batch.uid_validity,
                        existing=existing,
                        trigger=trigger,
                    )
                    failures.extend(item_failures)
                    if insight is not None:
                        collect(insight, analyzed_now=analyzed_now)
                if blocked_uid is None or numeric_uid < blocked_uid:
                    self._store.save_sync_state(
                        self._mailbox,
                        uid_validity=batch.uid_validity,
                        last_processed_uid=numeric_uid,
                    )
                    cursor = numeric_uid

            advanceable_failures = [
                uid
                for uid in quarantined_failed_uids
                if blocked_uid is None or uid < blocked_uid
            ]
            if advanceable_failures:
                saved = self._store.save_sync_state(
                    self._mailbox,
                    uid_validity=batch.uid_validity,
                    last_processed_uid=max([cursor or 0, *advanceable_failures]),
                )
                cursor = saved.last_processed_uid

            has_more = batch.has_more or bool(blocking_failed_uids)
            if blocked_uid is not None or not batch.has_more or total_fetched >= max_messages:
                break

        summary = StartupSummary(
            trigger=trigger,
            generated_at=datetime.now(timezone.utc).isoformat(),
            new_count=new_count,
            processed_count=processed_count,
            important_count=important_count,
            urgent_count=urgent_count,
            reply_count=reply_count,
            draft_ready_count=draft_ready_count,
            general_count=general_count,
            failed_count=len(failures),
            has_more=has_more,
            items=tuple(items),
            failures=tuple(failures),
        )
        payload = summary.to_payload()
        if trigger == "startup":
            stored_summary = self._store.save_startup_summary(payload)
            self._emit_startup_summary(stored_summary)
        else:
            self._event_sink.emit("sync_summary", payload)
        return summary

    def _emit_startup_summary(self, summary: StoredStartupSummary) -> bool:
        payload = {
            **summary.payload,
            "id": summary.id,
            "created_at": summary.created_at,
        }
        try:
            self._event_sink.emit("startup_summary", payload)
        except Exception:
            self._store.mark_startup_summary_delivery(summary.id, "failed")
            return False
        return True

    def _process_message(
        self,
        message: MailMessage,
        *,
        uid_validity: int,
        existing: StoredMailInsight | None,
        trigger: str,
    ) -> tuple[StoredMailInsight | None, bool, list[StartupSummaryFailure]]:
        if not self._store.acquire_sync_lease(self._lease_owner):
            raise SyncAlreadyRunningError("邮件同步租约已丢失")
        failures: list[StartupSummaryFailure] = []
        analyzed_now = False
        privacy_verdict = should_block_ai(message, self._privacy_config)
        if privacy_verdict.sensitive:
            insight = self._record_privacy_review(
                message,
                uid_validity=uid_validity,
                verdict=privacy_verdict,
                trigger=trigger,
            )
            return (
                insight,
                False,
                [
                    StartupSummaryFailure(
                        uid=message.id,
                        stage="privacy",
                        error="PrivacyProtected: 隐私保护模式已阻止本封邮件发送给 DeepSeek",
                    )
                ],
            )
        body_over_limit = len(message.body) > self._MAX_AI_BODY_CHARS
        if message.content_truncated or body_over_limit:
            limit_reason = (
                "邮件体积超过自动下载上限"
                if message.content_truncated
                else "邮件正文超过自动分析字符上限"
            )
            self._store.record_analysis_review_required(
                message,
                uid_validity=uid_validity,
                mailbox=self._mailbox,
                summary_zh=f"{limit_reason}，未发送给模型。",
                reason="为控制内存、模型成本和截断误判风险，需要人工打开查看。",
                error_code="message_too_large" if message.content_truncated else "body_too_long",
            )
            insight = self._store.get_mail_insight(
                message.id,
                uid_validity=uid_validity,
                mailbox=self._mailbox,
            )
            assert insight is not None
            self._emit_attention_required(insight, source=trigger)
            return (
                insight,
                False,
                [
                    StartupSummaryFailure(
                        uid=message.id,
                        stage="oversized",
                        error=f"MessageTooLarge: {limit_reason}，已转人工查看",
                    )
                ],
            )
        if existing is None or existing.analysis_status != "analyzed":
            self._store.record_analysis_started(
                message,
                uid_validity=uid_validity,
                mailbox=self._mailbox,
            )
            try:
                result = self._agent.triage(message)
                self._store.save_triage(
                    message,
                    result,
                    model=self._model,
                    uid_validity=uid_validity,
                    mailbox=self._mailbox,
                )
                analyzed_now = True
            except Exception as error:
                self._store.record_analysis_failure(
                    message,
                    uid_validity=uid_validity,
                    mailbox=self._mailbox,
                    error=error,
                )
                failures.append(_failure(message.id, "analysis", error))
                insight = self._store.get_mail_insight(
                    message.id,
                    uid_validity=uid_validity,
                    mailbox=self._mailbox,
                )
                assert insight is not None
                self._emit_attention_required(
                    insight,
                    analysis_failed=True,
                    source=trigger,
                )
                return insight, False, failures

        insight = self._store.get_mail_insight(
            message.id,
            uid_validity=uid_validity,
            mailbox=self._mailbox,
        )
        assert insight is not None

        if insight.confidence < 0.55:
            if insight.notification_status not in {"notified", "attention_emitted"}:
                self._store.set_notification_status(
                    insight.uid,
                    "attention_pending",
                    uid_validity=uid_validity,
                    mailbox=self._mailbox,
                )
                insight = self._store.get_mail_insight(
                    message.id,
                    uid_validity=uid_validity,
                    mailbox=self._mailbox,
                )
                assert insight is not None
                self._emit_attention_required(
                    insight,
                    low_confidence=True,
                    source=trigger,
                )
        elif (
            insight.importance in {"important", "urgent"}
            and insight.notification_status in {"pending", "failed"}
        ):
            self._emit_important(insight, source=trigger)

        if insight.needs_reply and insight.reply_status not in {"draft_ready", "sent"}:
            privacy_verdict = should_block_ai(message, self._privacy_config)
            if privacy_verdict.sensitive:
                insight = self._record_privacy_review(
                    message,
                    uid_validity=uid_validity,
                    verdict=privacy_verdict,
                    trigger=trigger,
                )
                failures.append(
                    StartupSummaryFailure(
                        uid=message.id,
                        stage="privacy",
                        error="PrivacyProtected: 隐私保护模式已阻止本封邮件生成 DeepSeek 草稿",
                    )
                )
                return insight, analyzed_now, failures
            legacy_draft = self._store.get_latest_draft_for_uid(
                message.id,
                uid_validity=0,
                mailbox=self._mailbox,
            )
            if legacy_draft is not None:
                self._store.set_reply_status(
                    message.id,
                    "review_required",
                    uid_validity=uid_validity,
                    mailbox=self._mailbox,
                )
                failures.append(
                    StartupSummaryFailure(
                        uid=message.id,
                        stage="legacy_draft",
                        error="LegacyDraft: 已存在无法验证UIDVALIDITY的旧草稿，未自动重复生成",
                    )
                )
            else:
                try:
                    draft = self._agent.draft_reply(message)
                    stored_draft = DraftService(self._client, self._store).save_generated_draft(  # type: ignore[arg-type]
                        draft,
                        uid_validity=uid_validity,
                        mailbox=self._mailbox,
                    )
                    self._store.set_reply_status(
                        message.id,
                        "draft_ready",
                        uid_validity=uid_validity,
                        mailbox=self._mailbox,
                        draft_id=stored_draft.draft_id,
                    )
                except Exception as error:
                    self._store.set_reply_status(
                        message.id,
                        "review_required",
                        uid_validity=uid_validity,
                        mailbox=self._mailbox,
                    )
                    failures.append(_failure(message.id, "draft", error))

        insight = self._store.get_mail_insight(
            message.id,
            uid_validity=uid_validity,
            mailbox=self._mailbox,
        )
        assert insight is not None
        self._event_sink.emit("mail_processed", _event_payload(insight, source=trigger))
        return (
            self._store.get_mail_insight(
                message.id,
                uid_validity=uid_validity,
                mailbox=self._mailbox,
            ),
            analyzed_now,
            failures,
        )

    def _record_privacy_review(
        self,
        message: MailMessage,
        *,
        uid_validity: int,
        verdict,
        trigger: str,
    ) -> StoredMailInsight:
        summary_zh, reason, error_code = privacy_review_summary(verdict)
        self._store.record_analysis_review_required(
            message,
            uid_validity=uid_validity,
            mailbox=self._mailbox,
            summary_zh=summary_zh,
            reason=reason,
            error_code=error_code,
        )
        insight = self._store.get_mail_insight(
            message.id,
            uid_validity=uid_validity,
            mailbox=self._mailbox,
        )
        assert insight is not None
        self._emit_attention_required(insight, source=trigger)
        return insight

    def _emit_important(
        self,
        insight: StoredMailInsight,
        *,
        source: str,
    ) -> None:
        if insight.notification_status == "notified":
            return
        if insight.notification_status == "failed":
            self._emitted_notification_keys.discard(insight.mail_key)
        if insight.mail_key in self._emitted_notification_keys:
            return
        try:
            self._event_sink.emit(
                "important_mail",
                _event_payload(insight, source=source),
            )
        except Exception:
            self._store.set_notification_status_by_mail_key(insight.mail_key, "failed")
            return
        self._emitted_notification_keys.add(insight.mail_key)

    def _emit_attention_required(
        self,
        insight: StoredMailInsight,
        *,
        analysis_failed: bool = False,
        low_confidence: bool = False,
        source: str,
    ) -> None:
        if insight.notification_status in {"event_emitted", "notified", "attention_emitted"}:
            return
        payload = _event_payload(insight, source=source)
        payload["importance"] = None
        payload["analysis_failed"] = analysis_failed
        payload["low_confidence"] = low_confidence
        try:
            self._event_sink.emit("attention_required", payload)
        except Exception:
            status = "attention_failed"
        else:
            status = "attention_emitted"
        self._store.set_notification_status(
            insight.uid,
            status,
            uid_validity=insight.source_uidvalidity,
            mailbox=insight.mailbox,
        )

    def _emit_fetch_attention(self, failure, *, source: str) -> None:
        try:
            self._event_sink.emit(
                "attention_required",
                {
                    "mail_key": failure.mail_key,
                    "uid": f"uid:{failure.uid}",
                    "sender": None,
                    "subject": None,
                    "importance": None,
                    "needs_reply": None,
                    "summary_zh": "邮件连续读取失败，已隔离并继续处理后续邮件",
                    "action_items": ["请在工作台中人工检查这封邮件"],
                    "confidence": 0.0,
                    "priority_reason": "无法读取邮件内容，未判断重要性",
                    "analysis_status": "failed",
                    "reply_status": "review_required",
                    "notification_status": "attention_pending",
                    "draft_id": None,
                    "analysis_failed": True,
                    "low_confidence": False,
                    "stage": "fetch",
                    "source": source,
                    "trigger": source,
                },
            )
        except Exception:
            status = "failed"
        else:
            status = "emitted"
        self._store.mark_fetch_failure_attention(failure.mail_key, status)


def _numeric_uid(mail_id: str) -> int | None:
    value = mail_id.removeprefix("uid:").strip()
    return int(value) if value.isdigit() else None


def _processing_complete(insight: StoredMailInsight) -> bool:
    if insight.analysis_status != "analyzed":
        return False
    if insight.needs_reply and insight.reply_status not in {"draft_ready", "sent"}:
        return False
    if insight.confidence < 0.55:
        return insight.notification_status in {"attention_emitted", "notified"}
    if insight.importance in {"important", "urgent"} and insight.notification_status not in {
        "notified",
    }:
        return False
    return True


def _privacy_review_recorded(insight: StoredMailInsight) -> bool:
    return (
        insight.analysis_error == "privacy_sensitive"
        and insight.analysis_status == "review_required"
        and insight.reply_status == "review_required"
    )


def _requires_privacy_reclassification(message: MailMessage, insight: StoredMailInsight, config) -> bool:
    if insight.analysis_error == "privacy_sensitive":
        return False
    if insight.analysis_status != "analyzed":
        return False
    return should_block_ai(message, config).sensitive


def _failure(uid: str, stage: str, error: Exception) -> StartupSummaryFailure:
    return StartupSummaryFailure(
        uid=uid,
        stage=stage,
        error=f"{error.__class__.__name__}: 本封邮件{stage}失败，请稍后重试",
    )


def _item_from_insight(insight: StoredMailInsight) -> StartupSummaryItem:
    return StartupSummaryItem(
        uid=insight.uid,
        sender=insight.sender,
        subject=insight.subject,
        importance=insight.importance if insight.analysis_status == "analyzed" else None,
        needs_reply=insight.needs_reply if insight.analysis_status == "analyzed" else None,
        summary_zh=insight.summary_zh,
        priority_reason=insight.priority_reason,
        confidence=insight.confidence,
        analysis_status=insight.analysis_status,
        analysis_error=insight.analysis_error,
        reply_status=insight.reply_status,
        notification_status=insight.notification_status,
        draft_id=insight.draft_id,
    )


def _event_payload(insight: StoredMailInsight, *, source: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "mail_key": insight.mail_key,
        "uid": insight.uid,
        "sender": insight.sender,
        "subject": insight.subject,
        "importance": insight.importance,
        "needs_reply": insight.needs_reply,
        "summary_zh": insight.summary_zh,
        "action_items": list(insight.action_items),
        "confidence": insight.confidence,
        "priority_reason": insight.priority_reason,
        "analysis_status": insight.analysis_status,
        "reply_status": insight.reply_status,
        "notification_status": insight.notification_status,
        "draft_id": insight.draft_id,
        "analysis_failed": insight.analysis_status == "failed",
        "low_confidence": insight.analysis_status == "analyzed" and insight.confidence < 0.55,
    }
    if source is not None:
        payload["source"] = source
        payload["trigger"] = source
    return payload

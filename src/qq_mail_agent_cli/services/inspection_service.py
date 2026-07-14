from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from qq_mail_agent_cli.agent import MailAgent
from qq_mail_agent_cli.mail_client import MailClient
from qq_mail_agent_cli.models import MailMessage, TriageResult
from qq_mail_agent_cli.privacy import PrivacyConfig, privacy_review_summary, should_block_ai
from qq_mail_agent_cli.storage import StateStore, StoredTriage, analysis_error_from_privacy_level, apply_user_label_rule


@dataclass(frozen=True)
class SecretaryInspectionItem:
    uid: str
    sender: str | None
    subject: str | None
    classification: str
    reason: str
    suggested_action: str
    action_reason: str
    queue_status: str
    updated_at: str | None


@dataclass(frozen=True)
class SecretaryInspectionGroup:
    key: str
    title: str
    items: tuple[SecretaryInspectionItem, ...]


@dataclass(frozen=True)
class SecretaryInspectionFailure:
    uid: str
    subject: str
    error: str


@dataclass(frozen=True)
class SecretaryInspectionReport:
    inspected_at: str
    scanned_count: int
    processed_count: int
    skipped_seen: int
    skipped_triaged: int
    failed_count: int
    current_actionable_count: int
    groups: tuple[SecretaryInspectionGroup, ...]
    failures: tuple[SecretaryInspectionFailure, ...]


class SecretaryInspectionService:
    """Build a secretary-style plan without executing mailbox actions."""

    _GROUPS = (
        ("reply", "需要回复"),
        ("review", "需要查看"),
        ("status", "状态处理建议"),
        ("no_action", "无需行动"),
    )
    _QUEUE_REPORT_LIMIT = 100

    def __init__(
        self,
        client: MailClient,
        agent: MailAgent,
        store: StateStore,
        *,
        model: str = "secretary-inspection",
        privacy_config: PrivacyConfig | None = None,
    ):
        self._client = client
        self._agent = agent
        self._store = store
        self._model = model
        self._privacy_config = privacy_config or PrivacyConfig()

    def inspect(self, *, limit: int = 20) -> SecretaryInspectionReport:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        messages = self._client.list_real_recent(limit, offset=0)
        scanned_count = len(messages)
        skipped_seen = 0
        skipped_triaged = 0
        failures: list[SecretaryInspectionFailure] = []
        processed_items: dict[str, SecretaryInspectionItem] = {}

        unread_messages: list[MailMessage] = []
        for message in messages:
            if message.is_seen is True:
                skipped_seen += 1
                self._store.upsert_mail(message)
                continue
            unread_messages.append(message)

        triaged_uids = self._store.get_triaged_uids([message.id for message in unread_messages])
        handled_uids: set[str] = set()
        for message in unread_messages:
            if message.id in triaged_uids or message.id in handled_uids:
                skipped_triaged += 1
                self._store.upsert_mail(message)
                continue

            handled_uids.add(message.id)
            rule = self._store.match_user_label_rule(message)
            if rule is not None:
                result = apply_user_label_rule(MailAgent().classify_title(message), rule)
                self._store.save_triage(
                    message,
                    result,
                    model="user-label-rule",
                    analysis_error=analysis_error_from_privacy_level(rule.privacy_level),
                )
                processed_items[message.id] = _item_from_result(message, result)
                continue
            privacy_verdict = should_block_ai(message, self._privacy_config)
            if privacy_verdict.sensitive:
                summary_zh, reason, error_code = privacy_review_summary(privacy_verdict)
                self._store.record_analysis_review_required(
                    message,
                    uid_validity=0,
                    summary_zh=summary_zh,
                    reason=reason,
                    error_code=error_code,
                )
                failures.append(
                    SecretaryInspectionFailure(
                        uid=message.id,
                        subject=message.subject,
                        error="PrivacyProtected: 隐私保护模式已阻止本封邮件发送给 DeepSeek",
                    )
                )
                continue
            try:
                result = self._agent.triage(message)
                self._store.save_triage(message, result, model=self._model)
                processed_items[message.id] = _item_from_result(message, result)
            except Exception as error:
                failures.append(
                    SecretaryInspectionFailure(
                        uid=message.id,
                        subject=message.subject,
                        error=_safe_error_summary(error),
                    )
                )

        queue_items = [
            _item_from_stored(item)
            for item in self._store.list_suggested_triage_queue(
                self._QUEUE_REPORT_LIMIT,
                statuses=("pending", "later"),
            )
        ]
        merged_items: dict[str, SecretaryInspectionItem] = {}
        for item in (*queue_items, *processed_items.values()):
            merged_items.setdefault(item.uid, item)

        grouped_items: dict[str, list[SecretaryInspectionItem]] = {
            key: [] for key, _ in self._GROUPS
        }
        for item in merged_items.values():
            grouped_items[_group_key(item)].append(item)

        groups = tuple(
            SecretaryInspectionGroup(key=key, title=title, items=tuple(grouped_items[key]))
            for key, title in self._GROUPS
        )
        current_actionable_count = sum(
            len(group.items) for group in groups if group.key != "no_action"
        )
        report = SecretaryInspectionReport(
            inspected_at=datetime.now(timezone.utc).isoformat(),
            scanned_count=scanned_count,
            processed_count=len(processed_items),
            skipped_seen=skipped_seen,
            skipped_triaged=skipped_triaged,
            failed_count=len(failures),
            current_actionable_count=current_actionable_count,
            groups=groups,
            failures=tuple(failures),
        )
        self._log_report_best_effort(report)
        return report

    def _log_report_best_effort(self, report: SecretaryInspectionReport) -> None:
        detail = (
            f"scanned_count={report.scanned_count}, "
            f"processed_count={report.processed_count}, "
            f"skipped_seen={report.skipped_seen}, "
            f"skipped_triaged={report.skipped_triaged}, "
            f"failed_count={report.failed_count}, "
            f"current_actionable_count={report.current_actionable_count}"
        )
        try:
            self._store.log_action("secretary_inspection", uid=None, detail=detail)
        except Exception:
            # The report is still useful when the non-critical audit entry fails.
            pass


def _item_from_stored(item: StoredTriage) -> SecretaryInspectionItem:
    return SecretaryInspectionItem(
        uid=item.uid,
        sender=item.sender,
        subject=item.subject,
        classification=item.classification,
        reason=item.reason,
        suggested_action=item.suggested_action,
        action_reason=item.action_reason,
        queue_status=item.queue_status,
        updated_at=item.updated_at,
    )


def _item_from_result(message: MailMessage, result: TriageResult) -> SecretaryInspectionItem:
    return SecretaryInspectionItem(
        uid=result.mail_id,
        sender=message.sender,
        subject=message.subject,
        classification=result.classification.value,
        reason=result.reason,
        suggested_action=result.suggested_action.value,
        action_reason=result.action_reason,
        queue_status="pending",
        updated_at=None,
    )


def _group_key(item: SecretaryInspectionItem) -> str:
    if item.classification == "respond" or item.suggested_action == "draft_reply":
        return "reply"
    if item.suggested_action in {"mark_seen", "move_to_trash"}:
        return "status"
    if item.suggested_action in {"read_full", "translate"}:
        return "review"
    if item.suggested_action == "no_action" or item.classification == "ignore":
        return "no_action"
    return "review"


def _safe_error_summary(error: Exception) -> str:
    # Model/provider exceptions may echo message content or request payloads.
    return f"{error.__class__.__name__}: 本封邮件分析失败，请稍后重试"

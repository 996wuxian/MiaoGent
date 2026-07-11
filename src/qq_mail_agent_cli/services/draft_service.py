from __future__ import annotations

from uuid import uuid4

from qq_mail_agent_cli.mail_client import MailClient
from qq_mail_agent_cli.models import Draft, DraftSendResult
from qq_mail_agent_cli.storage import StateStore, StoredDraft


class DraftServiceError(RuntimeError):
    pass


class DraftNotFoundError(DraftServiceError):
    pass


class DraftConflictError(DraftServiceError):
    def __init__(self, draft_id: str, status: str):
        self.draft_id = draft_id
        self.status = status
        labels = {
            "sending": "正在发送，不能重复提交",
            "sent": "已经发送，不能重复发送",
            "unknown": "发送结果不确定，已锁定以避免重复投递",
        }
        super().__init__(labels.get(status, f"当前状态 {status} 不允许发送"))


class DraftSendFailedError(DraftServiceError):
    pass


class DraftSendUncertainError(DraftServiceError):
    pass


class DraftService:
    """Small shared boundary for persisted draft versioning and delivery."""

    def __init__(self, client: MailClient, store: StateStore):
        self._client = client
        self._store = store

    def save_generated_draft(
        self,
        draft: Draft,
        *,
        uid_validity: int | None = None,
        mailbox: str = "INBOX",
    ) -> StoredDraft:
        return self._store.save_draft(
            draft,
            uid_validity=uid_validity,
            mailbox=mailbox,
        )

    def get_sendable_draft(self, draft_id: str) -> StoredDraft:
        stored = self._store.get_draft(draft_id)
        if stored is None:
            raise DraftNotFoundError("草稿不存在")
        if stored.send_status not in {"pending", "failed"}:
            raise DraftConflictError(draft_id, stored.send_status)
        return stored

    def send_stored_draft(
        self,
        draft_id: str,
        *,
        dry_run: bool,
        source: str,
    ) -> str | DraftSendResult:
        if dry_run:
            stored = self.get_sendable_draft(draft_id)
            return self._client.send_draft(_to_draft(stored), dry_run=True)

        attempt_id = uuid4().hex
        stored = self._store.claim_draft_for_send(draft_id, attempt_id=attempt_id)
        if stored is None:
            current = self._store.get_draft(draft_id)
            if current is None:
                raise DraftNotFoundError("草稿不存在")
            raise DraftConflictError(draft_id, current.send_status)

        try:
            result = self._client.send_draft(_to_draft(stored), dry_run=False)
        except Exception as error:
            detail = str(error) or error.__class__.__name__
            self._record_unknown(draft_id, attempt_id, stored, source, detail)
            raise DraftSendUncertainError(
                "发送过程发生异常，无法确认邮件是否已投递；草稿已锁定，请人工核对邮箱。"
            ) from error

        if not isinstance(result, DraftSendResult):
            detail = str(result) or "邮件客户端未返回发送结果"
            self._record_failed(draft_id, attempt_id, stored, source, detail)
            raise DraftSendFailedError(detail)

        try:
            completed = self._store.complete_draft_send(
                draft_id,
                attempt_id=attempt_id,
                warning=result.save_error,
            )
            if not completed:
                raise RuntimeError("发送状态已被其他操作改变")
        except Exception as state_error:
            detail = f"SMTP 已完成，但本地发送状态写入失败：{state_error}"
            try:
                self._store.mark_draft_send_unknown(draft_id, attempt_id=attempt_id, error=detail)
            except Exception:
                # Keeping ``sending`` is intentionally fail-closed: a later call
                # still cannot deliver the same draft again.
                pass
            self._log_best_effort("send_draft_unknown", stored, f"{source}: {detail}")
            raise DraftSendUncertainError(
                "邮件可能已经发出，但本地状态保存失败；已阻止再次发送，请人工核对邮箱。"
            ) from state_error

        action = "send_draft" if result.saved_to_sent else "send_draft_sent_copy_failed"
        self._log_best_effort(action, stored, f"{source}: {result.summary()}")
        return result

    def _record_unknown(
        self,
        draft_id: str,
        attempt_id: str,
        stored: StoredDraft,
        source: str,
        detail: str,
    ) -> None:
        try:
            transitioned = self._store.mark_draft_send_unknown(draft_id, attempt_id=attempt_id, error=detail)
        except Exception as state_error:
            raise DraftSendUncertainError(
                "发送结果不确定，且本地状态更新失败；草稿将保持占用状态，请人工核对邮箱。"
            ) from state_error
        if not transitioned:
            raise DraftSendUncertainError(
                "发送结果不确定，且未能确认本地锁定状态；请人工核对邮箱。"
            )
        self._log_best_effort("send_draft_unknown", stored, f"{source}: {detail}")

    def _record_failed(
        self,
        draft_id: str,
        attempt_id: str,
        stored: StoredDraft,
        source: str,
        detail: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        try:
            transitioned = self._store.fail_draft_send(draft_id, attempt_id=attempt_id, error=detail)
        except Exception as state_error:
            raise DraftSendUncertainError(
                "发送调用失败，但本地状态更新也失败；草稿将保持占用状态，请先核对后再处理。"
            ) from state_error
        if not transitioned:
            raise DraftSendUncertainError(
                "发送调用失败，但未能确认本地失败状态；草稿已锁定，请先核对后再处理。"
            ) from cause
        self._log_best_effort("send_draft_failed", stored, f"{source}: {detail}")

    def _log_best_effort(self, action: str, draft: StoredDraft, detail: str) -> None:
        try:
            self._store.log_action(action, uid=draft.uid, detail=detail)
        except Exception:
            # Delivery state is the source of truth. A logging failure must not
            # turn a completed SMTP operation into a retryable send.
            pass


def _to_draft(stored: StoredDraft) -> Draft:
    return Draft(
        id=stored.draft_id,
        mail_id=stored.uid,
        to=stored.to_addr,
        subject=stored.subject,
        body=stored.body,
        reply_to_message_id=stored.reply_to_message_id,
        references=stored.references,
    )

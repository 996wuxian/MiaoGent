from dataclasses import dataclass
from enum import StrEnum


class MailClassification(StrEnum):
    IGNORE = "ignore"
    NOTIFY = "notify"
    RESPOND = "respond"


class MailImportance(StrEnum):
    GENERAL = "general"
    IMPORTANT = "important"
    URGENT = "urgent"


class SuggestedAction(StrEnum):
    READ_FULL = "read_full"
    TRANSLATE = "translate"
    DRAFT_REPLY = "draft_reply"
    MARK_SEEN = "mark_seen"
    MOVE_TO_TRASH = "move_to_trash"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class MailMessage:
    id: str
    sender: str
    recipient: str
    subject: str
    body: str
    date: str | None = None
    snippet: str = ""
    html_body: str = ""
    remote_images: tuple[str, ...] = ()
    inline_images: tuple[str, ...] = ()
    attachments: tuple["MailAttachment", ...] = ()
    is_seen: bool | None = None
    message_id: str = ""
    references: str = ""
    size_bytes: int | None = None
    content_truncated: bool = False


@dataclass(frozen=True)
class MailAttachment:
    filename: str
    content_type: str
    size: int | None = None


@dataclass(frozen=True)
class TriageResult:
    mail_id: str
    classification: MailClassification
    reason: str
    suggested_action: SuggestedAction = SuggestedAction.READ_FULL
    action_reason: str = ""
    importance: MailImportance = MailImportance.GENERAL
    needs_reply: bool = False
    summary_zh: str = ""
    action_items: tuple[str, ...] = ()
    confidence: float = 0.5
    priority_reason: str = ""


@dataclass(frozen=True)
class MailSummary:
    mail_id: str
    summary_zh: str
    action_items: tuple[str, ...] = ()
    confidence: float = 0.5
    reason: str = ""


@dataclass(frozen=True)
class Draft:
    id: str
    mail_id: str
    to: str
    subject: str
    body: str
    reply_to_message_id: str = ""
    references: str = ""


@dataclass(frozen=True)
class MailTranslation:
    mail_id: str
    subject_zh: str
    body_zh: str


@dataclass(frozen=True)
class DraftSendResult:
    draft_id: str
    to: str
    saved_to_sent: bool
    sent_mailbox: str | None = None
    save_error: str | None = None

    def summary(self) -> str:
        if self.saved_to_sent and self.sent_mailbox:
            return f"Sent draft {self.draft_id} to {self.to}; saved to {self.sent_mailbox}"
        if self.save_error:
            return f"Sent draft {self.draft_id} to {self.to}; failed to save sent copy: {self.save_error}"
        return f"Sent draft {self.draft_id} to {self.to}"

    def __str__(self) -> str:
        return self.summary()

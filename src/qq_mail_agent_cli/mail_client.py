from email import policy
from email.message import EmailMessage
from email.header import decode_header, make_header
from email.message import Message
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import imaplib
import re
import smtplib
import time

from qq_mail_agent_cli.config import MailConfig
from qq_mail_agent_cli.models import Draft, DraftSendResult, MailAttachment, MailMessage


@dataclass(frozen=True)
class IncrementalMailBatch:
    uid_validity: int
    messages: tuple[MailMessage, ...]
    has_more: bool
    cursor_reset: bool = False
    failed_uids: tuple[int, ...] = ()


@dataclass(frozen=True)
class MailReadFailure:
    mail_id: str
    stage: str
    code: str
    error: str


@dataclass(frozen=True)
class MailReadBatch:
    messages: tuple[MailMessage, ...]
    failures: tuple[MailReadFailure, ...] = ()


class MailClient:
    """Mail protocol boundary for mock data, IMAP, and SMTP."""

    def __init__(self, config: MailConfig):
        self._config = config

    def list_recent(self, limit: int) -> list[MailMessage]:
        messages = [
            MailMessage(
                id="mock-1",
                sender="alice@example.com",
                recipient=self._config.address or "you@qq.com",
                subject="API design discussion",
                body="Can we meet next Tuesday to discuss the API design?",
            ),
            MailMessage(
                id="mock-2",
                sender="newsletter@example.com",
                recipient=self._config.address or "you@qq.com",
                subject="Weekly product newsletter",
                body="Here are this week's product updates and promotional links.",
            ),
            MailMessage(
                id="mock-3",
                sender="ops@example.com",
                recipient=self._config.address or "you@qq.com",
                subject="Deployment completed",
                body="The scheduled deployment completed successfully at 10:30.",
            ),
        ]
        return messages[:limit]

    def list_real_recent(self, limit: int, *, offset: int = 0) -> list[MailMessage]:
        return list(self.list_real_recent_batch(limit, offset=offset).messages)

    def list_real_recent_batch(self, limit: int, *, offset: int = 0) -> MailReadBatch:
        self._require_mail_credentials()
        with self._connect_imap() as imap:
            status, _ = imap.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError("Unable to select mailbox: INBOX")
            status, data = imap.uid("search", None, "ALL")
            if status != "OK":
                raise RuntimeError("IMAP recent message search failed.")
            if not data or not data[0]:
                return MailReadBatch(messages=())
            uids = data[0].split()
            newest_first = list(reversed(uids))
            selected_uids = newest_first[offset : offset + limit]
            messages: list[MailMessage] = []
            failures: list[MailReadFailure] = []
            for uid in selected_uids:
                mail_id = f"uid:{uid.decode('ascii', errors='replace')}"
                try:
                    message = self._fetch_uid_header(imap, uid)
                except (imaplib.IMAP4.error, OSError, TimeoutError, ConnectionError):
                    message = None
                except Exception:
                    message = None
                if message is not None:
                    messages.append(message)
                else:
                    failures.append(
                        MailReadFailure(
                            mail_id=mail_id,
                            stage="header",
                            code="header_unavailable",
                            error="邮件标题读取失败，请稍后重试或人工查看。",
                        )
                    )
            return MailReadBatch(messages=tuple(messages), failures=tuple(failures))

    def fetch_real_messages(self, mail_ids: list[str]) -> MailReadBatch:
        """Fetch complete messages for AI processing with a bounded MIME size."""
        requested: list[tuple[int, str, bytes]] = []
        ordered_failures: list[tuple[int, MailReadFailure]] = []
        seen: set[str] = set()
        for index, mail_id in enumerate(mail_ids):
            uid = _normalize_uid(mail_id)
            if uid is None:
                ordered_failures.append(
                    (
                        index,
                        MailReadFailure(
                            mail_id=mail_id,
                            stage="content",
                            code="invalid_uid",
                            error="邮件 UID 无效，无法读取正文。",
                        ),
                    )
                )
                continue
            canonical_id = f"uid:{uid}"
            if canonical_id in seen:
                continue
            seen.add(canonical_id)
            requested.append((index, canonical_id, uid.encode("ascii")))

        if not requested:
            return MailReadBatch(
                messages=(),
                failures=tuple(
                    failure
                    for _, failure in sorted(ordered_failures, key=lambda item: item[0])
                ),
            )

        self._require_mail_credentials()
        messages: list[MailMessage] = []
        with self._connect_imap() as imap:
            status, _ = imap.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError("Unable to select mailbox: INBOX")
            for index, canonical_id, uid in requested:
                try:
                    message = self._fetch_incremental_uid(imap, uid)
                except (imaplib.IMAP4.error, OSError, TimeoutError, ConnectionError):
                    message = None
                except Exception:
                    message = None
                if message is None:
                    ordered_failures.append(
                        (
                            index,
                            MailReadFailure(
                                mail_id=canonical_id,
                                stage="content",
                                code="content_unavailable",
                                error="邮件正文读取失败，请稍后重试或人工查看。",
                            ),
                        )
                    )
                    continue
                if message.content_truncated:
                    ordered_failures.append(
                        (
                            index,
                            MailReadFailure(
                                mail_id=canonical_id,
                                stage="content",
                                code="content_too_large",
                                error="邮件体积超过自动分析上限，请人工查看。",
                            ),
                        )
                    )
                    continue
                if not message.body.strip():
                    ordered_failures.append(
                        (
                            index,
                            MailReadFailure(
                                mail_id=canonical_id,
                                stage="content",
                                code="content_empty",
                                error="邮件正文为空或无法解析，请人工查看。",
                            ),
                        )
                    )
                    continue
                messages.append(message)
        return MailReadBatch(
            messages=tuple(messages),
            failures=tuple(
                failure
                for _, failure in sorted(ordered_failures, key=lambda item: item[0])
            ),
        )

    def fetch_incremental(
        self,
        *,
        mailbox: str = "INBOX",
        expected_uid_validity: int | None,
        last_processed_uid: int | None,
        limit: int = 50,
        initial_window: int = 50,
    ) -> IncrementalMailBatch:
        """Fetch an ascending UID page without coupling progress to ``\\Seen``.

        A changed UIDVALIDITY starts a bounded new baseline instead of trusting
        a cursor from a different mailbox generation.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        if initial_window < 1:
            raise ValueError("initial_window must be positive")

        self._require_mail_credentials()
        with self._connect_imap() as imap:
            status, _ = imap.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to select mailbox: {mailbox}")
            uid_validity = _read_uidvalidity(imap, mailbox)
            cursor_reset = expected_uid_validity is not None and expected_uid_validity != uid_validity

            if last_processed_uid is None or expected_uid_validity != uid_validity:
                status, data = imap.uid("search", None, "ALL")
                raw_uids = _parse_search_uids(status, data)
                candidate_uids = raw_uids[-initial_window:]
            else:
                start_uid = max(1, last_processed_uid + 1)
                status, data = imap.uid("search", None, "UID", f"{start_uid}:*")
                raw_uids = _parse_search_uids(status, data)
                candidate_uids = [uid for uid in raw_uids if int(uid) > last_processed_uid]

            selected_uids = candidate_uids[:limit]
            messages: list[MailMessage] = []
            failed_uids: list[int] = []
            for uid in selected_uids:
                try:
                    message = self._fetch_incremental_uid(imap, uid)
                except (imaplib.IMAP4.error, OSError, TimeoutError, ConnectionError) as error:
                    raise RuntimeError("IMAP connection failed during incremental fetch; sync will retry.") from error
                except Exception:
                    message = None
                if message is not None:
                    messages.append(message)
                else:
                    failed_uids.append(int(uid))
            return IncrementalMailBatch(
                uid_validity=uid_validity,
                messages=tuple(messages),
                has_more=len(candidate_uids) > len(selected_uids),
                cursor_reset=cursor_reset,
                failed_uids=tuple(failed_uids),
            )

    def fetch_specific_uids(
        self,
        uids: list[int],
        *,
        mailbox: str = "INBOX",
        expected_uid_validity: int,
    ) -> IncrementalMailBatch:
        unique_uids = sorted(set(uid for uid in uids if uid > 0))
        if not unique_uids:
            return IncrementalMailBatch(
                uid_validity=expected_uid_validity,
                messages=(),
                has_more=False,
            )
        self._require_mail_credentials()
        with self._connect_imap() as imap:
            status, _ = imap.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to select mailbox: {mailbox}")
            uid_validity = _read_uidvalidity(imap, mailbox)
            if uid_validity != expected_uid_validity:
                raise RuntimeError("Mailbox UIDVALIDITY changed while retrying quarantined mail.")
            messages: list[MailMessage] = []
            failed_uids: list[int] = []
            for numeric_uid in unique_uids:
                try:
                    message = self._fetch_incremental_uid(imap, str(numeric_uid).encode("ascii"))
                except (imaplib.IMAP4.error, OSError, TimeoutError, ConnectionError) as error:
                    raise RuntimeError("IMAP connection failed during quarantined fetch retry.") from error
                except Exception:
                    message = None
                if message is None:
                    failed_uids.append(numeric_uid)
                else:
                    messages.append(message)
            return IncrementalMailBatch(
                uid_validity=uid_validity,
                messages=tuple(messages),
                has_more=False,
                failed_uids=tuple(failed_uids),
            )

    def get_real_message(self, mail_id: str) -> MailMessage | None:
        self._require_mail_credentials()
        uid = _normalize_uid(mail_id)
        if uid is None:
            return None
        with self._connect_imap() as imap:
            imap.select("INBOX", readonly=True)
            return self._fetch_uid(imap, uid.encode("ascii"))

    def mark_real_seen(self, mail_id: str) -> bool:
        self._require_mail_credentials()
        uid = _normalize_uid(mail_id)
        if uid is None:
            return False
        with self._connect_imap() as imap:
            imap.select("INBOX", readonly=False)
            status, _ = imap.uid("store", uid.encode("ascii"), "+FLAGS.SILENT", r"(\Seen)")
            return status == "OK"

    def list_mailboxes(self) -> list[str]:
        self._require_mail_credentials()
        with self._connect_imap() as imap:
            return self._list_mailboxes_with_connection(imap)

    def move_real_to_trash(self, mail_ids: list[str]) -> str:
        self._require_mail_credentials()
        uids = _normalize_uids(mail_ids)
        if not uids:
            raise RuntimeError("No valid mail uid provided.")
        with self._connect_imap() as imap:
            mailboxes = self._list_mailboxes_with_connection(imap)
            trash = _find_trash_mailbox(mailboxes)
            if trash is None:
                available = ", ".join(mailboxes) or "(none)"
                raise RuntimeError(f"Trash mailbox not found. Available mailboxes: {available}")
            imap.select("INBOX", readonly=False)
            uid_set = ",".join(uids)
            status, data = imap.uid("MOVE", uid_set, _quote_mailbox(trash))
            if status != "OK":
                detail = data[0].decode("utf-8", errors="replace") if data else "unknown error"
                raise RuntimeError(f"IMAP MOVE failed: {detail}")
            return trash

    def send_draft(self, draft: Draft, *, dry_run: bool = True) -> str | DraftSendResult:
        if dry_run:
            return f"Dry run: would send draft {draft.id} to {draft.to}"
        self._require_mail_credentials()
        message = self._build_draft_message(draft)
        with smtplib.SMTP_SSL(self._config.smtp_host, self._config.smtp_port, timeout=45) as smtp:
            smtp.login(self._config.address, self._config.auth_code)
            smtp.send_message(message)

        saved, mailbox, error = self._append_to_sent(message)
        return DraftSendResult(
            draft_id=draft.id,
            to=draft.to,
            saved_to_sent=saved,
            sent_mailbox=mailbox,
            save_error=error,
        )

    def _build_draft_message(self, draft: Draft) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._config.address
        message["To"] = draft.to
        message["Subject"] = draft.subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid()
        if draft.reply_to_message_id:
            message["In-Reply-To"] = draft.reply_to_message_id
            references = _build_references_header(draft.references, draft.reply_to_message_id)
            if references:
                message["References"] = references
        message.set_content(draft.body)
        return message

    def _append_to_sent(self, message: EmailMessage) -> tuple[bool, str | None, str | None]:
        try:
            with self._connect_imap() as imap:
                mailboxes = self._list_mailboxes_with_connection(imap)
                sent_mailbox = _find_sent_mailbox(mailboxes)
                if sent_mailbox is None:
                    available = ", ".join(mailboxes) or "(none)"
                    return False, None, f"sent mailbox not found. Available mailboxes: {available}"
                status, data = imap.append(
                    _quote_mailbox(sent_mailbox),
                    None,
                    imaplib.Time2Internaldate(time.time()),
                    message.as_bytes(),
                )
                if status != "OK":
                    detail = data[0].decode("utf-8", errors="replace") if data else "unknown error"
                    return False, sent_mailbox, f"IMAP APPEND failed: {detail}"
                return True, sent_mailbox, None
        except Exception as error:
            return False, None, str(error)

    def _require_mail_credentials(self) -> None:
        missing = []
        if not self._config.address:
            missing.append("mail address")
        if not self._config.auth_code:
            missing.append("mail authorization code")
        if missing:
            raise RuntimeError(f"Missing required mail config: {', '.join(missing)}")

    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        try:
            imap = imaplib.IMAP4_SSL(
                self._config.imap_host,
                self._config.imap_port,
                timeout=self._config.timeout_seconds,
            )
            imap.login(self._config.address, self._config.auth_code)
            _send_imap_client_id_if_needed(imap, self._config.imap_host)
            return imap
        except imaplib.IMAP4.error as error:
            raise RuntimeError(
                "Mail IMAP login failed. Check mail address, authorization code, "
                "and whether IMAP/SMTP service is enabled for this mailbox."
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Mail IMAP connection failed. Check IMAP host, IMAP port, "
                "and current network or DNS availability."
            ) from error

    def _list_mailboxes_with_connection(self, imap: imaplib.IMAP4_SSL) -> list[str]:
        status, data = imap.list()
        if status != "OK":
            return []
        mailboxes = []
        for item in data or []:
            if not isinstance(item, bytes):
                continue
            parsed = _parse_mailbox_name(item)
            if parsed:
                mailboxes.append(parsed)
        return mailboxes

    def _fetch_uid(self, imap: imaplib.IMAP4_SSL, uid: bytes) -> MailMessage | None:
        status, data = imap.uid("fetch", uid, "(FLAGS BODY.PEEK[])")
        if status != "OK":
            return None
        raw_message = _extract_raw_message(data)
        if raw_message is None:
            return None
        is_seen = _extract_seen_flag(data)
        parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
        plain_body, html_body = _extract_bodies(parsed)
        display_body = _display_text(plain_body, html_body)
        return MailMessage(
            id=f"uid:{uid.decode('ascii', errors='replace')}",
            sender=_decode_header_value(parsed.get("From", "")),
            recipient=_decode_header_value(parsed.get("To", "")),
            subject=_decode_header_value(parsed.get("Subject", "(no subject)")),
            body=display_body,
            date=_decode_header_value(parsed.get("Date", "")) or None,
            snippet=_make_snippet(display_body),
            html_body=html_body,
            remote_images=tuple(_extract_remote_images(html_body)),
            inline_images=tuple(_extract_inline_images(parsed)),
            attachments=tuple(_extract_attachments(parsed)),
            is_seen=is_seen,
            message_id=_decode_header_value(parsed.get("Message-ID", "")),
            references=_decode_header_value(parsed.get("References", "")),
            size_bytes=len(raw_message),
        )

    def _fetch_uid_header(self, imap: imaplib.IMAP4_SSL, uid: bytes) -> MailMessage | None:
        status, data = imap.uid("fetch", uid, "(FLAGS RFC822.SIZE BODY.PEEK[HEADER])")
        if status != "OK":
            return None
        raw_headers = _extract_raw_message(data)
        if raw_headers is None:
            return None
        parsed = BytesParser(policy=policy.default).parsebytes(raw_headers)
        return MailMessage(
            id=f"uid:{uid.decode('ascii', errors='replace')}",
            sender=_decode_header_value(parsed.get("From", "")),
            recipient=_decode_header_value(parsed.get("To", "")),
            subject=_decode_header_value(parsed.get("Subject", "(no subject)")),
            body="",
            date=_decode_header_value(parsed.get("Date", "")) or None,
            snippet="邮件正文将在打开后读取。",
            is_seen=_extract_seen_flag(data),
            message_id=_decode_header_value(parsed.get("Message-ID", "")),
            references=_decode_header_value(parsed.get("References", "")),
            size_bytes=_extract_message_size(data),
            content_truncated=True,
        )

    def _fetch_incremental_uid(self, imap: imaplib.IMAP4_SSL, uid: bytes) -> MailMessage | None:
        status, data = imap.uid("fetch", uid, "(FLAGS RFC822.SIZE BODY.PEEK[HEADER])")
        if status != "OK":
            return None
        raw_headers = _extract_raw_message(data)
        if raw_headers is None:
            return None
        size_bytes = _extract_message_size(data)
        if size_bytes is not None and size_bytes > self._config.max_auto_fetch_bytes:
            parsed = BytesParser(policy=policy.default).parsebytes(raw_headers)
            return MailMessage(
                id=f"uid:{uid.decode('ascii', errors='replace')}",
                sender=_decode_header_value(parsed.get("From", "")),
                recipient=_decode_header_value(parsed.get("To", "")),
                subject=_decode_header_value(parsed.get("Subject", "(no subject)")),
                body="",
                date=_decode_header_value(parsed.get("Date", "")) or None,
                snippet="邮件体积过大，未自动下载正文，请人工查看。",
                is_seen=_extract_seen_flag(data),
                message_id=_decode_header_value(parsed.get("Message-ID", "")),
                references=_decode_header_value(parsed.get("References", "")),
                size_bytes=size_bytes,
                content_truncated=True,
            )
        message = self._fetch_uid(imap, uid)
        if message is None:
            return None
        if size_bytes is None:
            return message
        return MailMessage(**{**vars(message), "size_bytes": size_bytes})


def _extract_raw_message(data: list[bytes | tuple]) -> bytes | None:
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _extract_seen_flag(data: list[bytes | tuple]) -> bool | None:
    for item in data:
        if isinstance(item, tuple) and item:
            metadata = item[0]
            if isinstance(metadata, bytes):
                return b"\\Seen" in metadata
    return None


def _extract_message_size(data: list[bytes | tuple]) -> int | None:
    for item in data:
        metadata = item[0] if isinstance(item, tuple) and item else item
        if isinstance(metadata, bytes):
            match = re.search(rb"RFC822\.SIZE\s+(\d+)", metadata, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
    return None


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def _extract_bodies(message: Message) -> tuple[str, str]:
    plain = ""
    html = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disposition:
                continue
            if content_type == "text/plain" and not plain:
                plain = _part_content(part)
            elif content_type == "text/html" and not html:
                html = _part_content(part)
        return plain, html
    if message.get_content_type() == "text/html":
        return "", _part_content(message)
    return _part_content(message), ""


def _extract_text_body(message: Message) -> str:
    plain, html = _extract_bodies(message)
    return _display_text(plain, html)


def _extract_inline_images(message: Message) -> list[str]:
    images = []
    if not message.is_multipart():
        return images
    for part in message.walk():
        content_type = part.get_content_type()
        content_id = part.get("Content-ID")
        disposition = str(part.get("Content-Disposition", "")).lower()
        if content_type.startswith("image/") and content_id and "attachment" not in disposition:
            images.append(f"{content_type} {content_id.strip('<>')}")
    return images


def _extract_attachments(message: Message) -> list[MailAttachment]:
    attachments = []
    if not message.is_multipart():
        return attachments
    for part in message.walk():
        disposition = str(part.get("Content-Disposition", "")).lower()
        filename = part.get_filename()
        if "attachment" not in disposition and not filename:
            continue
        payload = part.get_payload(decode=True)
        size = len(payload) if isinstance(payload, bytes) else None
        attachments.append(
            MailAttachment(
                filename=_decode_header_value(filename or "(unnamed)"),
                content_type=part.get_content_type(),
                size=size,
            )
        )
    return attachments


def _extract_remote_images(html: str) -> list[str]:
    if not html:
        return []
    matches = re.findall(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE)
    return [src for src in matches if src.startswith(("http://", "https://"))]


def _part_content(part: Message) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content.strip()
    except Exception:
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace").strip()
    return ""


def _display_text(plain: str, html: str) -> str:
    if plain:
        return _strip_html(plain) if _looks_like_html(plain) else _normalize_text(plain)
    return _strip_html(html)


def _looks_like_html(value: str) -> bool:
    return bool(re.search(r"<\s*(?:!doctype|html|head|body|div|p|br|table|tr|td|span|a|style|script)\b", value, re.IGNORECASE))


class _TextHTMLParser(HTMLParser):
    _BLOCK_TAGS = {"address", "article", "blockquote", "div", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "p", "pre", "section", "table", "tr"}
    _SKIP_TAGS = {"head", "script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag in {"br", "hr"}:
            self.parts.append("\n")
        elif self.skip_depth == 0 and tag == "li":
            self.parts.append("\n- ")
        elif self.skip_depth == 0 and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif self.skip_depth == 0 and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def _strip_html(value: str) -> str:
    if not value:
        return ""
    parser = _TextHTMLParser()
    try:
        parser.feed(value)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", value)
    return _normalize_text(unescape(text))


def _normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()


def _make_snippet(body: str, limit: int = 120) -> str:
    snippet = " ".join(body.split())
    if len(snippet) <= limit:
        return snippet
    return snippet[: limit - 3] + "..."


def _normalize_uid(mail_id: str) -> str | None:
    uid = mail_id.removeprefix("uid:").strip()
    if not uid.isdigit():
        return None
    return uid


def _read_uidvalidity(imap: imaplib.IMAP4_SSL, mailbox: str) -> int:
    _, data = imap.response("UIDVALIDITY")
    value = _first_integer(data)
    if value is not None:
        return value

    status, status_data = imap.status(mailbox, "(UIDVALIDITY)")
    if status == "OK":
        value = _first_integer(status_data)
    if value is None:
        raise RuntimeError("IMAP server did not return UIDVALIDITY for the selected mailbox.")
    return value


def _first_integer(values: object) -> int | None:
    if not isinstance(values, (list, tuple)):
        values = [values]
    for value in values:
        if isinstance(value, bytes):
            match = re.search(rb"\d+", value)
        elif isinstance(value, str):
            match = re.search(r"\d+", value)
        else:
            continue
        if match:
            matched = match.group(0)
            return int(matched.decode("ascii") if isinstance(matched, bytes) else matched)
    return None


def _parse_search_uids(status: str, data: list[bytes] | tuple[bytes, ...] | None) -> list[bytes]:
    if status != "OK":
        raise RuntimeError("IMAP UID SEARCH failed; incremental sync will retry.")
    if not data or not data[0]:
        return []
    return sorted(
        (uid for uid in data[0].split() if uid.isdigit()),
        key=int,
    )


def _send_imap_client_id_if_needed(imap: imaplib.IMAP4_SSL, host: str) -> None:
    """Send IMAP ID for providers that reject mailbox selection without it.

    NetEase 163 can accept LOGIN but later reject SELECT/EXAMINE with
    "Unsafe Login" unless the client identifies itself first.
    """
    if "163.com" not in host.lower():
        return
    imaplib.Commands.setdefault("ID", ("AUTH", "NONAUTH"))
    status, _ = imap._simple_command(  # type: ignore[attr-defined]
        "ID",
        '("name" "MiaoGent" "version" "1.0" "vendor" "MiaoGent")',
    )
    if status != "OK":
        raise imaplib.IMAP4.error("IMAP ID command failed")


def _normalize_uids(mail_ids: list[str]) -> list[str]:
    normalized = []
    for mail_id in mail_ids:
        uid = _normalize_uid(mail_id)
        if uid is not None:
            normalized.append(uid)
    return normalized


def _find_trash_mailbox(mailboxes: list[str]) -> str | None:
    preferred = ["Trash", "Deleted Messages", "Deleted Items", "已删除", "已删除邮件", "垃圾箱"]
    lower_map = {mailbox.lower(): mailbox for mailbox in mailboxes}
    for name in preferred:
        if name.lower() in lower_map:
            return lower_map[name.lower()]
    for mailbox in mailboxes:
        lowered = mailbox.lower()
        if "trash" in lowered or "deleted" in lowered or "垃圾" in mailbox or "已删除" in mailbox:
            return mailbox
    return None


def _find_sent_mailbox(mailboxes: list[str]) -> str | None:
    preferred = ["Sent Messages", "Sent", "Sent Mail", "已发送", "已发送邮件", "发件箱"]
    lower_map = {mailbox.lower(): mailbox for mailbox in mailboxes}
    for name in preferred:
        if name.lower() in lower_map:
            return lower_map[name.lower()]
    for mailbox in mailboxes:
        lowered = mailbox.lower()
        if "sent" in lowered or "已发送" in mailbox:
            return mailbox
    return None


def _build_references_header(existing_references: str, reply_to_message_id: str) -> str:
    tokens = []
    for value in [existing_references, reply_to_message_id]:
        for token in value.split():
            if token and token not in tokens:
                tokens.append(token)
    return " ".join(tokens)


def _parse_mailbox_name(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    if '"' in text:
        parts = text.rsplit('"', 2)
        if len(parts) >= 2:
            return parts[-2]
    return text.split()[-1].strip('"')


def _quote_mailbox(mailbox: str) -> str:
    escaped = mailbox.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'

from __future__ import annotations

from collections.abc import Callable
import random
import re
from threading import Event
import time
from typing import Any

from qq_mail_agent_cli.config import MailConfig
from qq_mail_agent_cli.desktop_events import EventSink, NullEventSink


class ImapIdleWatcher:
    """Use IMAP IDLE only as a wake-up signal for cursor-based catch-up."""

    def __init__(
        self,
        config: MailConfig,
        on_wakeup: Callable[[], object],
        *,
        event_sink: EventSink | None = None,
        client_factory: Callable[..., Any] | None = None,
        mailbox: str = "INBOX",
        renewal_seconds: float = 90,
        fallback_poll_seconds: float = 90,
        reconnect_min_seconds: float = 2,
        reconnect_max_seconds: float = 60,
    ) -> None:
        self._config = config
        self._on_wakeup = on_wakeup
        self._event_sink = event_sink or NullEventSink()
        self._client_factory = client_factory or _default_client_factory
        self._mailbox = mailbox
        self._renewal_seconds = renewal_seconds
        self._fallback_poll_seconds = fallback_poll_seconds
        self._reconnect_min_seconds = reconnect_min_seconds
        self._reconnect_max_seconds = reconnect_max_seconds

    def run(self, stop_event: Event) -> None:
        backoff = self._reconnect_min_seconds
        while not stop_event.is_set():
            client = None
            connected_at: float | None = None
            try:
                self._require_credentials()
                client = self._client_factory(
                    self._config.imap_host,
                    port=self._config.imap_port,
                    ssl=True,
                    timeout=self._config.timeout_seconds,
                )
                client.login(self._config.address, self._config.auth_code)
                client.select_folder(self._mailbox, readonly=True)
                connected_at = time.monotonic()
                raw_capabilities = client.capabilities() if callable(client.capabilities) else client.capabilities
                capabilities = {_capability_text(value) for value in raw_capabilities}
                self._event_sink.emit(
                    "watcher_status",
                    {"status": "connected", "mode": "idle" if "IDLE" in capabilities else "poll"},
                )

                # Every (re)connection first catches up through the durable UID cursor.
                self._on_wakeup()
                if "IDLE" in capabilities:
                    self._idle_loop(client, stop_event)
                else:
                    self._poll_loop(stop_event)
            except Exception as error:
                if stop_event.is_set():
                    break
                self._event_sink.emit(
                    "watcher_status",
                    {
                        "status": "reconnecting",
                        "mode": "unknown",
                        "error": f"{error.__class__.__name__}: IMAP 监听暂时不可用",
                    },
                )
                jittered = backoff + random.uniform(0, max(0.0, backoff * 0.2))
                stop_event.wait(jittered)
                if connected_at is not None and time.monotonic() - connected_at >= 60:
                    backoff = self._reconnect_min_seconds
                elif backoff == 0:
                    backoff = self._reconnect_min_seconds
                else:
                    backoff = min(self._reconnect_max_seconds, max(self._reconnect_min_seconds, backoff * 2))
            finally:
                if client is not None:
                    try:
                        client.logout()
                    except Exception:
                        pass
        self._event_sink.emit("watcher_status", {"status": "stopped", "mode": "none"})

    def _idle_loop(self, client: Any, stop_event: Event) -> None:
        while not stop_event.is_set():
            client.idle()
            done_result: object = None
            response_signal = False
            tail_signal = False
            try:
                responses = client.idle_check(timeout=self._renewal_seconds)
                response_signal = _has_new_mail_signal(responses)
                if response_signal and not stop_event.is_set():
                    self._event_sink.emit(
                        "watcher_status",
                        {"status": "wakeup", "mode": "idle", "source": "idle_check"},
                    )
                    # Keep the dedicated watcher connection in IDLE while the
                    # short-connection catch-up runs, so later EXISTS signals
                    # remain buffered by the server.
                    self._on_wakeup()
            finally:
                done_result = client.idle_done()
            tail_responses = _idle_done_responses(done_result)
            tail_signal = _has_new_mail_signal(tail_responses)
            if tail_signal:
                self._event_sink.emit(
                    "watcher_status",
                    {"status": "wakeup", "mode": "idle", "source": "idle_done"},
                )
            # Always catch up after leaving each IDLE cycle. This covers renewal
            # timeouts, responses returned only by IDLE DONE, and mail arriving
            # while the first catch-up was running.
            if not stop_event.is_set():
                if not response_signal and not tail_signal:
                    self._event_sink.emit(
                        "watcher_status",
                        {
                            "status": "heartbeat",
                            "mode": "idle",
                            "interval_seconds": self._renewal_seconds,
                        },
                    )
                self._on_wakeup()

    def _poll_loop(self, stop_event: Event) -> None:
        self._event_sink.emit(
            "watcher_status",
            {"status": "degraded", "mode": "poll", "interval_seconds": self._fallback_poll_seconds},
        )
        while not stop_event.wait(self._fallback_poll_seconds):
            self._on_wakeup()

    def _require_credentials(self) -> None:
        if not self._config.address or not self._config.auth_code:
            raise RuntimeError("邮箱地址或授权码未配置")


def _default_client_factory(host: str, *, port: int, ssl: bool, timeout: float):
    try:
        from imapclient import IMAPClient
    except ImportError as error:  # pragma: no cover - packaging dependency guard
        raise RuntimeError("Desktop runtime requires the imapclient package") from error
    return IMAPClient(host, port=port, ssl=ssl, timeout=timeout)


def _capability_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="ignore").upper()
    return str(value).upper()


def _has_new_mail_signal(responses: object) -> bool:
    if isinstance(responses, (list, tuple)):
        return any(_has_new_mail_signal(response) for response in responses)
    text = _capability_text(responses)
    return re.search(r"(^|\s)(EXISTS|RECENT)(\s|$)", text) is not None


def _idle_done_responses(result: object) -> object:
    if isinstance(result, tuple) and len(result) >= 2:
        return result[1]
    return ()

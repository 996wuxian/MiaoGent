from __future__ import annotations

from dataclasses import dataclass
import json
from io import BufferedIOBase
import sys
from threading import Lock
from typing import Any, BinaryIO, Protocol, TextIO


EVENT_PREFIX = "QQMAIL_EVENT "


@dataclass(frozen=True)
class DesktopEvent:
    name: str
    payload: dict[str, Any]


class EventSink(Protocol):
    def emit(self, name: str, payload: dict[str, Any]) -> None: ...


class NullEventSink:
    def emit(self, name: str, payload: dict[str, Any]) -> None:
        return None


class RecordingEventSink:
    """In-memory sink used by deterministic service tests."""

    def __init__(self) -> None:
        self.events: list[DesktopEvent] = []

    def emit(self, name: str, payload: dict[str, Any]) -> None:
        self.events.append(DesktopEvent(name=name, payload=dict(payload)))


class JsonLineEventSink:
    """Write redaction-safe desktop events to sidecar stdout."""

    def __init__(self, *, stream: TextIO | BinaryIO | None = None) -> None:
        selected = stream or sys.stdout
        binary_stream = getattr(selected, "buffer", None)
        if binary_stream is not None:
            self._binary_stream: BinaryIO | None = binary_stream
            self._text_stream: TextIO | None = None
        elif isinstance(selected, BufferedIOBase):
            self._binary_stream = selected
            self._text_stream = None
        else:
            self._binary_stream = None
            self._text_stream = selected  # type: ignore[assignment]
        self._lock = Lock()

    def emit(self, name: str, payload: dict[str, Any]) -> None:
        line = EVENT_PREFIX + json.dumps(
            {"event": name, "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._lock:
            if self._binary_stream is not None:
                self._binary_stream.write((line + "\n").encode("utf-8"))
                self._binary_stream.flush()
            else:
                assert self._text_stream is not None
                self._text_stream.write(line + "\n")
                self._text_stream.flush()

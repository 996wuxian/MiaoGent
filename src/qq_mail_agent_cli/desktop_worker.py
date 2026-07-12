from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import socket
from threading import Event, Thread
import time

from qq_mail_agent_cli.agent import MailAgent
from qq_mail_agent_cli.config import (
    load_deepseek_config,
    load_mail_config,
)
from qq_mail_agent_cli.desktop_events import JsonLineEventSink
from qq_mail_agent_cli.health import run_local_health_checks
from qq_mail_agent_cli.llm_client import DeepSeekClient
from qq_mail_agent_cli.mail_client import MailClient
from qq_mail_agent_cli.services import ImapIdleWatcher, MailSyncService, SyncAlreadyRunningError
from qq_mail_agent_cli.storage import StateStore
from qq_mail_agent_cli.web_server import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="miaogent-worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--startup-max", type=int, default=200)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host != "127.0.0.1":
        raise SystemExit("--host must be exactly 127.0.0.1")
    session_token = os.getenv("QQ_MAIL_AGENT_SESSION_TOKEN")
    if not session_token or len(session_token) < 32:
        raise SystemExit(
            "QQ_MAIL_AGENT_SESSION_TOKEN must contain at least 32 random characters."
        )
    if args.parent_pid is not None and args.parent_pid <= 0:
        raise SystemExit("--parent-pid must be positive")
    if not 0 <= args.port <= 65535:
        raise SystemExit("--port must be between 0 and 65535")
    if args.startup_max < 1:
        raise SystemExit("--startup-max must be positive")

    try:
        import uvicorn
    except ImportError as error:  # pragma: no cover - packaging dependency guard
        raise SystemExit("Desktop runtime requires uvicorn and FastAPI.") from error

    data_dir = args.data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    event_sink = JsonLineEventSink()
    desktop_db_path = data_dir / "state.sqlite3"
    store = StateStore(desktop_db_path)
    mail_config = load_mail_config(load_dotenv=False)
    deepseek_config = load_deepseek_config(load_dotenv=False)
    mail_client = MailClient(mail_config)
    agent = MailAgent(llm_client=DeepSeekClient(deepseek_config))
    sync_service = MailSyncService(
        mail_client,
        agent,
        store,
        event_sink=event_sink,
        model=deepseek_config.model,
    )
    stop_event = Event()
    app = create_app(
        mail_client_factory=lambda: mail_client,
        agent_factory=lambda: agent,
        state_store_factory=lambda: store,
        sync_service_factory=lambda: sync_service,
        session_token=session_token,
        mail_config_factory=lambda: mail_config,
        deepseek_config_factory=lambda: deepseek_config,
        local_health_factory=lambda: run_local_health_checks(
            load_dotenv=False,
            db_path=desktop_db_path,
        ),
        shutdown_callback=stop_event.set,
    )

    server_socket = _bind_loopback(args.host, args.port)
    actual_port = int(server_socket.getsockname()[1])
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=actual_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = Thread(
        target=server.run,
        kwargs={"sockets": [server_socket]},
        name="qq-mail-api",
        daemon=True,
    )
    server_thread.start()
    if not _wait_until_started(server, server_thread, timeout_seconds=10):
        server.should_exit = True
        server_thread.join(timeout=3)
        raise RuntimeError("Desktop API failed to start on loopback.")

    event_sink.emit(
        "ready",
        {
            "base_url": f"http://127.0.0.1:{actual_port}",
            "pid": os.getpid(),
        },
    )
    sync_service.replay_unacknowledged_startup_summaries()

    def sync_after_wakeup() -> None:
        while not stop_event.is_set():
            try:
                sync_service.sync(trigger="idle")
                return
            except SyncAlreadyRunningError:
                stop_event.wait(0.25)

    watcher = ImapIdleWatcher(
        mail_config,
        sync_after_wakeup,
        event_sink=event_sink,
    )

    def run_background_agent() -> None:
        try:
            sync_service.sync_startup(max_messages=args.startup_max)
        except Exception as error:
            payload = _startup_failure_payload(error)
            stored_summary = store.save_startup_summary(payload)
            event_payload = {
                **payload,
                "id": stored_summary.id,
                "created_at": stored_summary.created_at,
            }
            try:
                event_sink.emit("startup_summary", event_payload)
            except Exception:
                store.mark_startup_summary_delivery(stored_summary.id, "failed")
        if not stop_event.is_set():
            watcher.run(stop_event)

    agent_thread = Thread(target=run_background_agent, name="qq-mail-agent", daemon=True)
    agent_thread.start()

    exit_code = 0
    try:
        while server_thread.is_alive() and not stop_event.wait(2):
            if args.parent_pid is not None and not _process_exists(args.parent_pid):
                break
            if not agent_thread.is_alive():
                event_sink.emit(
                    "watcher_status",
                    {"status": "fatal", "mode": "none", "error": "后台邮件监听意外退出"},
                )
                exit_code = 1
                break
    except KeyboardInterrupt:
        pass
    finally:
        if not server_thread.is_alive() and not stop_event.is_set():
            exit_code = 1
        stop_event.set()
        server.should_exit = True
        agent_thread.join(timeout=5)
        server_thread.join(timeout=5)
        try:
            server_socket.close()
        except OSError:
            pass
    return exit_code


def _bind_loopback(host: str, port: int) -> socket.socket:
    if host != "127.0.0.1":
        raise ValueError("desktop API may bind only to 127.0.0.1")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(2048)
    server_socket.setblocking(False)
    return server_socket


def _wait_until_started(server, thread: Thread, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline and thread.is_alive():
        if server.started:
            return True
        time.sleep(0.02)
    return bool(server.started)


def _process_exists(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_process_exists(pid: int) -> bool:
    """Query Windows without ``os.kill(pid, 0)``, which may terminate a process."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # Access denied still means that a protected process exists.
        return ctypes.get_last_error() == 5
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _startup_failure_payload(error: Exception) -> dict[str, object]:
    failure = _classify_startup_failure(error)
    return {
        "trigger": "startup",
        "generated_at": _utc_now(),
        "new_count": 0,
        "processed_count": 0,
        "important_count": 0,
        "urgent_count": 0,
        "reply_count": 0,
        "draft_ready_count": 0,
        "general_count": 0,
        "failed_count": 1,
        "has_more": failure["stage"] not in {"configuration"},
        "items": [],
        "failures": [failure],
    }


def _classify_startup_failure(error: Exception) -> dict[str, str]:
    message = str(error)
    if "Missing required mail config" in message:
        missing = _safe_missing_config_detail(message)
        detail = "桌面 Agent 配置未完成，请打开右上角“桌面 Agent 设置”，填写 QQ 邮箱地址和客户端授权码。"
        if missing:
            detail = f"{detail} 缺少：{missing}。"
        return {
            "uid": "mailbox",
            "stage": "configuration",
            "error": f"ConfigurationError: {detail}",
        }
    if "DEEPSEEK_API_KEY is missing" in message:
        return {
            "uid": "mailbox",
            "stage": "configuration",
            "error": "ConfigurationError: DeepSeek API Key 未配置，请在桌面 Agent 设置中填写后重试。",
        }
    if "IMAP login failed" in message:
        return {
            "uid": "mailbox",
            "stage": "imap_login",
            "error": "RuntimeError: QQ IMAP 登录失败，请检查 QQ 邮箱地址、客户端授权码和 IMAP/SMTP 服务是否已开启。",
        }
    if "IMAP connection failed" in message or "incremental fetch" in message:
        return {
            "uid": "mailbox",
            "stage": "imap_connection",
            "error": "RuntimeError: QQ IMAP 连接暂时失败，请检查网络、DNS 或 IMAP 服务状态后重试。",
        }
    if "DeepSeek API" in message:
        return {
            "uid": "mailbox",
            "stage": "deepseek",
            "error": "RuntimeError: DeepSeek 暂时不可用，邮件未自动分析，请稍后重试。",
        }
    return {
        "uid": "mailbox",
        "stage": "startup",
        "error": f"{error.__class__.__name__}: 启动同步暂时失败，请稍后重试",
    }


def _safe_missing_config_detail(message: str) -> str:
    allowed = {"QQ_MAIL_ADDRESS", "QQ_MAIL_AUTH_CODE"}
    if ":" not in message:
        return ""
    values = []
    for raw in message.split(":", 1)[1].split(","):
        key = raw.strip()
        if key in allowed:
            values.append(key)
    return ", ".join(values)


if __name__ == "__main__":
    raise SystemExit(main())

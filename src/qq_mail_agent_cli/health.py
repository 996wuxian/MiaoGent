from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
import imaplib
import os
from pathlib import Path
import sqlite3
import smtplib

from qq_mail_agent_cli.config import DeepSeekConfig, MailConfig, load_env_file
from qq_mail_agent_cli.llm_client import ChatMessage, DeepSeekClient


@dataclass(frozen=True)
class HealthCheckItem:
    name: str
    ok: bool
    detail: str


def run_local_health_checks(
    *,
    load_dotenv: bool = True,
    db_path: Path | None = None,
) -> list[HealthCheckItem]:
    if load_dotenv:
        load_env_file()
    items = [
        _required_env("QQ_MAIL_ADDRESS", label="QQ_MAIL_ADDRESS"),
        _required_env("QQ_MAIL_AUTH_CODE", label="QQ_MAIL_AUTH_CODE"),
        _host_port("QQ IMAP", "QQ_MAIL_IMAP_HOST", "QQ_MAIL_IMAP_PORT", "imap.qq.com", "993"),
        _host_port("QQ SMTP", "QQ_MAIL_SMTP_HOST", "QQ_MAIL_SMTP_PORT", "smtp.qq.com", "465"),
        _required_env("DEEPSEEK_API_KEY", fallback_key="DeepSeek_API_KEY", label="DEEPSEEK_API_KEY"),
        _required_env("DEEPSEEK_BASE_URL", label="DEEPSEEK_BASE_URL", default="https://api.deepseek.com"),
        _required_env("DEEPSEEK_MODEL", label="DEEPSEEK_MODEL", default="deepseek-chat"),
        _positive_int_env("DEEPSEEK_TIMEOUT_SECONDS", default="45"),
        _sqlite_writable(
            db_path or Path(os.getenv("QQ_MAIL_AGENT_DB_PATH", ".mail_agent_state/state.sqlite3"))
        ),
    ]
    return items


def check_imap_login(config: MailConfig) -> HealthCheckItem:
    missing = _missing_mail_config(config)
    if missing:
        return HealthCheckItem("QQ IMAP", False, f"缺少配置: {', '.join(missing)}")
    try:
        imap = imaplib.IMAP4_SSL(config.imap_host, config.imap_port)
        try:
            imap.login(config.address, config.auth_code)
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    except Exception as error:
        return HealthCheckItem("QQ IMAP", False, f"登录失败: {_sanitize_error(str(error), _mail_secrets(config))}")
    return HealthCheckItem("QQ IMAP", True, "登录成功，未读取邮件")


def check_smtp_login(config: MailConfig) -> HealthCheckItem:
    missing = _missing_mail_config(config)
    if missing:
        return HealthCheckItem("QQ SMTP", False, f"缺少配置: {', '.join(missing)}")
    try:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=45) as smtp:
            smtp.login(config.address, config.auth_code)
    except Exception as error:
        return HealthCheckItem("QQ SMTP", False, f"登录失败: {_sanitize_error(str(error), _mail_secrets(config))}")
    return HealthCheckItem("QQ SMTP", True, "登录成功，未发送邮件")


def check_deepseek_connectivity(config: DeepSeekConfig) -> HealthCheckItem:
    if not config.api_key:
        return HealthCheckItem("DeepSeek", False, "缺少配置: DEEPSEEK_API_KEY")
    try:
        response = DeepSeekClient(config).chat(
            [
                ChatMessage(role="system", content="Return exactly pong."),
                ChatMessage(role="user", content="ping"),
            ],
            temperature=0.0,
        )
    except Exception as error:
        return HealthCheckItem("DeepSeek", False, f"连通失败: {_sanitize_error(str(error), _deepseek_secrets(config))}")
    if not response.strip():
        return HealthCheckItem("DeepSeek", False, "连通失败: 返回内容为空")
    if "pong" in response.lower():
        return HealthCheckItem("DeepSeek", True, "连通成功")
    return HealthCheckItem("DeepSeek", True, "连通成功，返回非空")


def _required_env(key: str, *, label: str, default: str | None = None, fallback_key: str | None = None) -> HealthCheckItem:
    value = os.getenv(key) or (os.getenv(fallback_key) if fallback_key else None) or default
    if value:
        return HealthCheckItem(label, True, "已配置")
    return HealthCheckItem(label, False, "未配置")


def _host_port(name: str, host_key: str, port_key: str, default_host: str, default_port: str) -> HealthCheckItem:
    host = os.getenv(host_key, default_host)
    port_text = os.getenv(port_key, default_port)
    try:
        port = int(port_text)
    except ValueError:
        return HealthCheckItem(name, False, f"{host}:{port_text} 端口不是有效数字")
    if not 1 <= port <= 65535:
        return HealthCheckItem(name, False, f"{host}:{port} 端口超出范围")
    return HealthCheckItem(name, True, f"{host}:{port}")


def _positive_int_env(key: str, *, default: str) -> HealthCheckItem:
    value = os.getenv(key, default)
    try:
        parsed = int(value)
    except ValueError:
        return HealthCheckItem(key, False, "不是有效数字")
    if parsed <= 0:
        return HealthCheckItem(key, False, "必须大于 0")
    return HealthCheckItem(key, True, str(parsed))


def _sqlite_writable(db_path: Path) -> HealthCheckItem:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS __health_check(id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO __health_check DEFAULT VALUES")
            conn.execute("DELETE FROM __health_check")
            conn.execute("DROP TABLE __health_check")
            conn.commit()
    except Exception as error:
        return HealthCheckItem("SQLite", False, f"不可写 {db_path}: {error}")
    return HealthCheckItem("SQLite", True, f"可写 {db_path}")


def _missing_mail_config(config: MailConfig) -> list[str]:
    missing = []
    if not config.address:
        missing.append("QQ_MAIL_ADDRESS")
    if not config.auth_code:
        missing.append("QQ_MAIL_AUTH_CODE")
    return missing


def _mail_secrets(config: MailConfig) -> list[str]:
    return [value for value in [config.address, config.auth_code] if value]


def _deepseek_secrets(config: DeepSeekConfig) -> list[str]:
    return [value for value in [config.api_key] if value]


def _sanitize_error(message: str, secrets: list[str]) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "***")
    return sanitized

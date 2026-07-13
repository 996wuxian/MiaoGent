from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
import imaplib
import os
from pathlib import Path
import sqlite3
import smtplib

from qq_mail_agent_cli.config import DeepSeekConfig, MailConfig, load_deepseek_config, load_env_file, load_mail_config
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
    mail_config = load_mail_config(load_dotenv=False)
    deepseek_config = load_deepseek_config(load_dotenv=False)
    mail_label = "163 邮箱" if mail_config.provider == "netease_163" else "QQ 邮箱"
    items = [
        HealthCheckItem(f"{mail_label}地址", bool(mail_config.address), "已配置" if mail_config.address else "未配置"),
        HealthCheckItem(
            f"{mail_label}授权码",
            bool(mail_config.auth_code),
            "已配置" if mail_config.auth_code else "未配置",
        ),
        HealthCheckItem("邮箱 IMAP", True, f"{mail_config.imap_host}:{mail_config.imap_port}"),
        HealthCheckItem("邮箱 SMTP", True, f"{mail_config.smtp_host}:{mail_config.smtp_port}"),
        HealthCheckItem("DEEPSEEK_API_KEY", bool(deepseek_config.api_key), "已配置" if deepseek_config.api_key else "未配置"),
        HealthCheckItem("DEEPSEEK_BASE_URL", bool(deepseek_config.base_url), deepseek_config.base_url),
        HealthCheckItem("DEEPSEEK_MODEL", bool(deepseek_config.model), deepseek_config.model),
        HealthCheckItem("DEEPSEEK_TIMEOUT_SECONDS", deepseek_config.timeout_seconds > 0, str(deepseek_config.timeout_seconds)),
        _sqlite_writable(
            db_path or Path(os.getenv("QQ_MAIL_AGENT_DB_PATH", ".mail_agent_state/state.sqlite3"))
        ),
    ]
    return items


def check_imap_login(config: MailConfig) -> HealthCheckItem:
    missing = _missing_mail_config(config)
    if missing:
        return HealthCheckItem("邮箱 IMAP", False, f"缺少配置: {', '.join(missing)}")
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
        return HealthCheckItem("邮箱 IMAP", False, f"登录失败: {_sanitize_error(str(error), _mail_secrets(config))}")
    return HealthCheckItem("邮箱 IMAP", True, "登录成功，未读取邮件")


def check_smtp_login(config: MailConfig) -> HealthCheckItem:
    missing = _missing_mail_config(config)
    if missing:
        return HealthCheckItem("邮箱 SMTP", False, f"缺少配置: {', '.join(missing)}")
    try:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=45) as smtp:
            smtp.login(config.address, config.auth_code)
    except Exception as error:
        return HealthCheckItem("邮箱 SMTP", False, f"登录失败: {_sanitize_error(str(error), _mail_secrets(config))}")
    return HealthCheckItem("邮箱 SMTP", True, "登录成功，未发送邮件")


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
        missing.append("邮箱地址")
    if not config.auth_code:
        missing.append("邮箱授权码")
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

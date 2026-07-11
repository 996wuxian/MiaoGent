from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class MailConfig:
    address: str | None
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    auth_code: str | None
    timeout_seconds: int = 30
    max_auto_fetch_bytes: int = 5_000_000


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: int


@dataclass(frozen=True)
class AppConfig:
    db_path: Path


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_mail_config(*, load_dotenv: bool = True) -> MailConfig:
    if load_dotenv:
        load_env_file()
    return MailConfig(
        address=os.getenv("QQ_MAIL_ADDRESS"),
        imap_host=os.getenv("QQ_MAIL_IMAP_HOST", "imap.qq.com"),
        imap_port=int(os.getenv("QQ_MAIL_IMAP_PORT", "993")),
        smtp_host=os.getenv("QQ_MAIL_SMTP_HOST", "smtp.qq.com"),
        smtp_port=int(os.getenv("QQ_MAIL_SMTP_PORT", "465")),
        auth_code=os.getenv("QQ_MAIL_AUTH_CODE"),
        timeout_seconds=int(os.getenv("QQ_MAIL_IMAP_TIMEOUT_SECONDS", "30")),
        max_auto_fetch_bytes=int(os.getenv("QQ_MAIL_AGENT_MAX_MESSAGE_BYTES", "5000000")),
    )


def load_deepseek_config(*, load_dotenv: bool = True) -> DeepSeekConfig:
    if load_dotenv:
        load_env_file()
    return DeepSeekConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("DeepSeek_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        timeout_seconds=int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "45")),
    )


def load_app_config() -> AppConfig:
    load_env_file()
    return AppConfig(db_path=Path(os.getenv("QQ_MAIL_AGENT_DB_PATH", ".mail_agent_state/state.sqlite3")))

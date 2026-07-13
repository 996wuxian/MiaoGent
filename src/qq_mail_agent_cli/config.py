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
    provider: str = "qq"


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
    provider = _mail_provider()
    provider_prefix = "163_MAIL" if provider == "netease_163" else "QQ_MAIL"
    fallback_prefixes = ("QQ_MAIL",) if provider == "qq" else ()
    return MailConfig(
        address=_first_env(
            "MAIL_ADDRESS",
            f"{provider_prefix}_ADDRESS",
            *(f"{prefix}_ADDRESS" for prefix in fallback_prefixes),
        ),
        imap_host=_first_env(
            "MAIL_IMAP_HOST",
            f"{provider_prefix}_IMAP_HOST",
            *(f"{prefix}_IMAP_HOST" for prefix in fallback_prefixes),
            default="imap.163.com" if provider == "netease_163" else "imap.qq.com",
        ),
        imap_port=int(
            _first_env(
                "MAIL_IMAP_PORT",
                f"{provider_prefix}_IMAP_PORT",
                *(f"{prefix}_IMAP_PORT" for prefix in fallback_prefixes),
                default="993",
            )
        ),
        smtp_host=_first_env(
            "MAIL_SMTP_HOST",
            f"{provider_prefix}_SMTP_HOST",
            *(f"{prefix}_SMTP_HOST" for prefix in fallback_prefixes),
            default="smtp.163.com" if provider == "netease_163" else "smtp.qq.com",
        ),
        smtp_port=int(
            _first_env(
                "MAIL_SMTP_PORT",
                f"{provider_prefix}_SMTP_PORT",
                *(f"{prefix}_SMTP_PORT" for prefix in fallback_prefixes),
                default="465",
            )
        ),
        auth_code=_first_env(
            "MAIL_AUTH_CODE",
            f"{provider_prefix}_AUTH_CODE",
            *(f"{prefix}_AUTH_CODE" for prefix in fallback_prefixes),
        ),
        timeout_seconds=int(os.getenv("QQ_MAIL_IMAP_TIMEOUT_SECONDS", "30")),
        max_auto_fetch_bytes=int(os.getenv("QQ_MAIL_AGENT_MAX_MESSAGE_BYTES", "5000000")),
        provider=provider,
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


def _first_env(*keys: str, default: str | None = None) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


def _mail_provider() -> str:
    explicit = os.getenv("MAIL_PROVIDER") or os.getenv("QQ_MAIL_PROVIDER")
    if explicit in {"qq", "netease_163"}:
        return explicit
    if os.getenv("163_MAIL_ADDRESS") or os.getenv("163_MAIL_AUTH_CODE"):
        return "netease_163"
    return "qq"

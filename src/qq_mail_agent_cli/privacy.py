from __future__ import annotations

from dataclasses import dataclass
import re

from qq_mail_agent_cli.models import MailMessage


@dataclass(frozen=True)
class PrivacyConfig:
    enabled: bool = True
    block_ai_for_sensitive: bool = True
    subject_body_scan_limit: int = 8_000


@dataclass(frozen=True)
class PrivacyVerdict:
    sensitive: bool
    categories: tuple[str, ...] = ()
    reason_zh: str = ""
    level: str = "normal"


_SENSITIVE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "入职/录用",
        (
            r"\boffer\b",
            r"\boffer\s*letter\b",
            r"\bemployment\b",
            "录用",
            "入职",
            "聘用",
            "入职通知",
            "录取通知",
        ),
    ),
    (
        "薪资/合同",
        (
            "薪资",
            "工资",
            "待遇",
            "合同",
            "劳动合同",
            "保密协议",
            r"\bnda\b",
        ),
    ),
    (
        "身份/财务",
        (
            "身份证",
            "护照",
            "银行卡",
            "银行账号",
            "社保",
            "公积金",
            "税务",
        ),
    ),
    (
        "地址/联系方式",
        (
            "住址",
            "家庭地址",
            "手机号",
        ),
    ),
    (
        "敏感附件",
        (
            "附件",
            r"\battachment\b",
            r"\boffer\.pdf\b",
            "合同.pdf",
        ),
    ),
)


def classify_mail_privacy(message: MailMessage, config: PrivacyConfig | None = None) -> PrivacyVerdict:
    config = config or PrivacyConfig()
    if not config.enabled:
        return PrivacyVerdict(sensitive=False)

    text = _scan_text(message, limit=config.subject_body_scan_limit)
    categories = []
    for category, patterns in _SENSITIVE_PATTERNS:
        if any(_matches(text, pattern) for pattern in patterns):
            categories.append(category)

    unique_categories = tuple(dict.fromkeys(categories))
    if not unique_categories:
        return PrivacyVerdict(sensitive=False)
    return PrivacyVerdict(
        sensitive=True,
        categories=unique_categories,
        reason_zh=f"疑似包含{ '、'.join(unique_categories) }等隐私信息",
        level=_privacy_level(unique_categories),
    )


def classify_mail_title_privacy(subject: str, config: PrivacyConfig | None = None) -> PrivacyVerdict:
    config = config or PrivacyConfig()
    if not config.enabled:
        return PrivacyVerdict(sensitive=False)

    text = (subject or "")[: max(0, config.subject_body_scan_limit)].lower()
    categories = []
    for category, patterns in _SENSITIVE_PATTERNS:
        if any(_matches(text, pattern) for pattern in patterns):
            categories.append(category)

    unique_categories = tuple(dict.fromkeys(categories))
    if not unique_categories:
        return PrivacyVerdict(sensitive=False)
    return PrivacyVerdict(
        sensitive=True,
        categories=unique_categories,
        reason_zh=f"标题疑似包含{ '、'.join(unique_categories) }等隐私信息",
        level=_privacy_level(unique_categories),
    )


def should_block_ai(message: MailMessage, config: PrivacyConfig | None = None) -> PrivacyVerdict:
    config = config or PrivacyConfig()
    verdict = classify_mail_privacy(message, config)
    if not config.enabled or not config.block_ai_for_sensitive:
        return PrivacyVerdict(sensitive=False)
    return verdict


def privacy_review_summary(verdict: PrivacyVerdict) -> tuple[str, str, str]:
    reason = verdict.reason_zh or "疑似包含隐私信息"
    return (
        f"{reason}，已按隐私保护模式阻止发送给 DeepSeek。",
        "为避免把敏感邮件正文发送给第三方模型，请人工打开查看。",
        "privacy_private" if verdict.level == "private" else "privacy_sensitive",
    )


def privacy_error_code(verdict: PrivacyVerdict) -> str | None:
    if not verdict.sensitive:
        return None
    return "privacy_private" if verdict.level == "private" else "privacy_sensitive"


def _scan_text(message: MailMessage, *, limit: int) -> str:
    value = "\n".join(
        part
        for part in [
            message.sender or "",
            message.subject or "",
            message.snippet or "",
            message.body or "",
        ]
        if part
    )
    return value[: max(0, limit)].lower()


def _matches(text: str, pattern: str) -> bool:
    if pattern.startswith(r"\b") or "\\" in pattern:
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return pattern.lower() in text


def _privacy_level(categories: tuple[str, ...]) -> str:
    private_categories = {"身份/财务", "地址/联系方式"}
    return "private" if any(category in private_categories for category in categories) else "sensitive"

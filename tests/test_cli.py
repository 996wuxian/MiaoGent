from pathlib import Path

import pytest

from qq_mail_agent_cli.main import main
import qq_mail_agent_cli.interactive as interactive
import qq_mail_agent_cli.mail_client as mail_client


def test_list_command(capsys):
    assert main(["list", "--limit", "1"]) == 0
    output = capsys.readouterr().out
    assert "mock-1" in output


def test_real_list_formatter_hides_snippet_by_default(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage

    monkeypatch.setattr(
        "qq_mail_agent_cli.mail_client.MailClient.list_real_recent",
        lambda self, limit: [
            MailMessage(
                id="uid:1",
                sender="sender@example.com",
                recipient="you@qq.com",
                subject="Sensitive subject",
                body="secret body",
                date="today",
                snippet="secret snippet",
                is_seen=False,
            )
        ],
    )
    assert main(["list", "--real", "--limit", "1"]) == 0
    output = capsys.readouterr().out
    assert "uid:1" in output
    assert "unread" in output
    assert "secret snippet" not in output


def test_triage_command(capsys):
    assert main(["triage", "--limit", "3"]) == 0
    output = capsys.readouterr().out
    assert "respond" in output
    assert "notify" in output
    assert "draft_reply" in output


def test_agent_rule_triage_includes_suggested_action():
    from qq_mail_agent_cli.agent import MailAgent
    from qq_mail_agent_cli.models import MailMessage, SuggestedAction

    result = MailAgent().triage(
        MailMessage(
            id="mock",
            sender="sender@example.com",
            recipient="you@qq.com",
            subject="Question",
            body="Can you reply?",
        )
    )

    assert result.suggested_action == SuggestedAction.DRAFT_REPLY
    assert result.action_reason


def test_agent_draft_preserves_reply_thread_headers():
    from qq_mail_agent_cli.agent import MailAgent
    from qq_mail_agent_cli.models import MailMessage

    message = MailMessage(
        id="uid:1",
        sender="sender@example.com",
        recipient="you@qq.com",
        subject="Question",
        body="Can you reply?",
        message_id="<source@example.com>",
        references="<root@example.com>",
    )

    draft = MailAgent().draft_reply(message)

    assert draft.reply_to_message_id == "<source@example.com>"
    assert draft.references == "<root@example.com>"


def test_agent_mock_translation_returns_chinese_placeholder():
    from qq_mail_agent_cli.agent import MailAgent
    from qq_mail_agent_cli.models import MailMessage

    message = MailMessage(
        id="uid:1",
        sender="sender@example.com",
        recipient="you@qq.com",
        subject="Invitation for Interview",
        body="Please join the interview tomorrow.",
    )

    translation = MailAgent().translate_message(message)

    assert translation.mail_id == "uid:1"
    assert "模拟翻译" in translation.subject_zh
    assert "DeepSeek" in translation.body_zh


def test_agent_llm_translation_uses_structured_json():
    from qq_mail_agent_cli.agent import MailAgent
    from qq_mail_agent_cli.models import MailMessage

    captured = {}

    class FakeLlm:
        def chat(self, messages, *, temperature):
            captured["messages"] = messages
            captured["temperature"] = temperature
            return '{"subject_zh":"面试邀请","body_zh":"请明天参加面试。"}'

    message = MailMessage(
        id="uid:1",
        sender="sender@example.com",
        recipient="you@qq.com",
        subject="Invitation for Interview",
        body="Please join the interview tomorrow.",
    )

    translation = MailAgent(llm_client=FakeLlm()).translate_message(message)

    assert translation.subject_zh == "面试邀请"
    assert translation.body_zh == "请明天参加面试。"
    assert captured["temperature"] == 0.0
    assert "Return only JSON" in captured["messages"][0].content
    assert "Invitation for Interview" in captured["messages"][1].content


def test_agent_llm_triage_parses_suggested_action():
    from qq_mail_agent_cli.agent import MailAgent
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction

    captured = {}

    class FakeLlm:
        def chat(self, messages, *, temperature):
            captured["messages"] = messages
            captured["temperature"] = temperature
            return (
                '{"classification":"respond","reason":"Needs a reply.",'
                '"suggested_action":"draft_reply","action_reason":"The sender asks a question."}'
            )

    result = MailAgent(llm_client=FakeLlm()).triage(
        MailMessage(
            id="uid:1",
            sender="sender@example.com",
            recipient="you@qq.com",
            subject="Question",
            body="Can you reply?",
        )
    )

    assert result.classification == MailClassification.RESPOND
    assert result.suggested_action == SuggestedAction.DRAFT_REPLY
    assert result.action_reason == "The sender asks a question."
    assert captured["temperature"] == 0.0
    assert "suggested_action" in captured["messages"][0].content


def test_agent_llm_triage_invalid_suggested_action_falls_back():
    from qq_mail_agent_cli.agent import MailAgent
    from qq_mail_agent_cli.models import MailMessage, SuggestedAction

    class FakeLlm:
        def chat(self, messages, *, temperature):
            return '{"classification":"notify","reason":"FYI.","suggested_action":"delete_everything","action_reason":"bad"}'

    result = MailAgent(llm_client=FakeLlm()).triage(
        MailMessage(
            id="uid:1",
            sender="sender@example.com",
            recipient="you@qq.com",
            subject="FYI",
            body="Deployment completed.",
        )
    )

    assert result.suggested_action == SuggestedAction.READ_FULL


def test_translate_command_uses_mock_by_default(capsys):
    assert main(["translate", "--id", "mock-1"]) == 0
    output = capsys.readouterr().out
    assert "Translation: mock-1" in output
    assert "模拟翻译" in output


def test_send_defaults_to_dry_run_uses_stored_draft(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import Draft
    from qq_mail_agent_cli.storage import StateStore

    db_path = tmp_path / "state.sqlite3"
    StateStore(db_path).save_draft(
        Draft(
            id="stored-draft",
            mail_id="uid:9",
            to="bob@example.com",
            subject="Re: Stored subject",
            body="Stored body, not a hard-coded mock.",
        )
    )
    monkeypatch.setenv("QQ_MAIL_AGENT_DB_PATH", str(db_path))

    assert main(["send", "--draft", "stored-draft"]) == 0
    output = capsys.readouterr().out
    assert "Dry run" in output
    assert "bob@example.com" in output
    assert "Stored body, not a hard-coded mock." in output
    assert "alice@example.com" not in output


def test_send_yes_send_delivers_stored_draft_and_marks_sent(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import Draft, DraftSendResult
    from qq_mail_agent_cli.storage import StateStore

    db_path = tmp_path / "state.sqlite3"
    store = StateStore(db_path)
    store.save_draft(
        Draft(
            id="stored-draft",
            mail_id="uid:9",
            to="bob@example.com",
            subject="Re: Stored subject",
            body="Stored body.",
            reply_to_message_id="<source@example.com>",
        )
    )
    monkeypatch.setenv("QQ_MAIL_AGENT_DB_PATH", str(db_path))
    sent = []

    def fake_send(self, draft, *, dry_run=True):
        assert dry_run is False
        sent.append(draft)
        return DraftSendResult(draft_id=draft.id, to=draft.to, saved_to_sent=True, sent_mailbox="Sent")

    monkeypatch.setattr("qq_mail_agent_cli.mail_client.MailClient.send_draft", fake_send)

    assert main(["send", "--draft", "stored-draft", "--yes-send"]) == 0

    assert len(sent) == 1
    assert sent[0].to == "bob@example.com"
    assert sent[0].body == "Stored body."
    assert sent[0].reply_to_message_id == "<source@example.com>"
    assert StateStore(db_path).get_draft("stored-draft").send_status == "sent"
    assert "saved to Sent" in capsys.readouterr().out


def test_send_rejects_missing_or_already_sent_stored_draft(tmp_path, monkeypatch):
    from qq_mail_agent_cli.models import Draft
    from qq_mail_agent_cli.storage import StateStore

    db_path = tmp_path / "state.sqlite3"
    store = StateStore(db_path)
    store.save_draft(
        Draft(
            id="sent-draft",
            mail_id="uid:9",
            to="bob@example.com",
            subject="Re: Stored subject",
            body="Stored body.",
        )
    )
    store.mark_draft_sent("sent-draft")
    monkeypatch.setenv("QQ_MAIL_AGENT_DB_PATH", str(db_path))

    with pytest.raises(SystemExit) as missing:
        main(["send", "--draft", "missing", "--yes-send"])
    assert missing.value.code == 2

    with pytest.raises(SystemExit) as sent:
        main(["send", "--draft", "sent-draft", "--yes-send"])
    assert sent.value.code == 2


def test_ai_without_key_reports_missing_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DeepSeek_API_KEY", raising=False)
    monkeypatch.setattr("qq_mail_agent_cli.config.load_env_file", lambda path=".env": None)

    try:
        main(["triage", "--ai", "--limit", "1"])
    except RuntimeError as error:
        assert "DEEPSEEK_API_KEY" in str(error)
    else:
        raise AssertionError("Expected missing DeepSeek API key error")


def test_real_without_mail_config_reports_missing_config(monkeypatch):
    monkeypatch.delenv("QQ_MAIL_ADDRESS", raising=False)
    monkeypatch.delenv("QQ_MAIL_AUTH_CODE", raising=False)
    monkeypatch.setattr("qq_mail_agent_cli.config.load_env_file", lambda path=".env": None)

    try:
        main(["list", "--real", "--limit", "1"])
    except RuntimeError as error:
        message = str(error)
        assert "QQ_MAIL_ADDRESS" in message
        assert "QQ_MAIL_AUTH_CODE" in message
    else:
        raise AssertionError("Expected missing QQ mail config error")


def test_mark_seen_rejects_invalid_uid_without_connecting(monkeypatch):
    from qq_mail_agent_cli.config import MailConfig
    from qq_mail_agent_cli.mail_client import MailClient

    client = MailClient(
        MailConfig(
            address="you@qq.com",
            imap_host="imap.qq.com",
            imap_port=993,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            auth_code="secret",
        )
    )
    monkeypatch.setattr(client, "_connect_imap", lambda: (_ for _ in ()).throw(AssertionError("should not connect")))
    assert client.mark_real_seen("not-a-uid") is False


def test_interactive_limit_defaults_on_empty(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert interactive._ask_limit(default=7) == 7


def test_interactive_yes_no_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert interactive._ask_yes_no("continue?", default=False) is False


def test_interactive_menu_is_simplified():
    assert "1. 邮件处理面板" in interactive.MENU
    assert "2. DeepSeek 分类最近邮件" in interactive.MENU
    assert "3. 草稿箱 / 编辑 / 发送" in interactive.MENU
    assert "4. 操作记录" in interactive.MENU
    assert "5. 配置体检" in interactive.MENU
    assert "10. 邮件处理面板" not in interactive.MENU
    assert "DeepSeek 翻译英文邮件" not in interactive.MENU
    assert "移动邮件到垃圾箱" not in interactive.MENU


def test_interactive_main_routes_simplified_menu(monkeypatch):
    calls = []

    class AppConfig:
        db_path = "unused.sqlite3"

    client = object()
    store = object()

    monkeypatch.setattr(interactive, "load_mail_config", lambda: object())
    monkeypatch.setattr(interactive, "MailClient", lambda config: client)
    monkeypatch.setattr(interactive, "load_app_config", lambda: AppConfig())
    monkeypatch.setattr(interactive, "StateStore", lambda db_path: store)
    monkeypatch.setattr(interactive, "_message_workbench_flow", lambda passed_client, passed_store: calls.append(("workbench", passed_client is client, passed_store is store)))
    monkeypatch.setattr(interactive, "_triage_real_messages_flow", lambda passed_client, passed_store: calls.append(("triage", passed_client is client, passed_store is store)))
    monkeypatch.setattr(interactive, "_draft_send_flow", lambda passed_client, passed_store: calls.append(("drafts", passed_client is client, passed_store is store)))
    monkeypatch.setattr(interactive, "_show_action_log", lambda passed_store: calls.append(("log", passed_store is store)))
    monkeypatch.setattr(interactive, "_config_health_flow", lambda: calls.append(("health",)))

    answers = iter(["1", "2", "3", "4", "5", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert interactive.main() == 0
    assert calls == [
        ("workbench", True, True),
        ("triage", True, True),
        ("drafts", True, True),
        ("log", True),
        ("health",),
    ]


def test_health_check_reports_missing_config_without_secret(monkeypatch, capsys):
    import qq_mail_agent_cli.health as health

    keys = [
        "QQ_MAIL_ADDRESS",
        "QQ_MAIL_AUTH_CODE",
        "QQ_MAIL_IMAP_HOST",
        "QQ_MAIL_IMAP_PORT",
        "QQ_MAIL_SMTP_HOST",
        "QQ_MAIL_SMTP_PORT",
        "DEEPSEEK_API_KEY",
        "DeepSeek_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_TIMEOUT_SECONDS",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QQ_MAIL_AGENT_DB_PATH", "health-test.sqlite3")
    monkeypatch.setattr(health, "load_env_file", lambda: None)
    monkeypatch.setattr(health, "_sqlite_writable", lambda path: health.HealthCheckItem("SQLite", True, f"可写 {path}"))

    items = health.run_local_health_checks()
    interactive._show_health_check_items(items)

    output = capsys.readouterr().out
    assert "[FAIL] QQ_MAIL_ADDRESS 未配置" in output
    assert "[FAIL] QQ_MAIL_AUTH_CODE 未配置" in output
    assert "[FAIL] DEEPSEEK_API_KEY 未配置" in output
    assert "结果: 需要补全配置" in output
    assert "secret" not in output.lower()


def test_health_check_passes_with_configured_env(tmp_path, monkeypatch):
    import qq_mail_agent_cli.health as health

    monkeypatch.setattr(health, "load_env_file", lambda: None)
    monkeypatch.setenv("QQ_MAIL_ADDRESS", "you@qq.com")
    monkeypatch.setenv("QQ_MAIL_AUTH_CODE", "secret-auth-code")
    monkeypatch.setenv("QQ_MAIL_IMAP_HOST", "imap.qq.com")
    monkeypatch.setenv("QQ_MAIL_IMAP_PORT", "993")
    monkeypatch.setenv("QQ_MAIL_SMTP_HOST", "smtp.qq.com")
    monkeypatch.setenv("QQ_MAIL_SMTP_PORT", "465")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("QQ_MAIL_AGENT_DB_PATH", str(tmp_path / "state.sqlite3"))

    items = health.run_local_health_checks()

    assert all(item.ok for item in items)
    assert not any("secret-auth-code" in item.detail for item in items)
    assert not any("secret-deepseek-key" in item.detail for item in items)


def test_config_health_flow_local_check(monkeypatch, capsys):
    import qq_mail_agent_cli.health as health

    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    monkeypatch.setattr(
        interactive,
        "run_local_health_checks",
        lambda: [health.HealthCheckItem("SQLite", True, "可写 test.sqlite3")],
    )

    interactive._config_health_flow()

    output = capsys.readouterr().out
    assert "配置体检" in output
    assert "1. 本地配置检查" in output
    assert "[OK] SQLite 可写 test.sqlite3" in output


def test_config_health_flow_external_check_requires_confirmation(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "2" if "请选择" in prompt else "n")
    monkeypatch.setattr(interactive, "check_imap_login", lambda config: (_ for _ in ()).throw(AssertionError("should not connect")))

    interactive._config_health_flow()

    assert "已取消。" in capsys.readouterr().out


def test_health_check_imap_login_success_and_failure_are_sanitized(monkeypatch):
    import qq_mail_agent_cli.health as health
    from qq_mail_agent_cli.config import MailConfig

    calls = []

    class FakeImap:
        def __init__(self, host, port):
            calls.append(("connect", host, port))

        def login(self, address, auth_code):
            calls.append(("login", address, auth_code))

        def logout(self):
            calls.append(("logout",))

    config = MailConfig(
        address="you@qq.com",
        imap_host="imap.qq.com",
        imap_port=993,
        smtp_host="smtp.qq.com",
        smtp_port=465,
        auth_code="secret-auth-code",
    )
    monkeypatch.setattr(health.imaplib, "IMAP4_SSL", FakeImap)

    success = health.check_imap_login(config)

    assert success.ok is True
    assert success.detail == "登录成功，未读取邮件"
    assert calls == [
        ("connect", "imap.qq.com", 993),
        ("login", "you@qq.com", "secret-auth-code"),
        ("logout",),
    ]

    class FailingImap(FakeImap):
        def login(self, address, auth_code):
            raise RuntimeError(f"bad login {address} {auth_code}")

    monkeypatch.setattr(health.imaplib, "IMAP4_SSL", FailingImap)
    failure = health.check_imap_login(config)

    assert failure.ok is False
    assert "secret-auth-code" not in failure.detail
    assert "you@qq.com" not in failure.detail
    assert "***" in failure.detail


def test_health_check_smtp_login_success(monkeypatch):
    import qq_mail_agent_cli.health as health
    from qq_mail_agent_cli.config import MailConfig

    calls = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append(("quit",))

        def login(self, address, auth_code):
            calls.append(("login", address, auth_code))

    config = MailConfig(
        address="you@qq.com",
        imap_host="imap.qq.com",
        imap_port=993,
        smtp_host="smtp.qq.com",
        smtp_port=465,
        auth_code="secret-auth-code",
    )
    monkeypatch.setattr(health.smtplib, "SMTP_SSL", FakeSmtp)

    result = health.check_smtp_login(config)

    assert result.ok is True
    assert result.detail == "登录成功，未发送邮件"
    assert calls == [
        ("connect", "smtp.qq.com", 465, 45),
        ("login", "you@qq.com", "secret-auth-code"),
        ("quit",),
    ]


def test_health_check_deepseek_ping_sanitizes_failure(monkeypatch):
    import qq_mail_agent_cli.health as health
    from qq_mail_agent_cli.config import DeepSeekConfig

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def chat(self, messages, *, temperature):
            raise RuntimeError(f"401 bad key {self.config.api_key}")

    config = DeepSeekConfig(
        api_key="secret-deepseek-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=45,
    )
    monkeypatch.setattr(health, "DeepSeekClient", FakeClient)

    result = health.check_deepseek_connectivity(config)

    assert result.ok is False
    assert "secret-deepseek-key" not in result.detail
    assert "***" in result.detail


def test_health_check_deepseek_ping_success(monkeypatch):
    import qq_mail_agent_cli.health as health
    from qq_mail_agent_cli.config import DeepSeekConfig

    captured = {}

    class FakeClient:
        def __init__(self, config):
            captured["config"] = config

        def chat(self, messages, *, temperature):
            captured["messages"] = messages
            captured["temperature"] = temperature
            return "pong"

    config = DeepSeekConfig(
        api_key="secret-deepseek-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=45,
    )
    monkeypatch.setattr(health, "DeepSeekClient", FakeClient)

    result = health.check_deepseek_connectivity(config)

    assert result.ok is True
    assert result.detail == "连通成功"
    assert captured["temperature"] == 0.0
    assert captured["messages"][1].content == "ping"


def test_interactive_message_output_is_block_layout(capsys):
    from qq_mail_agent_cli.models import MailMessage

    interactive._show_messages(
        [
            MailMessage(
                id="uid:9",
                sender="Very Long Sender <sender@example.com>",
                recipient="you@qq.com",
                subject="A long subject that should stay readable in the terminal",
                body="body",
                date="Mon, 06 Jul 2026 12:00:00 +0800",
                snippet="This is a long snippet that should be wrapped onto a readable indented line instead of being appended as another tab separated column.",
                is_seen=False,
            )
        ],
        allow_snippet=True,
    )
    output = capsys.readouterr().out
    assert "[1] uid:9" in output
    assert "[未读]" in output
    assert "发件人:" in output
    assert "主题:" in output
    assert "摘要:" in output
    assert "uid:9\t" not in output


def test_interactive_triage_summary_groups_repeated_subjects(capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult

    results = [
        (
            MailMessage(id="uid:1", sender="a@example.com", recipient="you@qq.com", subject="余额不足预警", body=""),
            TriageResult(
                mail_id="uid:1",
                classification=MailClassification.NOTIFY,
                reason="余额不足，需要关注。",
                suggested_action=SuggestedAction.READ_FULL,
                action_reason="需要查看余额详情。",
            ),
        ),
        (
            MailMessage(id="uid:2", sender="a@example.com", recipient="you@qq.com", subject="余额不足预警", body="", is_seen=True),
            TriageResult(mail_id="uid:2", classification=MailClassification.NOTIFY, reason="余额不足，需要关注。"),
        ),
        (
            MailMessage(id="uid:3", sender="b@example.com", recipient="you@qq.com", subject="GitHub security", body=""),
            TriageResult(mail_id="uid:3", classification=MailClassification.NOTIFY, reason="安全提醒。"),
        ),
    ]

    interactive._show_triage_summary(results)
    output = capsys.readouterr().out
    assert "分类汇总" in output
    assert "[notify] 2 封 - 余额不足预警" in output
    assert "建议动作: 查看全文" in output
    assert "动作原因: 需要查看余额详情。" in output
    assert "uid:1, uid:2" in output
    assert "uid:2 [已读]" in output
    assert "分类明细" in output


def test_triage_real_messages_flow_filters_unread_by_default(monkeypatch):
    from qq_mail_agent_cli.models import MailMessage

    captured = {}

    class FakeClient:
        def list_real_recent(self, limit):
            captured["limit"] = limit
            return [
                MailMessage(id="uid:1", sender="a", recipient="you", subject="Unread", body="", is_seen=False),
                MailMessage(id="uid:2", sender="b", recipient="you", subject="Seen", body="", is_seen=True),
            ]

    class FakeStore:
        def get_triaged_uids(self, uids):
            return set()

    answers = iter(["y", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: object())
    monkeypatch.setattr(
        interactive,
        "_triage_messages",
        lambda messages, agent, store=None, model="rules": captured.update({"ids": [message.id for message in messages], "model": model}),
    )

    interactive._triage_real_messages_flow(FakeClient(), FakeStore())

    assert captured["limit"] == 20
    assert captured["ids"] == ["uid:1"]
    assert captured["model"] == "deepseek"


def test_triage_real_messages_flow_skips_when_no_unread(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage

    class FakeClient:
        def list_real_recent(self, limit):
            return [
                MailMessage(id="uid:1", sender="a", recipient="you", subject="Seen", body="", is_seen=True),
                MailMessage(id="uid:2", sender="b", recipient="you", subject="Unknown", body="", is_seen=None),
            ]

    class FakeStore:
        pass

    answers = iter(["y", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: (_ for _ in ()).throw(AssertionError("should not build agent")))
    monkeypatch.setattr(interactive, "_triage_messages", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not triage")))

    interactive._triage_real_messages_flow(FakeClient(), FakeStore())

    assert "没有未读邮件需要分类。" in capsys.readouterr().out


def test_triage_real_messages_flow_can_include_seen(monkeypatch):
    from qq_mail_agent_cli.models import MailMessage

    captured = {}

    class FakeClient:
        def list_real_recent(self, limit):
            return [
                MailMessage(id="uid:1", sender="a", recipient="you", subject="Unread", body="", is_seen=False),
                MailMessage(id="uid:2", sender="b", recipient="you", subject="Seen", body="", is_seen=True),
            ]

    class FakeStore:
        def get_triaged_uids(self, uids):
            return set()

    answers = iter(["y", "2", "n", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: object())
    monkeypatch.setattr(
        interactive,
        "_triage_messages",
        lambda messages, agent, store=None, model="rules": captured.update({"ids": [message.id for message in messages], "model": model}),
    )

    interactive._triage_real_messages_flow(FakeClient(), FakeStore())

    assert captured["ids"] == ["uid:1", "uid:2"]
    assert captured["model"] == "deepseek"


def test_triage_real_messages_flow_skips_already_triaged_by_default(tmp_path, monkeypatch):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    captured = {}

    class FakeClient:
        def list_real_recent(self, limit):
            return [
                MailMessage(id="uid:1", sender="a", recipient="you", subject="New unread", body="", is_seen=False),
                MailMessage(id="uid:2", sender="b", recipient="you", subject="Old unread", body="", is_seen=False),
            ]

    store = StateStore(tmp_path / "state.sqlite3")
    old_message = MailMessage(id="uid:2", sender="b", recipient="you", subject="Old unread", body="")
    store.save_triage(
        old_message,
        TriageResult(mail_id="uid:2", classification=MailClassification.NOTIFY, reason="already done"),
        model="test",
    )

    answers = iter(["y", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: object())
    monkeypatch.setattr(
        interactive,
        "_triage_messages",
        lambda messages, agent, store=None, model="rules": captured.update({"ids": [message.id for message in messages], "model": model}),
    )

    interactive._triage_real_messages_flow(FakeClient(), store)

    assert captured["ids"] == ["uid:1"]
    assert captured["model"] == "deepseek"


def test_triage_real_messages_flow_skips_when_all_triaged(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    class FakeClient:
        def list_real_recent(self, limit):
            return [
                MailMessage(id="uid:1", sender="a", recipient="you", subject="Unread", body="", is_seen=False),
            ]

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="a", recipient="you", subject="Unread", body="")
    store.save_triage(
        message,
        TriageResult(mail_id="uid:1", classification=MailClassification.NOTIFY, reason="already done"),
        model="test",
    )

    answers = iter(["y", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: (_ for _ in ()).throw(AssertionError("should not build agent")))
    monkeypatch.setattr(interactive, "_triage_messages", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not triage")))

    interactive._triage_real_messages_flow(FakeClient(), store)

    assert "没有新的未分类邮件需要分类。" in capsys.readouterr().out


def test_triage_real_messages_flow_can_reclassify_triaged(tmp_path, monkeypatch):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    captured = {}

    class FakeClient:
        def list_real_recent(self, limit):
            return [
                MailMessage(id="uid:1", sender="a", recipient="you", subject="Unread", body="", is_seen=False),
            ]

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="a", recipient="you", subject="Unread", body="")
    store.save_triage(
        message,
        TriageResult(mail_id="uid:1", classification=MailClassification.NOTIFY, reason="already done"),
        model="test",
    )

    answers = iter(["y", "", "", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: object())
    monkeypatch.setattr(
        interactive,
        "_triage_messages",
        lambda messages, agent, store=None, model="rules": captured.update({"ids": [message.id for message in messages], "model": model}),
    )

    interactive._triage_real_messages_flow(FakeClient(), store)

    assert captured["ids"] == ["uid:1"]
    assert captured["model"] == "deepseek"


def test_interactive_full_message_output(capsys):
    from qq_mail_agent_cli.models import MailMessage

    interactive._show_full_message(
        MailMessage(
            id="uid:10",
            sender="sender@example.com",
            recipient="you@qq.com",
            subject="Full message",
            body="This is the full body of the message.",
            date="today",
            is_seen=True,
        )
    )
    output = capsys.readouterr().out
    assert "ID: uid:10 [已读]" in output
    assert "发件人:" in output
    assert "This is the full body" in output


def test_full_message_action_does_not_ask_mark_seen_for_seen_message(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage

    class FakeClient:
        def mark_real_seen(self, mail_id):
            raise AssertionError("should not mark an already seen message")

    class FakeStore:
        def upsert_mail(self, message):
            raise AssertionError("should not write state for already seen message")

        def log_action(self, action, *, uid=None, detail=""):
            raise AssertionError("should not log mark_seen for already seen message")

    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)
    message = MailMessage(
        id="uid:10",
        sender="sender@example.com",
        recipient="you@qq.com",
        subject="Seen message",
        body="Already read.",
        is_seen=True,
    )

    returned = interactive._show_full_message_action(FakeClient(), FakeStore(), message)

    assert returned is message
    assert prompts == []
    assert "ID: uid:10 [已读]" in capsys.readouterr().out


def test_interactive_export_html(tmp_path):
    from qq_mail_agent_cli.models import MailMessage

    message = MailMessage(
        id="uid:10",
        sender="sender@example.com",
        recipient="you@qq.com",
        subject="HTML message",
        body="plain",
        html_body="<p>Hello<img src=\"https://example.com/a.png\"></p>",
    )
    path = interactive._export_html(message, export_dir=tmp_path)
    assert path.name == "uid-10.html"
    content = path.read_text(encoding="utf-8")
    assert "<!doctype html>" in content
    assert "https://example.com/a.png" in content


def test_message_resources_output(capsys):
    from qq_mail_agent_cli.models import MailAttachment, MailMessage

    message = MailMessage(
        id="uid:11",
        sender="sender@example.com",
        recipient="you@qq.com",
        subject="HTML message",
        body="plain",
        html_body="<p>Hello</p>",
        remote_images=("https://example.com/a.png",),
        inline_images=("image/png logo",),
        attachments=(MailAttachment(filename="a.txt", content_type="text/plain", size=12),),
    )
    interactive._show_message_resources(message)
    output = capsys.readouterr().out
    assert "HTML 富文本: 有" in output
    assert "远程图片: 1" in output
    assert "内嵌图片: 1" in output
    assert "附件: 1" in output


def test_parse_mail_id_list_normalizes_numeric_ids():
    assert interactive._parse_mail_id_list("uid:1, 2,uid:3") == ["uid:1", "uid:2", "uid:3"]


def test_parse_selection_supports_ranges_and_all():
    assert interactive._parse_selection("1,3-5,8", max_index=10) == [1, 3, 4, 5, 8]
    assert interactive._parse_selection("all", max_index=3) == [1, 2, 3]


def test_parse_selection_rejects_out_of_range():
    try:
        interactive._parse_selection("1,9", max_index=3)
    except ValueError as error:
        assert "超出范围" in str(error)
    else:
        raise AssertionError("Expected out-of-range selection error")


def test_find_trash_mailbox_prefers_known_names():
    assert mail_client._find_trash_mailbox(["INBOX", "Sent", "Trash"]) == "Trash"
    assert mail_client._find_trash_mailbox(["INBOX", "垃圾箱"]) == "垃圾箱"
    assert mail_client._find_trash_mailbox(["INBOX"]) is None


def test_parse_mailbox_name_from_imap_list():
    assert mail_client._parse_mailbox_name(b'(\\HasNoChildren) "/" "Trash"') == "Trash"


def test_move_to_trash_selects_inbox_before_move(monkeypatch):
    from qq_mail_agent_cli.config import MailConfig
    from qq_mail_agent_cli.mail_client import MailClient

    calls = []

    class FakeImap:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list(self):
            calls.append(("list",))
            return "OK", [b'(\\HasNoChildren) "/" "Trash"']

        def select(self, mailbox, readonly=False):
            calls.append(("select", mailbox, readonly))
            return "OK", []

        def uid(self, command, uid_set, mailbox):
            calls.append(("uid", command, uid_set, mailbox))
            return "OK", []

    client = MailClient(
        MailConfig(
            address="you@qq.com",
            imap_host="imap.qq.com",
            imap_port=993,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            auth_code="secret",
        )
    )
    monkeypatch.setattr(client, "_connect_imap", lambda: FakeImap())

    assert client.move_real_to_trash(["uid:1", "uid:2"]) == "Trash"
    assert calls == [
        ("list",),
        ("select", "INBOX", False),
        ("uid", "MOVE", "1,2", '"Trash"'),
    ]


def test_fetch_uid_extracts_reply_thread_headers():
    from qq_mail_agent_cli.config import MailConfig
    from qq_mail_agent_cli.mail_client import MailClient

    raw_message = (
        b"From: Sender <sender@example.com>\r\n"
        b"To: You <you@qq.com>\r\n"
        b"Subject: Threaded question\r\n"
        b"Message-ID: <source@example.com>\r\n"
        b"References: <root@example.com> <parent@example.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Can you reply?\r\n"
    )

    class FakeImap:
        def uid(self, command, uid, query):
            assert command == "fetch"
            assert uid == b"123"
            assert query == "(FLAGS BODY.PEEK[])"
            return "OK", [(b"123 (FLAGS (\\Seen))", raw_message)]

    client = MailClient(
        MailConfig(
            address="you@qq.com",
            imap_host="imap.qq.com",
            imap_port=993,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            auth_code="secret",
        )
    )

    message = client._fetch_uid(FakeImap(), b"123")

    assert message is not None
    assert message.message_id == "<source@example.com>"
    assert message.references == "<root@example.com> <parent@example.com>"
    assert message.is_seen is True


def test_fetch_uid_converts_mislabeled_html_plain_part_to_readable_text():
    from qq_mail_agent_cli.config import MailConfig
    from qq_mail_agent_cli.mail_client import MailClient

    raw_message = (
        b"From: Sender <sender@example.com>\r\n"
        b"To: You <you@qq.com>\r\n"
        b"Subject: HTML in plain part\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"<html><head><style>.hidden{display:none}</style></head>"
        b"<body><p>Hello&nbsp;Wuxian</p><div>Line two<br>Line three</div>"
        b"<script>alert('ignored')</script></body></html>\r\n"
    )

    class FakeImap:
        def uid(self, command, uid, query):
            return "OK", [(b"124 (FLAGS ())", raw_message)]

    client = MailClient(
        MailConfig(
            address="you@qq.com",
            imap_host="imap.qq.com",
            imap_port=993,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            auth_code="secret",
        )
    )

    message = client._fetch_uid(FakeImap(), b"124")

    assert message is not None
    assert message.body == "Hello Wuxian\n\nLine two\nLine three"
    assert "<html>" not in message.body
    assert "display:none" not in message.body
    assert "alert" not in message.body


def test_fetch_uid_uses_safe_text_from_html_only_message():
    from qq_mail_agent_cli.config import MailConfig
    from qq_mail_agent_cli.mail_client import MailClient

    raw_message = (
        b"From: Sender <sender@example.com>\r\n"
        b"To: You <you@qq.com>\r\n"
        b"Subject: HTML only\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<table><tr><td>First</td><td>&amp; second</td></tr></table>\r\n"
    )

    class FakeImap:
        def uid(self, command, uid, query):
            return "OK", [(b"125 (FLAGS ())", raw_message)]

    client = MailClient(
        MailConfig(
            address="you@qq.com",
            imap_host="imap.qq.com",
            imap_port=993,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            auth_code="secret",
        )
    )

    message = client._fetch_uid(FakeImap(), b"125")

    assert message is not None
    assert message.body == "First& second"
    assert message.html_body.startswith("<table>")


def test_quote_mailbox_handles_spaces():
    assert mail_client._quote_mailbox("Deleted Messages") == '"Deleted Messages"'


def test_find_sent_mailbox_prefers_known_names():
    assert mail_client._find_sent_mailbox(["INBOX", "Sent Messages", "Trash"]) == "Sent Messages"
    assert mail_client._find_sent_mailbox(["INBOX", "已发送"]) == "已发送"
    assert mail_client._find_sent_mailbox(["INBOX"]) is None


def test_send_draft_uses_smtp_and_appends_sent_copy(monkeypatch):
    from qq_mail_agent_cli.config import MailConfig
    from qq_mail_agent_cli.mail_client import MailClient
    from qq_mail_agent_cli.models import Draft

    calls = []
    sent_messages = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, address, auth_code):
            calls.append(("login", address, auth_code))

        def send_message(self, message):
            sent_messages.append(message)

    class FakeImap:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list(self):
            calls.append(("list",))
            return "OK", [b'(\\HasNoChildren) "/" "Sent Messages"']

        def append(self, mailbox, flags, date_time, message_bytes):
            calls.append(("append", mailbox, flags, isinstance(date_time, str), b"Re: Hello" in message_bytes))
            return "OK", []

    monkeypatch.setattr(mail_client.smtplib, "SMTP_SSL", FakeSmtp)
    client = MailClient(
        MailConfig(
            address="you@qq.com",
            imap_host="imap.qq.com",
            imap_port=993,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            auth_code="secret",
        )
    )
    monkeypatch.setattr(client, "_connect_imap", lambda: FakeImap())
    draft = Draft(
        id="draft-1",
        mail_id="uid:1",
        to="sender@example.com",
        subject="Re: Hello",
        body="你好，这是一封测试回复。",
        reply_to_message_id="<source@example.com>",
        references="<root@example.com> <source@example.com>",
    )

    result = client.send_draft(draft, dry_run=False)

    assert result.saved_to_sent is True
    assert result.sent_mailbox == "Sent Messages"
    assert result.summary() == "Sent draft draft-1 to sender@example.com; saved to Sent Messages"
    assert calls == [
        ("connect", "smtp.qq.com", 465, 45),
        ("login", "you@qq.com", "secret"),
        ("list",),
        ("append", '"Sent Messages"', None, True, True),
    ]
    assert len(sent_messages) == 1
    message = sent_messages[0]
    assert message["From"] == "you@qq.com"
    assert message["To"] == "sender@example.com"
    assert message["Subject"] == "Re: Hello"
    assert message["Date"]
    assert message["Message-ID"]
    assert message["In-Reply-To"] == "<source@example.com>"
    assert message["References"] == "<root@example.com> <source@example.com>"
    assert "你好，这是一封测试回复。" in message.get_content()


def test_send_draft_reports_missing_sent_mailbox_without_resending(monkeypatch):
    from qq_mail_agent_cli.config import MailConfig
    from qq_mail_agent_cli.mail_client import MailClient
    from qq_mail_agent_cli.models import Draft

    calls = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, address, auth_code):
            calls.append(("login", address, auth_code))

        def send_message(self, message):
            calls.append(("send_message", message["To"]))

    class FakeImap:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list(self):
            calls.append(("list",))
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

    monkeypatch.setattr(mail_client.smtplib, "SMTP_SSL", FakeSmtp)
    client = MailClient(
        MailConfig(
            address="you@qq.com",
            imap_host="imap.qq.com",
            imap_port=993,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            auth_code="secret",
        )
    )
    monkeypatch.setattr(client, "_connect_imap", lambda: FakeImap())

    result = client.send_draft(
        Draft(
            id="draft-1",
            mail_id="uid:1",
            to="sender@example.com",
            subject="Re: Hello",
            body="body",
        ),
        dry_run=False,
    )

    assert result.saved_to_sent is False
    assert result.save_error is not None
    assert "sent mailbox not found" in result.save_error
    assert calls == [
        ("connect", "smtp.qq.com", 465, 45),
        ("login", "you@qq.com", "secret"),
        ("send_message", "sender@example.com"),
        ("list",),
    ]


def test_state_store_saves_triage_and_actions(tmp_path):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(
        id="uid:1",
        sender="sender@example.com",
        recipient="you@qq.com",
        subject="Subject",
        body="Full body should not be saved",
        is_seen=False,
    )
    result = TriageResult(
        mail_id="uid:1",
        classification=MailClassification.NOTIFY,
        reason="Needs attention",
        suggested_action=SuggestedAction.TRANSLATE,
        action_reason="English content.",
    )

    store.save_triage(message, result, model="test")
    store.log_action("triage", uid="uid:1", detail="notify")

    triage_rows = store.list_triage_results()
    assert len(triage_rows) == 1
    assert triage_rows[0].uid == "uid:1"
    assert triage_rows[0].classification == "notify"
    assert triage_rows[0].subject == "Subject"
    assert triage_rows[0].suggested_action == "translate"
    assert triage_rows[0].action_reason == "English content."

    loaded = store.get_triage_result("uid:1")
    assert loaded is not None
    assert loaded.suggested_action == "translate"
    assert loaded.queue_status == "pending"

    action_rows = store.list_actions()
    assert len(action_rows) == 1
    assert action_rows[0].action == "triage"


def test_state_store_lists_suggested_triage_queue_by_action_priority(tmp_path):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    cases = [
        ("uid:no_action", SuggestedAction.NO_ACTION),
        ("uid:mark_seen", SuggestedAction.MARK_SEEN),
        ("uid:draft_reply", SuggestedAction.DRAFT_REPLY),
        ("uid:move_to_trash", SuggestedAction.MOVE_TO_TRASH),
        ("uid:translate", SuggestedAction.TRANSLATE),
        ("uid:read_full", SuggestedAction.READ_FULL),
    ]
    for uid, action in cases:
        store.save_triage(
            MailMessage(id=uid, sender="sender@example.com", recipient="you@qq.com", subject=uid, body=""),
            TriageResult(
                mail_id=uid,
                classification=MailClassification.NOTIFY,
                reason=f"Reason {uid}",
                suggested_action=action,
                action_reason=f"Action {uid}",
            ),
            model="test",
        )

    rows = store.list_suggested_triage_queue(limit=10)

    assert [row.uid for row in rows] == [
        "uid:draft_reply",
        "uid:translate",
        "uid:read_full",
        "uid:mark_seen",
        "uid:move_to_trash",
        "uid:no_action",
    ]


def test_state_store_filters_suggested_triage_queue_by_status(tmp_path):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    for uid, action in [
        ("uid:pending", SuggestedAction.NO_ACTION),
        ("uid:later", SuggestedAction.DRAFT_REPLY),
        ("uid:done", SuggestedAction.DRAFT_REPLY),
        ("uid:skipped", SuggestedAction.DRAFT_REPLY),
    ]:
        store.save_triage(
            MailMessage(id=uid, sender="sender@example.com", recipient="you@qq.com", subject=uid, body=""),
            TriageResult(
                mail_id=uid,
                classification=MailClassification.NOTIFY,
                reason=f"Reason {uid}",
                suggested_action=action,
            ),
            model="test",
        )

    assert store.set_triage_queue_status("uid:later", "later") is True
    assert store.set_triage_queue_status("uid:done", "done") is True
    assert store.set_triage_queue_status("uid:skipped", "skipped") is True

    rows = store.list_suggested_triage_queue(limit=10)

    assert [row.uid for row in rows] == ["uid:pending", "uid:later"]
    assert [row.queue_status for row in rows] == ["pending", "later"]


def test_state_store_searches_mail_items_by_keyword_and_seen_status(tmp_path):
    from qq_mail_agent_cli.models import MailMessage
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_mail(
        MailMessage(
            id="uid:1",
            sender="alice@example.com",
            recipient="you@qq.com",
            subject="Interview schedule",
            body="",
            is_seen=False,
        )
    )
    store.upsert_mail(
        MailMessage(
            id="uid:2",
            sender="billing@example.com",
            recipient="you@qq.com",
            subject="Invoice paid",
            body="",
            is_seen=True,
        )
    )

    assert [row.uid for row in store.search_mail_items(keyword="Interview")] == ["uid:1"]
    assert [row.uid for row in store.search_mail_items(keyword="billing")] == ["uid:2"]
    assert [row.uid for row in store.search_mail_items(is_seen=False)] == ["uid:1"]
    assert [row.uid for row in store.search_mail_items(is_seen=True)] == ["uid:2"]


def test_state_store_searches_mail_items_by_classification_and_queue_status(tmp_path):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    respond_message = MailMessage(id="uid:1", sender="alice@example.com", recipient="you@qq.com", subject="Reply", body="")
    notify_message = MailMessage(id="uid:2", sender="notice@example.com", recipient="you@qq.com", subject="Notice", body="")
    store.save_triage(
        respond_message,
        TriageResult(
            mail_id="uid:1",
            classification=MailClassification.RESPOND,
            reason="Needs reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
        ),
        model="test",
    )
    store.save_triage(
        notify_message,
        TriageResult(mail_id="uid:2", classification=MailClassification.NOTIFY, reason="Read it."),
        model="test",
    )
    assert store.set_triage_queue_status("uid:1", "later") is True

    classification_rows = store.search_mail_items(classification="respond")
    status_rows = store.search_mail_items(queue_status="later")

    assert [row.uid for row in classification_rows] == ["uid:1"]
    assert classification_rows[0].classification == "respond"
    assert classification_rows[0].suggested_action == "draft_reply"
    assert [row.uid for row in status_rows] == ["uid:1"]
    assert status_rows[0].queue_status == "later"


def test_state_store_saves_full_draft(tmp_path):
    from qq_mail_agent_cli.models import Draft
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    body = "第一行回复。\n\n第二行回复，比 preview 更完整。"
    draft = Draft(
        id="ai-draft-uid:1",
        mail_id="uid:1",
        to="sender@example.com",
        subject="Re: Subject",
        body=body,
        reply_to_message_id="<source@example.com>",
        references="<root@example.com>",
    )

    store.save_draft(draft)

    rows = store.list_drafts()
    assert len(rows) == 1
    assert rows[0].draft_id == "ai-draft-uid:1"
    assert rows[0].body == body
    assert rows[0].body_preview != ""
    assert rows[0].reply_to_message_id == "<source@example.com>"
    assert rows[0].references == "<root@example.com>"

    loaded = store.get_draft("ai-draft-uid:1")
    assert loaded is not None
    assert loaded.body == body
    assert loaded.reply_to_message_id == "<source@example.com>"
    assert loaded.references == "<root@example.com>"

    store.mark_draft_sent("ai-draft-uid:1")
    assert store.list_drafts() == []
    assert store.list_drafts(include_sent=True)[0].sent_at is not None


def test_state_store_migrates_old_triage_schema(tmp_path):
    import sqlite3

    from qq_mail_agent_cli.storage import StateStore

    db_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE mail_items (
                uid TEXT PRIMARY KEY,
                sender TEXT,
                recipient TEXT,
                subject TEXT,
                date TEXT,
                is_seen INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE triage_results (
                uid TEXT PRIMARY KEY,
                classification TEXT NOT NULL,
                reason TEXT NOT NULL,
                model TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO mail_items(uid, sender, recipient, subject, created_at, updated_at)
            VALUES ('uid:old', 'sender@example.com', 'you@qq.com', 'Old subject', 'now', 'now');
            INSERT INTO triage_results(uid, classification, reason, model, created_at, updated_at)
            VALUES ('uid:old', 'notify', 'Old reason', 'test', 'now', 'now');
            """
        )

    store = StateStore(db_path)
    row = store.get_triage_result("uid:old")

    assert row is not None
    assert row.suggested_action == "read_full"
    assert row.action_reason == ""
    assert row.queue_status == "pending"


def test_state_store_migrates_old_drafts_to_send_lifecycle(tmp_path):
    import sqlite3

    from qq_mail_agent_cli.storage import StateStore

    db_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE drafts (
                draft_id TEXT PRIMARY KEY,
                uid TEXT,
                to_addr TEXT,
                subject TEXT,
                body TEXT,
                body_preview TEXT,
                reply_to_message_id TEXT,
                reference_ids TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT
            );
            INSERT INTO drafts(draft_id, uid, to_addr, subject, body, body_preview, created_at, sent_at)
            VALUES
                ('old-pending', 'uid:1', 'a@example.com', 'Pending', 'Body', 'Body', 'now', NULL),
                ('old-sent', 'uid:2', 'b@example.com', 'Sent', 'Body', 'Body', 'now', 'sent-time');
            """
        )

    store = StateStore(db_path)

    pending = store.get_draft("old-pending")
    sent = store.get_draft("old-sent")
    assert pending is not None and pending.send_status == "pending"
    assert pending.base_draft_id == "old-pending"
    assert pending.draft_version == 1
    assert sent is not None and sent.send_status == "sent"
    assert sent.sent_at == "sent-time"


def test_state_store_updates_draft_without_losing_thread_fields(tmp_path):
    from qq_mail_agent_cli.models import Draft
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    store.save_draft(
        Draft(
            id="ai-draft-uid:1",
            mail_id="uid:1",
            to="sender@example.com",
            subject="Re: Old",
            body="Old body",
            reply_to_message_id="<source@example.com>",
            references="<root@example.com>",
        )
    )

    assert store.update_draft("ai-draft-uid:1", subject="Re: New", body="New body") is True

    loaded = store.get_draft("ai-draft-uid:1")
    assert loaded is not None
    assert loaded.subject == "Re: New"
    assert loaded.body == "New body"
    assert loaded.body_preview == "New body"
    assert loaded.reply_to_message_id == "<source@example.com>"
    assert loaded.references == "<root@example.com>"

    store.mark_draft_sent("ai-draft-uid:1")
    assert store.update_draft("ai-draft-uid:1", subject="Nope", body="Nope") is False


def test_state_store_regenerated_draft_keeps_sent_version_history(tmp_path):
    from qq_mail_agent_cli.models import Draft
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    first = Draft(
        id="ai-draft-uid:1",
        mail_id="uid:1",
        to="sender@example.com",
        subject="Re: Old",
        body="Old body",
    )
    regenerated = Draft(
        id="ai-draft-uid:1",
        mail_id="uid:1",
        to="sender@example.com",
        subject="Re: New",
        body="New body",
    )

    store.save_draft(first)
    store.mark_draft_sent("ai-draft-uid:1")
    assert store.list_drafts() == []

    second = store.save_draft(regenerated)

    rows = store.list_drafts()
    assert len(rows) == 1
    assert rows[0].draft_id == "ai-draft-uid:1--v2"
    assert rows[0].subject == "Re: New"
    assert rows[0].sent_at is None
    assert rows[0].send_status == "pending"
    assert rows[0].supersedes_id == "ai-draft-uid:1"
    assert rows[0].draft_version == 2
    assert second == rows[0]

    all_rows = {draft.draft_id: draft for draft in store.list_drafts(status="all")}
    assert all_rows["ai-draft-uid:1"].send_status == "sent"
    assert all_rows["ai-draft-uid:1"].body == "Old body"
    assert all_rows["ai-draft-uid:1--v2"].body == "New body"


def test_state_store_lists_drafts_by_status(tmp_path):
    from qq_mail_agent_cli.models import Draft
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    store.save_draft(
        Draft(
            id="pending-draft",
            mail_id="uid:1",
            to="sender@example.com",
            subject="Re: Pending",
            body="Pending body",
        )
    )
    store.save_draft(
        Draft(
            id="sent-draft",
            mail_id="uid:2",
            to="sender@example.com",
            subject="Re: Sent",
            body="Sent body",
        )
    )
    store.mark_draft_sent("sent-draft")

    assert [draft.draft_id for draft in store.list_drafts(status="pending")] == ["pending-draft"]
    assert [draft.draft_id for draft in store.list_drafts(status="sent")] == ["sent-draft"]
    assert {draft.draft_id for draft in store.list_drafts(status="all")} == {"pending-draft", "sent-draft"}
    assert {draft.draft_id for draft in store.list_drafts(include_sent=True)} == {"pending-draft", "sent-draft"}


def test_interactive_sent_draft_is_read_only(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import Draft
    from qq_mail_agent_cli.storage import StateStore

    class FakeClient:
        def send_draft(self, *args, **kwargs):
            raise AssertionError("should not send a sent draft")

    store = StateStore(tmp_path / "state.sqlite3")
    store.save_draft(
        Draft(
            id="sent-draft",
            mail_id="uid:1",
            to="sender@example.com",
            subject="Re: Sent",
            body="Sent body",
        )
    )
    store.mark_draft_sent("sent-draft")

    answers = iter(["", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._browse_drafts(FakeClient(), store, status="sent")

    output = capsys.readouterr().out
    assert "状态: 已发送" in output
    assert "已发送草稿只读" in output


def test_read_multiline_body_save(monkeypatch):
    answers = iter(["第一行", "第二行", ".save"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert interactive._read_multiline_body() == "第一行\n第二行"


def test_read_multiline_body_cancel(monkeypatch):
    answers = iter(["第一行", ".cancel"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert interactive._read_multiline_body() is None


def test_state_store_filters_triage_results(tmp_path):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    notify_message = MailMessage(id="uid:1", sender="a", recipient="you", subject="Notify", body="")
    respond_message = MailMessage(id="uid:2", sender="b", recipient="you", subject="Respond", body="")
    store.save_triage(
        notify_message,
        TriageResult(mail_id="uid:1", classification=MailClassification.NOTIFY, reason="notice"),
        model="test",
    )
    store.save_triage(
        respond_message,
        TriageResult(mail_id="uid:2", classification=MailClassification.RESPOND, reason="reply"),
        model="test",
    )

    rows = store.list_triage_results(classification="respond")
    assert len(rows) == 1
    assert rows[0].uid == "uid:2"


def test_show_stored_triage_uses_chinese_block_output(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(
        id="uid:1",
        sender="sender@example.com",
        recipient="you@qq.com",
        subject="Subject",
        body="body",
    )
    result = TriageResult(
        mail_id="uid:1",
        classification=MailClassification.RESPOND,
        reason="Need action",
        suggested_action=SuggestedAction.DRAFT_REPLY,
        action_reason="The sender asks for confirmation.",
    )
    store.save_triage(message, result, model="test")

    monkeypatch.setattr("builtins.input", lambda prompt: "")
    interactive._show_stored_triage(store)
    output = capsys.readouterr().out
    assert "[1] uid:1" in output
    assert "分类: 需要处理" in output
    assert "建议: 生成回复草稿" in output
    assert "建议原因: The sender asks for confirmation." in output
    assert "主题: Subject" in output
    assert "uid:1\trespond" not in output


def test_interactive_translate_message_requires_confirmation(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage

    class FakeClient:
        def get_real_message(self, mail_id):
            return MailMessage(
                id=mail_id,
                sender="sender@example.com",
                recipient="you@qq.com",
                subject="Invitation",
                body="Please join.",
            )

    class FakeStore:
        def upsert_mail(self, message):
            raise AssertionError("should not write state before confirmation")

        def log_action(self, action, *, uid=None, detail=""):
            raise AssertionError("should not log before confirmation")

    answers = iter(["uid:1", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: (_ for _ in ()).throw(AssertionError("should not build agent")))

    interactive._translate_message_flow(FakeClient(), FakeStore())

    assert "中文翻译" not in capsys.readouterr().out


def test_interactive_translate_message_logs_action_without_translation_body(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage, MailTranslation

    actions = []
    upserted = []

    class FakeClient:
        def get_real_message(self, mail_id):
            return MailMessage(
                id=mail_id,
                sender="sender@example.com",
                recipient="you@qq.com",
                subject="Invitation",
                body="Please join.",
                is_seen=False,
            )

    class FakeStore:
        def upsert_mail(self, message):
            upserted.append(message.id)

        def log_action(self, action, *, uid=None, detail=""):
            actions.append((action, uid, detail))

    class FakeAgent:
        def translate_message(self, message):
            return MailTranslation(
                mail_id=message.id,
                subject_zh="邀请",
                body_zh="请参加。",
            )

    answers = iter(["uid:1", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: FakeAgent())

    interactive._translate_message_flow(FakeClient(), FakeStore())

    output = capsys.readouterr().out
    assert "中文主题: 邀请" in output
    assert "请参加。" in output
    assert upserted == ["uid:1"]
    assert actions == [("translate", "uid:1", "Invitation")]
    assert "请参加。" not in actions[0][2]


def test_message_workbench_selects_message_and_returns(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    calls = []

    class FakeClient:
        def list_real_recent(self, limit, *, offset=0):
            calls.append(("list", limit, offset))
            return [
                MailMessage(id="uid:1", sender="a", recipient="you", subject="one", body="summary"),
                MailMessage(id="uid:2", sender="b", recipient="you", subject="two", body="summary"),
            ]

        def get_real_message(self, mail_id):
            calls.append(("get", mail_id))
            return MailMessage(id=mail_id, sender="a", recipient="you", subject="Full", body="Full body")

    store = StateStore(tmp_path / "state.sqlite3")
    store.save_triage(
        MailMessage(id="uid:1", sender="a", recipient="you", subject="one", body="summary"),
        TriageResult(
            mail_id="uid:1",
            classification=MailClassification.RESPOND,
            reason="Needs reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
            action_reason="The sender asks a question.",
        ),
        model="test",
    )

    answers = iter(["2", "", "1", "0", "q", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._message_workbench_flow(FakeClient(), store)

    output = capsys.readouterr().out
    assert "1. 按 AI 建议处理" in output
    assert "2. 查看最近邮件" in output
    assert "邮件处理面板 - 第 1 页" in output
    assert "邮件处理: uid:1" in output
    assert "AI 建议: 生成回复草稿" in output
    assert "队列状态: 待处理" in output
    assert "建议原因: The sender asks a question." in output
    assert ("get", "uid:1") in calls


def test_message_workbench_routes_submenu_choices(monkeypatch):
    calls = []

    monkeypatch.setattr(interactive, "_suggestion_queue_flow", lambda client, store: calls.append(("suggestions", client, store)))
    monkeypatch.setattr(interactive, "_browse_recent_messages_for_workbench", lambda client, store: calls.append(("recent", client, store)))
    monkeypatch.setattr(interactive, "_queue_history_flow", lambda store: calls.append(("history", store)))
    monkeypatch.setattr(interactive, "_mail_search_flow", lambda client, store: calls.append(("search", client, store)))

    client = object()
    store = object()
    answers = iter(["1", "2", "3", "4", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._message_workbench_flow(client, store)

    assert calls == [
        ("suggestions", client, store),
        ("recent", client, store),
        ("history", store),
        ("search", client, store),
    ]


def test_suggestion_queue_empty_shows_hint(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    interactive._suggestion_queue_flow(object(), store)

    assert "暂无 AI 建议。请先返回主菜单选择 2 分类最近邮件。" in capsys.readouterr().out


def test_suggestion_queue_selects_message_and_enters_actions(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    calls = []

    class FakeClient:
        def get_real_message(self, mail_id):
            calls.append(("get", mail_id))
            return MailMessage(id=mail_id, sender="sender", recipient="you", subject="Full", body="Full body")

    store = StateStore(tmp_path / "state.sqlite3")
    store.save_triage(
        MailMessage(id="uid:1", sender="sender", recipient="you", subject="Need reply", body="summary"),
        TriageResult(
            mail_id="uid:1",
            classification=MailClassification.RESPOND,
            reason="Needs a reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
            action_reason="The sender asks a question.",
        ),
        model="test",
    )

    answers = iter(["", "1", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._suggestion_queue_flow(FakeClient(), store)

    output = capsys.readouterr().out
    assert "AI 建议队列" in output
    assert "[1] uid:1 [待处理]" in output
    assert "建议: 生成回复草稿" in output
    assert "分类: 需要处理" in output
    assert "邮件处理: uid:1" in output
    assert calls == [("get", "uid:1")]


def test_message_actions_can_mark_queue_status_later(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Subject", body="Body")
    store.save_triage(
        message,
        TriageResult(mail_id="uid:1", classification=MailClassification.NOTIFY, reason="Read later."),
        model="test",
    )

    monkeypatch.setattr("builtins.input", lambda prompt="": "7")

    assert interactive._message_actions_flow(object(), store, message) is False

    row = store.get_triage_result("uid:1")
    assert row is not None
    assert row.queue_status == "later"
    assert "AI 建议队列状态已更新为: 稍后处理" in capsys.readouterr().out


def test_message_actions_can_skip_queue_item(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Subject", body="Body")
    store.save_triage(
        message,
        TriageResult(mail_id="uid:1", classification=MailClassification.NOTIFY, reason="Ignore this."),
        model="test",
    )

    monkeypatch.setattr("builtins.input", lambda prompt="": "8")

    assert interactive._message_actions_flow(object(), store, message) is False

    row = store.get_triage_result("uid:1")
    assert row is not None
    assert row.queue_status == "skipped"
    assert store.list_suggested_triage_queue() == []
    assert "AI 建议队列状态已更新为: 已跳过" in capsys.readouterr().out


def test_queue_history_empty_shows_status_hint(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    answers = iter(["1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._queue_history_flow(store)

    output = capsys.readouterr().out
    assert "队列记录" in output
    assert "暂无已处理队列记录。" in output


def test_queue_history_can_restore_skipped_to_pending(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Skipped subject", body="")
    store.save_triage(
        message,
        TriageResult(mail_id="uid:1", classification=MailClassification.NOTIFY, reason="Skipped by mistake."),
        model="test",
    )
    assert store.set_triage_queue_status("uid:1", "skipped") is True

    answers = iter(["2", "", "1", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._queue_history_flow(store)

    row = store.get_triage_result("uid:1")
    assert row is not None
    assert row.queue_status == "pending"
    assert [item.uid for item in store.list_suggested_triage_queue()] == ["uid:1"]
    output = capsys.readouterr().out
    assert "队列记录 - 已跳过" in output
    assert "[1] uid:1 [已跳过]" in output
    assert "AI 建议队列状态已更新为: 待处理" in output


def test_queue_history_can_move_done_to_later(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Done subject", body="")
    store.save_triage(
        message,
        TriageResult(mail_id="uid:1", classification=MailClassification.RESPOND, reason="Already handled."),
        model="test",
    )
    assert store.set_triage_queue_status("uid:1", "done") is True

    answers = iter(["1", "", "1", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._queue_history_flow(store)

    row = store.get_triage_result("uid:1")
    assert row is not None
    assert row.queue_status == "later"
    output = capsys.readouterr().out
    assert "队列记录 - 已处理" in output
    assert "AI 建议队列状态已更新为: 稍后处理" in output


def test_mail_search_empty_shows_hint(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    answers = iter(["1", "missing", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._mail_search_flow(object(), store)

    output = capsys.readouterr().out
    assert "搜索 / 筛选邮件" in output
    assert "暂无搜索结果。" in output


def test_mail_search_selects_result_and_enters_actions(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    calls = []

    class FakeClient:
        def get_real_message(self, mail_id):
            calls.append(("get", mail_id))
            return MailMessage(id=mail_id, sender="alice@example.com", recipient="you@qq.com", subject="Interview", body="Full body")

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(
        id="uid:1",
        sender="alice@example.com",
        recipient="you@qq.com",
        subject="Interview schedule",
        body="",
        is_seen=False,
    )
    store.save_triage(
        message,
        TriageResult(
            mail_id="uid:1",
            classification=MailClassification.RESPOND,
            reason="Needs reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
        ),
        model="test",
    )

    answers = iter(["1", "Interview", "", "1", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._mail_search_flow(FakeClient(), store)

    output = capsys.readouterr().out
    assert "搜索结果" in output
    assert "[1] uid:1 [未读] [待处理]" in output
    assert "分类:   需要处理" in output
    assert "建议:   生成回复草稿" in output
    assert "邮件处理: uid:1" in output
    assert calls == [("get", "uid:1")]


def test_mail_search_filters_by_queue_status(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Later", body="")
    store.save_triage(
        message,
        TriageResult(mail_id="uid:1", classification=MailClassification.NOTIFY, reason="Later."),
        model="test",
    )
    assert store.set_triage_queue_status("uid:1", "later") is True

    answers = iter(["5", "2", "", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    interactive._mail_search_flow(object(), store)

    output = capsys.readouterr().out
    assert "选择队列状态" in output
    assert "[1] uid:1 [未知] [稍后处理]" in output


def test_message_actions_translate_requires_confirmation(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage

    class FakeStore:
        def upsert_mail(self, message):
            raise AssertionError("should not write before translation confirmation")

        def log_action(self, action, *, uid=None, detail=""):
            raise AssertionError("should not log before translation confirmation")

    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Hello", body="Translate me")
    answers = iter(["2", "n", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: (_ for _ in ()).throw(AssertionError("should not build agent")))

    assert interactive._message_actions_flow(object(), FakeStore(), message) is False

    assert "中文翻译" not in capsys.readouterr().out


def test_message_actions_generates_draft(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import Draft, MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    class FakeAgent:
        def draft_reply(self, message):
            return Draft(
                id=f"draft-{message.id}",
                mail_id=message.id,
                to=message.sender,
                subject=f"Re: {message.subject}",
                body="Draft body",
            )

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="sender@example.com", recipient="you", subject="Question", body="Please reply")
    store.save_triage(
        message,
        TriageResult(
            mail_id="uid:1",
            classification=MailClassification.RESPOND,
            reason="Needs reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
        ),
        model="test",
    )
    answers = iter(["3", "y", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(interactive, "_ai_agent", lambda: FakeAgent())

    assert interactive._message_actions_flow(object(), store, message) is False

    drafts = store.list_drafts(status="pending")
    assert len(drafts) == 1
    assert drafts[0].draft_id == "draft-uid:1"
    actions = store.list_actions()
    assert any(action.action == "draft_generated" and action.uid == "uid:1" for action in actions)
    assert store.get_triage_result("uid:1").queue_status == "done"
    assert "已保存草稿" in capsys.readouterr().out


def test_message_actions_marks_seen_after_confirmation(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailClassification, MailMessage, SuggestedAction, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    calls = []

    class FakeClient:
        def mark_real_seen(self, mail_id):
            calls.append(mail_id)
            return True

    store = StateStore(tmp_path / "state.sqlite3")
    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Subject", body="Body", is_seen=False)
    store.save_triage(
        message,
        TriageResult(
            mail_id="uid:1",
            classification=MailClassification.NOTIFY,
            reason="Read it.",
            suggested_action=SuggestedAction.MARK_SEEN,
        ),
        model="test",
    )
    answers = iter(["4", "y", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert interactive._message_actions_flow(FakeClient(), store, message) is False

    assert calls == ["uid:1"]
    actions = store.list_actions()
    assert any(action.action == "mark_seen" and action.uid == "uid:1" for action in actions)
    assert store.get_triage_result("uid:1").queue_status == "done"
    assert "邮件处理: uid:1 [已读]" in capsys.readouterr().out


def test_message_actions_move_to_trash_requires_confirmation(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage

    class FakeClient:
        def move_real_to_trash(self, mail_ids):
            raise AssertionError("should not move before confirmation")

    class FakeStore:
        def upsert_mail(self, message):
            raise AssertionError("should not write before move confirmation")

        def log_action(self, action, *, uid=None, detail=""):
            raise AssertionError("should not log before move confirmation")

    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Subject", body="Body")
    answers = iter(["5", "n", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert interactive._message_actions_flow(FakeClient(), FakeStore(), message) is False

    assert "已取消" in capsys.readouterr().out


def test_message_actions_moves_to_trash_after_confirmation(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage

    actions = []

    class FakeClient:
        def move_real_to_trash(self, mail_ids):
            actions.append(("move", tuple(mail_ids)))
            return "Trash"

    class FakeStore:
        def upsert_mail(self, message):
            actions.append(("upsert", message.id))

        def log_action(self, action, *, uid=None, detail=""):
            actions.append((action, uid, detail))

    message = MailMessage(id="uid:1", sender="sender", recipient="you", subject="Subject", body="Body")
    answers = iter(["5", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert interactive._message_actions_flow(FakeClient(), FakeStore(), message) is True

    assert ("move", ("uid:1",)) in actions
    assert ("move_to_trash", "uid:1", "Subject -> Trash") in actions
    assert "已移动到垃圾箱: Trash" in capsys.readouterr().out


def test_bulk_draft_for_respond_messages_generates_multiple_drafts(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import Draft, MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    class FakeClient:
        def get_real_message(self, uid):
            return MailMessage(
                id=uid,
                sender=f"{uid}@example.com",
                recipient="you@qq.com",
                subject=f"Subject {uid}",
                body="Please reply.",
            )

    class FakeAgent:
        def draft_reply(self, message):
            return Draft(
                id=f"draft-{message.id}",
                mail_id=message.id,
                to=message.sender,
                subject=f"Re: {message.subject}",
                body=f"Reply to {message.id}",
            )

    store = StateStore(tmp_path / "state.sqlite3")
    for uid in ["uid:1", "uid:2"]:
        message = MailMessage(id=uid, sender="sender@example.com", recipient="you@qq.com", subject=uid, body="")
        store.save_triage(
            message,
            TriageResult(mail_id=uid, classification=MailClassification.RESPOND, reason="Need reply"),
            model="test",
        )

    answers = iter(["", "all", "y"])
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(interactive, "_ai_agent", lambda: FakeAgent())

    interactive._draft_for_respond_message(FakeClient(), store)

    draft_ids = {draft.draft_id for draft in store.list_drafts(status="pending")}
    assert draft_ids == {"draft-uid:1", "draft-uid:2"}
    assert {store.get_triage_result(uid).queue_status for uid in ["uid:1", "uid:2"]} == {"done"}
    confirm_prompts = [prompt for prompt in prompts if "DeepSeek" in prompt]
    assert confirm_prompts == ["确认将 2 封邮件内容发送给 DeepSeek 处理? [y/N]: "]
    output = capsys.readouterr().out
    assert "成功 2 封，失败 0 封" in output


def test_bulk_draft_continues_after_one_failure(tmp_path, monkeypatch, capsys):
    from qq_mail_agent_cli.models import Draft, MailClassification, MailMessage, TriageResult
    from qq_mail_agent_cli.storage import StateStore

    class FakeClient:
        def get_real_message(self, uid):
            if uid == "uid:2":
                raise RuntimeError("fetch failed")
            return MailMessage(
                id=uid,
                sender=f"{uid}@example.com",
                recipient="you@qq.com",
                subject=f"Subject {uid}",
                body="Please reply.",
            )

    class FakeAgent:
        def draft_reply(self, message):
            return Draft(
                id=f"draft-{message.id}",
                mail_id=message.id,
                to=message.sender,
                subject=f"Re: {message.subject}",
                body=f"Reply to {message.id}",
            )

    store = StateStore(tmp_path / "state.sqlite3")
    for uid in ["uid:1", "uid:2", "uid:3"]:
        message = MailMessage(id=uid, sender="sender@example.com", recipient="you@qq.com", subject=uid, body="")
        store.save_triage(
            message,
            TriageResult(mail_id=uid, classification=MailClassification.RESPOND, reason="Need reply"),
            model="test",
        )
    rows = store.list_triage_results(limit=20, classification="respond")

    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    monkeypatch.setattr(interactive, "_ai_agent", lambda: FakeAgent())

    interactive._draft_for_selected_respond_messages(FakeClient(), store, rows, [1, 2, 3])

    draft_ids = {draft.draft_id for draft in store.list_drafts(status="pending")}
    assert "draft-uid:2" not in draft_ids
    assert len(draft_ids) == 2
    actions = store.list_actions(limit=10)
    assert any(action.action == "draft_failed" and action.uid == "uid:2" for action in actions)
    output = capsys.readouterr().out
    assert "成功 2 封，失败 1 封" in output
    assert "uid:2" in output


def test_interactive_browse_real_messages_uses_next_page(monkeypatch, capsys):
    from qq_mail_agent_cli.models import MailMessage

    calls = []

    class FakeClient:
        def list_real_recent(self, limit, *, offset=0):
            calls.append((limit, offset))
            if offset == 0:
                return [
                    MailMessage(id="uid:1", sender="a", recipient="you", subject="one", body="body"),
                    MailMessage(id="uid:2", sender="b", recipient="you", subject="two", body="body"),
                ]
            if offset == 2:
                return [
                    MailMessage(id="uid:3", sender="c", recipient="you", subject="three", body="body")
                ]
            return []

    class FakeStore:
        def upsert_mail(self, message):
            pass

    answers = iter(["2", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    interactive._browse_real_messages(FakeClient(), FakeStore())
    output = capsys.readouterr().out
    assert "第 1 页" in output
    assert "第 2 页" in output
    assert calls == [(2, 0), (2, 2)]

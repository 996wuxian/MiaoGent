from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

from fastapi.testclient import TestClient

from qq_mail_agent_cli.agent import MailAgent
from qq_mail_agent_cli.mail_client import MailClient
from qq_mail_agent_cli.models import (
    Draft,
    DraftSendResult,
    MailClassification,
    MailImportance,
    MailMessage,
    MailSummary,
    SuggestedAction,
    TriageResult,
)
from qq_mail_agent_cli.storage import StateStore
from qq_mail_agent_cli.web_server import create_app


class FakeMailClient:
    def __init__(self):
        self.messages = [
            MailMessage(
                id="uid:101",
                sender="alice@example.com",
                recipient="me@qq.com",
                subject="Interview question",
                body="Can you reply with your available time?",
                snippet="Can you reply with your available time?",
                is_seen=False,
                message_id="<m1@example.com>",
            ),
            MailMessage(
                id="uid:100",
                sender="news@example.com",
                recipient="me@qq.com",
                subject="Newsletter",
                body="Weekly links.",
                snippet="Weekly links.",
                is_seen=True,
            ),
        ]
        self.sent: list[Draft] = []
        self.marked_seen: list[str] = []
        self.moved: list[str] = []
        self.recent_calls: list[tuple[int, int]] = []
        self.detail_calls: list[str] = []

    def list_real_recent(self, limit: int, *, offset: int = 0):
        self.recent_calls.append((limit, offset))
        return self.messages[offset : offset + limit]

    def get_real_message(self, mail_id: str):
        self.detail_calls.append(mail_id)
        normalized = mail_id if mail_id.startswith("uid:") else f"uid:{mail_id}"
        return next((message for message in self.messages if message.id == normalized), None)

    def mark_real_seen(self, mail_id: str):
        self.marked_seen.append(mail_id)
        return True

    def move_real_to_trash(self, mail_ids: list[str]):
        self.moved.extend(mail_ids)
        return "Trash"

    def send_draft(self, draft: Draft, *, dry_run: bool = True):
        self.sent.append(draft)
        return DraftSendResult(draft_id=draft.id, to=draft.to, saved_to_sent=True, sent_mailbox="Sent")


class RecordingMailAgent(MailAgent):
    def __init__(
        self,
        *,
        results: dict[str, TriageResult] | None = None,
        failures: dict[str, Exception] | None = None,
    ):
        super().__init__()
        self.results = results or {}
        self.failures = failures or {}
        self.triage_calls: list[str] = []
        self.draft_calls: list[str] = []
        self.translation_calls: list[str] = []
        self.summary_calls: list[str] = []

    def triage(self, message: MailMessage) -> TriageResult:
        self.triage_calls.append(message.id)
        if message.id in self.failures:
            raise self.failures[message.id]
        return self.results.get(message.id) or super().triage(message)

    def draft_reply(self, message: MailMessage) -> Draft:
        self.draft_calls.append(message.id)
        return super().draft_reply(message)

    def translate_message(self, message: MailMessage):
        self.translation_calls.append(message.id)
        return super().translate_message(message)

    def summarize_message(self, message: MailMessage) -> MailSummary:
        self.summary_calls.append(message.id)
        return MailSummary(
            mail_id=message.id,
            summary_zh=f"{message.subject} 按需摘要",
            action_items=("查看正文要点",),
            confidence=0.82,
            reason="测试替身生成摘要。",
        )


def _client(
    tmp_path: Path,
    *,
    mail_client: FakeMailClient | None = None,
    agent: MailAgent | None = None,
):
    fake_client = mail_client or FakeMailClient()
    fake_agent = agent or MailAgent()
    store = StateStore(tmp_path / "state.sqlite3")
    app = create_app(
        mail_client_factory=lambda: fake_client,  # type: ignore[arg-type]
        agent_factory=lambda: fake_agent,
        state_store_factory=lambda: store,
    )
    return TestClient(app), fake_client, store


def test_web_recent_messages_store_metadata(tmp_path):
    client, _, store = _client(tmp_path)

    response = client.get("/api/messages/recent?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "uid:101"
    assert payload[0]["body"] == ""
    assert store.search_mail_items(keyword="Interview")[0].uid == "uid:101"


def test_web_recent_messages_returns_json_error_on_mail_failure(tmp_path):
    class FailingMailClient(FakeMailClient):
        def list_real_recent(self, limit: int, *, offset: int = 0):
            raise RuntimeError("QQ IMAP connection failed.")

    client, _, _ = _client(tmp_path, mail_client=FailingMailClient())

    response = client.get("/api/messages/recent?limit=2")

    assert response.status_code == 502
    assert response.json()["detail"] == "QQ IMAP connection failed."


def test_web_recent_messages_returns_json_error_on_unexpected_mail_failure(tmp_path):
    class FailingMailClient(FakeMailClient):
        def list_real_recent(self, limit: int, *, offset: int = 0):
            raise ValueError("SEARCH illegal in state AUTH")

    client, _, _ = _client(tmp_path, mail_client=FailingMailClient())

    response = client.get("/api/messages/recent?limit=2")

    assert response.status_code == 502
    assert "邮箱列表暂时无法读取" in response.json()["detail"]


def test_desktop_auth_error_keeps_cors_headers(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    app = create_app(
        mail_client_factory=FakeMailClient,  # type: ignore[arg-type]
        agent_factory=MailAgent,
        state_store_factory=lambda: store,
        session_token="x" * 32,
    )
    client = TestClient(app)

    response = client.get(
        "/api/messages/recent?limit=2",
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_web_message_detail_includes_body(tmp_path):
    client, _, _ = _client(tmp_path)

    response = client.get("/api/messages/101")

    assert response.status_code == 200
    assert response.json()["body"] == "Can you reply with your available time?"


def test_web_generates_summary_on_demand_for_normal_mail(tmp_path):
    agent = RecordingMailAgent()
    client, _, store = _client(tmp_path, agent=agent)

    response = client.post("/api/messages/101/summary", json={"confirmed": False})

    assert response.status_code == 200
    payload = response.json()
    assert payload["uid"] == "uid:101"
    assert payload["analysis_status"] == "analyzed"
    assert payload["summary_zh"] == "Interview question 按需摘要"
    assert payload["analysis_error"] is None
    assert payload["ai_audit"]["privacy_level"] == "normal"
    assert payload["ai_audit"]["title_classification"]["sent_to_ai"] is False
    assert payload["ai_audit"]["body_summary"]["status"] == "generated"
    assert payload["ai_audit"]["body_summary"]["sent_to_ai"] is True
    assert payload["ai_audit"]["body_policy"]["status"] == "allowed"
    assert agent.summary_calls == ["uid:101"]
    stored = store.get_mail_insight("uid:101")
    assert stored is not None
    assert stored.summary_zh == "Interview question 按需摘要"


def test_web_summary_requires_confirmation_for_sensitive_title(tmp_path):
    fake_client = FakeMailClient()
    fake_client.messages[0] = MailMessage(
        id="uid:101",
        sender="hr@example.com",
        recipient="me@qq.com",
        subject="录用通知 Offer Letter",
        body="请确认薪资待遇和身份证信息。",
        snippet="录用通知",
        is_seen=False,
    )
    agent = RecordingMailAgent()
    client, _, store = _client(tmp_path, mail_client=fake_client, agent=agent)

    response = client.post("/api/messages/101/summary", json={"confirmed": False})

    assert response.status_code == 409
    assert "生成摘要会把正文发送给 AI" in response.json()["detail"]
    assert agent.summary_calls == []
    assert store.get_mail_insight("uid:101") is None


def test_web_summary_allows_sensitive_title_after_confirmation(tmp_path):
    fake_client = FakeMailClient()
    fake_client.messages[0] = MailMessage(
        id="uid:101",
        sender="hr@example.com",
        recipient="me@qq.com",
        subject="录用通知 Offer Letter",
        body="请确认薪资待遇。",
        snippet="录用通知",
        is_seen=False,
    )
    agent = RecordingMailAgent()
    client, _, store = _client(tmp_path, mail_client=fake_client, agent=agent)

    response = client.post("/api/messages/101/summary", json={"confirmed": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_status"] == "analyzed"
    assert payload["analysis_error"] == "privacy_sensitive"
    assert payload["summary_zh"] == "录用通知 Offer Letter 按需摘要"
    assert payload["ai_audit"]["privacy_level"] == "sensitive"
    assert payload["ai_audit"]["body_summary"]["status"] == "generated"
    assert payload["ai_audit"]["body_summary"]["sent_to_ai"] is True
    assert payload["ai_audit"]["body_policy"]["status"] == "confirmed_once"
    assert "后续正文 AI 操作仍需谨慎" in payload["ai_audit"]["body_policy"]["description"]
    assert agent.summary_calls == ["uid:101"]
    stored = store.get_mail_insight("uid:101")
    assert stored is not None
    assert stored.analysis_error == "privacy_sensitive"


def test_web_risky_actions_require_confirmation(tmp_path):
    client, _, _ = _client(tmp_path)

    response = client.post("/api/messages/101/draft", json={"confirmed": False})

    assert response.status_code == 400


def test_web_triage_recent_skips_seen_and_saves_results(tmp_path):
    client, _, store = _client(tmp_path)

    response = client.post("/api/triage/recent", json={"confirmed": True, "limit": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["skipped_seen"] == 1
    assert payload["processed"][0]["classification"] == "respond"
    assert store.get_triage_result("uid:101") is not None


def test_web_triage_recent_blocks_sensitive_mail_before_ai(tmp_path):
    fake_client = FakeMailClient()
    fake_client.messages = [
        MailMessage(
            id="uid:888",
            sender="hr@example.com",
            recipient="me@qq.com",
            subject="Offer Letter",
            body="请查看附件中的入职录用通知书。",
            snippet="入职录用通知书",
            is_seen=False,
        )
    ]
    agent = RecordingMailAgent()
    client, _, store = _client(tmp_path, mail_client=fake_client, agent=agent)

    response = client.post("/api/triage/recent", json={"confirmed": True, "limit": 1})

    assert response.status_code == 200
    assert response.json()["processed"] == []
    assert agent.triage_calls == []
    insight = store.get_mail_insight("uid:888")
    assert insight is not None
    assert insight.analysis_status == "review_required"
    assert "阻止发送给 DeepSeek" in insight.summary_zh
    detail = client.get("/api/insights/888")
    assert detail.status_code == 200
    audit = detail.json()["ai_audit"]
    assert audit["privacy_level"] == "sensitive"
    assert audit["body_summary"]["status"] == "not_generated"
    assert audit["body_summary"]["sent_to_ai"] is False
    assert audit["body_policy"]["status"] == "confirmation_required"


def test_web_triage_queue_can_include_history_statuses(tmp_path):
    client, _, _ = _client(tmp_path)
    assert client.post("/api/triage/recent", json={"confirmed": True, "limit": 2}).status_code == 200
    assert client.post("/api/triage/101/status", json={"status": "done"}).status_code == 200

    default_queue = client.get("/api/triage/queue")
    history = client.get("/api/triage/queue?statuses=done")

    assert default_queue.status_code == 200
    assert default_queue.json() == []
    assert history.status_code == 200
    assert history.json()[0]["uid"] == "uid:101"
    assert history.json()[0]["queue_status"] == "done"


def test_web_insights_include_queue_status_for_processed_filtering(tmp_path):
    message = MailMessage(
        id="uid:109",
        sender="hr@example.com",
        recipient="me@qq.com",
        subject="招聘沟通",
        body="请回复面试时间。",
    )
    client, _, store = _client(tmp_path)
    store.save_triage(
        message,
        TriageResult(
            mail_id=message.id,
            classification=MailClassification.RESPOND,
            reason="Needs reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
            action_reason="Prepare a reply.",
            importance=MailImportance.IMPORTANT,
            needs_reply=True,
        ),
        model="test",
    )
    assert store.set_triage_queue_status("uid:109", "done")

    response = client.get("/api/insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["uid"] == "uid:109"
    assert payload[0]["queue_status"] == "done"


def test_web_can_update_mail_insight_labels(tmp_path):
    message = MailMessage(
        id="uid:110",
        sender="hr@example.com",
        recipient="me@qq.com",
        subject="招聘沟通",
        body="请回复面试时间。",
    )
    client, _, store = _client(tmp_path)
    store.save_triage(
        message,
        TriageResult(
            mail_id=message.id,
            classification=MailClassification.IGNORE,
            reason="Initial low priority.",
            suggested_action=SuggestedAction.NO_ACTION,
            action_reason="No action initially.",
            importance=MailImportance.GENERAL,
            needs_reply=False,
        ),
        model="test",
    )

    response = client.patch(
        "/api/insights/110/labels",
        json={"importance": "urgent", "needs_reply": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["importance"] == "urgent"
    assert payload["needs_reply"] is True
    assert payload["reply_status"] == "needs_reply"
    assert payload["notification_status"] == "pending"
    insight = store.get_mail_insight("uid:110")
    assert insight is not None
    assert insight.importance == "urgent"
    assert insight.needs_reply is True


def test_web_can_save_latest_mail_insight_feedback(tmp_path):
    message = MailMessage(
        id="uid:111",
        sender="hr@example.com",
        recipient="me@qq.com",
        subject="招聘沟通",
        body="请回复面试时间。",
    )
    client, _, store = _client(tmp_path)
    store.save_triage(
        message,
        TriageResult(
            mail_id=message.id,
            classification=MailClassification.RESPOND,
            reason="Needs reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
            action_reason="Prepare a reply.",
            importance=MailImportance.IMPORTANT,
            needs_reply=True,
        ),
        model="test",
    )

    first = client.post("/api/insights/111/feedback", json={"feedback": "correct"})
    second = client.post("/api/insights/111/feedback", json={"feedback": "wrong", "comment": "应该是紧急"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["feedback"] == "wrong"
    assert second.json()["comment"] == "应该是紧急"
    stored = store.get_latest_mail_insight_feedback("uid:111")
    assert stored is not None
    assert stored.feedback == "wrong"
    insight_response = client.get("/api/insights/111")
    assert insight_response.status_code == 200
    assert insight_response.json()["latest_feedback"] == "wrong"


def test_desktop_reset_recognition_cache_clears_ai_state_but_keeps_mail_and_drafts(tmp_path):
    client, _, store = _client(tmp_path)
    message = MailMessage(
        id="uid:113",
        sender="hr@example.com",
        recipient="me@qq.com",
        subject="Offer discussion",
        body="Please reply.",
    )
    store.save_triage(
        message,
        TriageResult(
            mail_id=message.id,
            classification=MailClassification.RESPOND,
            reason="Needs reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
            action_reason="Prepare a reply.",
            importance=MailImportance.IMPORTANT,
            needs_reply=True,
            summary_zh="需要回复的 offer 邮件。",
            confidence=0.9,
            priority_reason="招聘沟通。",
        ),
        model="test",
        uid_validity=5,
    )
    store.save_mail_insight_feedback(message.id, feedback="wrong", comment="应重新识别")
    store.set_triage_queue_status(message.id, "done")
    store.save_draft(Draft(id="draft-113", mail_id=message.id, to="hr@example.com", subject="Re: Offer", body="Thanks."))
    store.save_sync_state("INBOX", uid_validity=5, last_processed_uid=113)
    store.record_fetch_failure("INBOX", uid_validity=5, uid=114, quarantine_after=1)
    store.save_startup_summary(
        {
            "trigger": "startup",
            "new_count": 1,
            "processed_count": 1,
            "important_count": 1,
            "urgent_count": 0,
            "reply_count": 1,
            "draft_ready_count": 0,
            "general_count": 0,
            "failed_count": 0,
            "has_more": False,
            "items": [],
            "failures": [],
        }
    )
    assert store.acquire_sync_lease("test-owner")

    response = client.post("/api/desktop/reset-recognition-cache")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mail_insights"] == 1
    assert payload["triage_results"] == 1
    assert payload["mail_insight_feedback"] == 1
    assert payload["mail_fetch_failures"] == 1
    assert payload["desktop_summaries"] == 1
    assert payload["mailbox_sync_state"] == 1
    assert payload["sync_leases"] == 1
    assert payload["total_removed"] == 7
    assert store.list_mail_insights() == []
    assert store.list_triage_results() == []
    assert store.get_latest_mail_insight_feedback(message.id) is None
    assert store.get_sync_state() is None
    assert store.list_quarantined_fetch_failures(uid_validity=5) == []
    assert store.search_mail_items(keyword="Offer")[0].uid == message.id
    assert store.list_drafts(status="all")[0].uid == message.id
    assert store.list_actions(1)[0].action == "reset_recognition_cache"


def test_web_rejects_invalid_mail_insight_feedback(tmp_path):
    message = MailMessage(
        id="uid:112",
        sender="hr@example.com",
        recipient="me@qq.com",
        subject="招聘沟通",
        body="请回复面试时间。",
    )
    client, _, store = _client(tmp_path)
    store.save_triage(
        message,
        TriageResult(
            mail_id=message.id,
            classification=MailClassification.RESPOND,
            reason="Needs reply.",
            suggested_action=SuggestedAction.DRAFT_REPLY,
            action_reason="Prepare a reply.",
            importance=MailImportance.IMPORTANT,
            needs_reply=True,
        ),
        model="test",
    )

    response = client.post("/api/insights/112/feedback", json={"feedback": "maybe"})

    assert response.status_code == 400


def test_web_secretary_inspection_requires_confirmation(tmp_path):
    agent = RecordingMailAgent()
    client, fake_client, _ = _client(tmp_path, agent=agent)

    response = client.post("/api/secretary/inspection", json={"confirmed": False})

    assert response.status_code == 400
    assert fake_client.recent_calls == []
    assert agent.triage_calls == []


def test_web_secretary_inspection_hides_top_level_mail_error(tmp_path):
    class FailingMailClient(FakeMailClient):
        def __init__(self):
            super().__init__()
            self.fail_next_request = True

        def list_real_recent(self, limit: int, *, offset: int = 0):
            if self.fail_next_request:
                self.fail_next_request = False
                raise RuntimeError("IMAP failed while handling Customer secret body api-key=secret")
            return super().list_real_recent(limit, offset=offset)

    client, _, _ = _client(tmp_path, mail_client=FailingMailClient())

    response = client.post("/api/secretary/inspection", json={"confirmed": True})

    assert response.status_code == 502
    assert response.json()["detail"] == "巡检暂时无法完成，请稍后重试"
    assert "Customer secret" not in response.text
    assert "api-key" not in response.text

    retried = client.post(
        "/api/secretary/inspection",
        json={"confirmed": True, "limit": 1},
    )

    assert retried.status_code == 200
    assert retried.json()["scanned_count"] == 1


def test_web_secretary_inspection_rejects_concurrent_run(tmp_path):
    entered = Event()
    release = Event()

    class BlockingMailAgent(RecordingMailAgent):
        def triage(self, message: MailMessage) -> TriageResult:
            entered.set()
            assert release.wait(timeout=5)
            return super().triage(message)

    agent = BlockingMailAgent()
    client, _, _ = _client(tmp_path, agent=agent)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            client.post,
            "/api/secretary/inspection",
            json={"confirmed": True, "limit": 1},
        )
        entered_in_time = entered.wait(timeout=5)
        if not entered_in_time:
            release.set()
        assert entered_in_time
        try:
            second_response = client.post(
                "/api/secretary/inspection",
                json={"confirmed": True, "limit": 1},
            )
        finally:
            release.set()
        first_response = first.result(timeout=5)

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "巡检正在进行，请稍后再试"
    assert agent.triage_calls == ["uid:101"]


def test_web_secretary_inspection_filters_and_deduplicates_current_queue(tmp_path):
    fake_client = FakeMailClient()
    new_message = MailMessage(
        id="uid:201",
        sender="new@example.com",
        recipient="me@qq.com",
        subject="Please reply",
        body="Please reply today.",
        is_seen=False,
    )
    seen_message = MailMessage(
        id="uid:202",
        sender="seen@example.com",
        recipient="me@qq.com",
        subject="Already read",
        body="No inspection needed.",
        is_seen=True,
    )
    existing_message = MailMessage(
        id="uid:203",
        sender="ops@example.com",
        recipient="me@qq.com",
        subject="Deployment completed",
        body="The deployment completed.",
        is_seen=False,
    )
    fake_client.messages = [new_message, seen_message, existing_message, new_message]
    agent = RecordingMailAgent()
    client, _, store = _client(tmp_path, mail_client=fake_client, agent=agent)
    store.save_triage(
        existing_message,
        TriageResult(
            mail_id=existing_message.id,
            classification=MailClassification.NOTIFY,
            reason="Existing local result.",
            suggested_action=SuggestedAction.READ_FULL,
            action_reason="Review the status update.",
        ),
        model="test",
    )
    store.set_triage_queue_status(existing_message.id, "later")

    response = client.post(
        "/api/secretary/inspection",
        json={"confirmed": True, "limit": 4},
    )

    assert response.status_code == 200
    payload = response.json()
    assert fake_client.recent_calls == [(4, 0)]
    assert agent.triage_calls == ["uid:201"]
    assert payload["scanned_count"] == 4
    assert payload["processed_count"] == 1
    assert payload["skipped_seen"] == 1
    assert payload["skipped_triaged"] == 2
    assert payload["failed_count"] == 0
    items = [item for group in payload["groups"] for item in group["items"]]
    assert [item["uid"] for item in items].count("uid:201") == 1
    assert [item["uid"] for item in items].count("uid:203") == 1
    existing_item = next(item for item in items if item["uid"] == "uid:203")
    assert existing_item["reason"] == "Existing local result."
    assert existing_item["queue_status"] == "later"


def test_web_secretary_inspection_continues_after_single_mail_failure(tmp_path):
    fake_client = FakeMailClient()
    failed_message = MailMessage(
        id="uid:301",
        sender="failed@example.com",
        recipient="me@qq.com",
        subject="Failure candidate",
        body="This classification will fail.",
        is_seen=False,
    )
    successful_message = MailMessage(
        id="uid:302",
        sender="success@example.com",
        recipient="me@qq.com",
        subject="Reply requested",
        body="Please reply.",
        is_seen=False,
    )
    fake_client.messages = [failed_message, successful_message]
    agent = RecordingMailAgent(failures={failed_message.id: RuntimeError("temporary model failure")})
    client, _, store = _client(tmp_path, mail_client=fake_client, agent=agent)

    response = client.post(
        "/api/secretary/inspection",
        json={"confirmed": True, "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert agent.triage_calls == ["uid:301", "uid:302"]
    assert payload["processed_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["failures"] == [
        {
            "uid": "uid:301",
            "subject": "Failure candidate",
            "error": "RuntimeError: 本封邮件分析失败，请稍后重试",
        }
    ]
    assert store.get_triage_result("uid:301") is None
    assert store.get_triage_result("uid:302") is not None


def test_web_secretary_inspection_has_no_mailbox_or_draft_side_effects(tmp_path):
    agent = RecordingMailAgent()
    client, fake_client, store = _client(tmp_path, agent=agent)

    response = client.post("/api/secretary/inspection", json={"confirmed": True})

    assert response.status_code == 200
    assert fake_client.recent_calls == [(20, 0)]
    assert fake_client.detail_calls == []
    assert fake_client.marked_seen == []
    assert fake_client.moved == []
    assert fake_client.sent == []
    assert agent.draft_calls == []
    assert agent.translation_calls == []
    assert store.list_drafts(status="all") == []


def test_web_secretary_inspection_groups_once_and_counts_only_actionable_items(tmp_path):
    fake_client = FakeMailClient()
    fake_client.messages = [
        MailMessage(
            id="uid:400",
            sender="seen@example.com",
            recipient="me@qq.com",
            subject="Seen",
            body="Already read.",
            is_seen=True,
        )
    ]
    client, _, store = _client(tmp_path, mail_client=fake_client)
    seeded = [
        ("401", MailClassification.RESPOND, SuggestedAction.MARK_SEEN),
        ("402", MailClassification.NOTIFY, SuggestedAction.DRAFT_REPLY),
        ("403", MailClassification.NOTIFY, SuggestedAction.TRANSLATE),
        ("404", MailClassification.NOTIFY, SuggestedAction.MOVE_TO_TRASH),
        ("405", MailClassification.IGNORE, SuggestedAction.READ_FULL),
        ("406", MailClassification.NOTIFY, SuggestedAction.NO_ACTION),
        ("407", MailClassification.IGNORE, SuggestedAction.TRANSLATE),
    ]
    for suffix, classification, suggested_action in seeded:
        message = MailMessage(
            id=f"uid:{suffix}",
            sender=f"sender-{suffix}@example.com",
            recipient="me@qq.com",
            subject=f"Subject {suffix}",
            body="Stored locally.",
            is_seen=False,
        )
        store.save_triage(
            message,
            TriageResult(
                mail_id=message.id,
                classification=classification,
                reason=f"Reason {suffix}",
                suggested_action=suggested_action,
                action_reason=f"Action reason {suffix}",
            ),
            model="test",
        )

    response = client.post(
        "/api/secretary/inspection",
        json={"confirmed": True, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 0
    assert payload["skipped_seen"] == 1
    assert payload["current_actionable_count"] == 6
    assert [(group["key"], group["title"]) for group in payload["groups"]] == [
        ("reply", "需要回复"),
        ("review", "需要查看"),
        ("status", "状态处理建议"),
        ("no_action", "无需行动"),
    ]
    grouped_uids = {
        group["key"]: {item["uid"] for item in group["items"]}
        for group in payload["groups"]
    }
    assert grouped_uids == {
        "reply": {"uid:401", "uid:402"},
        "review": {"uid:403", "uid:405", "uid:407"},
        "status": {"uid:404"},
        "no_action": {"uid:406"},
    }
    all_uids = [item["uid"] for group in payload["groups"] for item in group["items"]]
    assert len(all_uids) == len(set(all_uids)) == 7


def test_web_secretary_inspection_logs_counts_without_mail_content(tmp_path):
    fake_client = FakeMailClient()
    sensitive_message = MailMessage(
        id="uid:501",
        sender="private-sender@example.com",
        recipient="me@qq.com",
        subject="Private acquisition subject",
        body="Customer secret body",
        is_seen=False,
    )
    fake_client.messages = [sensitive_message]
    agent = RecordingMailAgent(
        failures={sensitive_message.id: RuntimeError("provider failed while handling Customer secret body")}
    )
    client, _, store = _client(tmp_path, mail_client=fake_client, agent=agent)

    response = client.post(
        "/api/secretary/inspection",
        json={"confirmed": True, "limit": 1},
    )

    assert response.status_code == 200
    log = store.list_actions(1)[0]
    assert log.action == "secretary_inspection"
    assert log.uid is None
    assert log.detail == (
        "scanned_count=1, processed_count=0, skipped_seen=0, skipped_triaged=0, "
        "failed_count=1, current_actionable_count=0"
    )
    assert "private-sender" not in log.detail
    assert "Private acquisition" not in log.detail
    assert "Customer secret" not in log.detail
    failure = response.json()["failures"][0]
    assert failure["error"] == "RuntimeError: 本封邮件分析失败，请稍后重试"
    assert "Customer secret" not in failure["error"]


def test_web_secretary_inspection_blocks_sensitive_mail_before_ai(tmp_path):
    fake_client = FakeMailClient()
    fake_client.messages = [
        MailMessage(
            id="uid:777",
            sender="hr@example.com",
            recipient="me@qq.com",
            subject="入职录用通知",
            body="附件包含 offer 和劳动合同。",
            is_seen=False,
        )
    ]
    agent = RecordingMailAgent()
    client, _, store = _client(tmp_path, mail_client=fake_client, agent=agent)

    response = client.post("/api/secretary/inspection", json={"confirmed": True, "limit": 1})

    assert response.status_code == 200
    assert agent.triage_calls == []
    payload = response.json()
    assert payload["processed_count"] == 0
    assert payload["failed_count"] == 1
    assert payload["failures"][0]["error"].startswith("PrivacyProtected")
    insight = store.get_mail_insight("uid:777")
    assert insight is not None
    assert insight.analysis_status == "review_required"


def test_web_manual_draft_and_translation_block_sensitive_mail_before_ai(tmp_path):
    fake_client = FakeMailClient()
    fake_client.messages[0] = MailMessage(
        id="uid:101",
        sender="hr@example.com",
        recipient="me@qq.com",
        subject="录用通知 Offer Letter",
        body="请确认薪资待遇和身份证信息。",
        snippet="录用通知",
        is_seen=False,
    )
    agent = RecordingMailAgent()
    client, _, _ = _client(tmp_path, mail_client=fake_client, agent=agent)

    draft_response = client.post("/api/messages/101/draft", json={"confirmed": True})
    translate_response = client.post("/api/messages/101/translate", json={"confirmed": True})

    assert draft_response.status_code == 409
    assert translate_response.status_code == 409
    assert "隐私保护模式" in draft_response.json()["detail"]
    assert "隐私保护模式" in translate_response.json()["detail"]
    assert agent.draft_calls == []
    assert agent.translation_calls == []


def test_web_generates_draft_and_send_marks_sent(tmp_path):
    client, fake_client, store = _client(tmp_path)

    draft_response = client.post("/api/messages/101/draft", json={"confirmed": True})

    assert draft_response.status_code == 200
    draft_id = draft_response.json()["draft_id"]
    assert store.get_draft(draft_id) is not None

    send_response = client.post(f"/api/drafts/{draft_id}/send", json={"confirmed": True})

    assert send_response.status_code == 200
    assert send_response.json()["saved_to_sent"] is True
    assert fake_client.sent[0].id == draft_id
    assert store.get_draft(draft_id).sent_at is not None
    assert store.get_draft(draft_id).send_status == "sent"


def test_web_update_sent_draft_is_rejected(tmp_path):
    client, _, _ = _client(tmp_path)
    draft_id = client.post("/api/messages/101/draft", json={"confirmed": True}).json()["draft_id"]
    client.post(f"/api/drafts/{draft_id}/send", json={"confirmed": True})

    response = client.patch(f"/api/drafts/{draft_id}", json={"subject": "New", "body": "Body"})

    assert response.status_code == 404


def test_web_concurrent_send_only_delivers_once(tmp_path):
    entered = Event()
    release = Event()
    lock = Lock()

    class BlockingMailClient(FakeMailClient):
        def __init__(self):
            super().__init__()
            self.send_calls = 0

        def send_draft(self, draft: Draft, *, dry_run: bool = True):
            with lock:
                self.send_calls += 1
            entered.set()
            assert release.wait(timeout=5)
            return super().send_draft(draft, dry_run=dry_run)

    fake_client = BlockingMailClient()
    client, _, store = _client(tmp_path, mail_client=fake_client)
    draft_id = client.post("/api/messages/101/draft", json={"confirmed": True}).json()["draft_id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, f"/api/drafts/{draft_id}/send", json={"confirmed": True})
        assert entered.wait(timeout=5)
        second = executor.submit(client.post, f"/api/drafts/{draft_id}/send", json={"confirmed": True})
        second_response = second.result(timeout=5)
        release.set()
        first_response = first.result(timeout=5)

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert "正在发送" in second_response.json()["detail"]
    assert fake_client.send_calls == 1
    assert len(fake_client.sent) == 1
    assert store.get_draft(draft_id).send_status == "sent"


def test_web_smtp_exception_is_locked_unknown_to_prevent_duplicate_delivery(tmp_path):
    class FlakyMailClient(FakeMailClient):
        def __init__(self):
            super().__init__()
            self.send_calls = 0

        def send_draft(self, draft: Draft, *, dry_run: bool = True):
            self.send_calls += 1
            if self.send_calls == 1:
                raise RuntimeError("temporary SMTP failure")
            return super().send_draft(draft, dry_run=dry_run)

    fake_client = FlakyMailClient()
    client, _, store = _client(tmp_path, mail_client=fake_client)
    draft_id = client.post("/api/messages/101/draft", json={"confirmed": True}).json()["draft_id"]

    failed = client.post(f"/api/drafts/{draft_id}/send", json={"confirmed": True})

    assert failed.status_code == 409
    assert "无法确认邮件是否已投递" in failed.json()["detail"]
    assert store.get_draft(draft_id).send_status == "unknown"
    assert "temporary SMTP failure" in store.get_draft(draft_id).send_error

    retried = client.post(f"/api/drafts/{draft_id}/send", json={"confirmed": True})

    assert retried.status_code == 409
    assert "发送结果不确定" in retried.json()["detail"]
    assert fake_client.send_calls == 1
    assert len(fake_client.sent) == 0
    assert store.get_draft(draft_id).send_status == "unknown"


def test_web_smtp_success_with_state_write_failure_is_locked_unknown(tmp_path, monkeypatch):
    client, fake_client, store = _client(tmp_path)
    draft_id = client.post("/api/messages/101/draft", json={"confirmed": True}).json()["draft_id"]

    monkeypatch.setattr(
        store,
        "complete_draft_send",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sqlite write failed")),
    )

    response = client.post(f"/api/drafts/{draft_id}/send", json={"confirmed": True})

    assert response.status_code == 409
    assert "可能已经发出" in response.json()["detail"]
    assert len(fake_client.sent) == 1
    assert store.get_draft(draft_id).send_status == "unknown"

    duplicate = client.post(f"/api/drafts/{draft_id}/send", json={"confirmed": True})

    assert duplicate.status_code == 409
    assert "发送结果不确定" in duplicate.json()["detail"]
    assert len(fake_client.sent) == 1


def test_web_regenerated_draft_returns_unique_version_and_keeps_sent_history(tmp_path):
    client, _, store = _client(tmp_path)
    first_id = client.post("/api/messages/101/draft", json={"confirmed": True}).json()["draft_id"]
    assert client.post(f"/api/drafts/{first_id}/send", json={"confirmed": True}).status_code == 200

    regenerated = client.post("/api/messages/101/draft", json={"confirmed": True})

    assert regenerated.status_code == 200
    second = regenerated.json()
    assert second["draft_id"] != first_id
    assert second["supersedes_id"] == first_id
    assert second["draft_version"] == 2
    assert second["send_status"] == "pending"
    assert store.get_draft(first_id).send_status == "sent"
    assert {draft.draft_id for draft in store.list_drafts(status="all")} == {first_id, second["draft_id"]}

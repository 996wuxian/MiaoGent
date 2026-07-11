from __future__ import annotations

from collections.abc import Callable
import hmac
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from qq_mail_agent_cli.agent import MailAgent
from qq_mail_agent_cli.config import (
    DeepSeekConfig,
    MailConfig,
    load_app_config,
    load_deepseek_config,
    load_mail_config,
)
from qq_mail_agent_cli.health import (
    HealthCheckItem,
    check_deepseek_connectivity,
    check_imap_login,
    check_smtp_login,
    run_local_health_checks,
)
from qq_mail_agent_cli.llm_client import DeepSeekClient
from qq_mail_agent_cli.mail_client import MailClient
from qq_mail_agent_cli.services import (
    DraftConflictError,
    DraftNotFoundError,
    DraftSendFailedError,
    DraftSendUncertainError,
    DraftService,
    MailSyncService,
    SecretaryInspectionService,
    SyncAlreadyRunningError,
)
from qq_mail_agent_cli.storage import StateStore
from qq_mail_agent_cli.web_schemas import (
    ActionLogResponse,
    ConfirmRequest,
    DraftResponse,
    DraftUpdateRequest,
    DesktopNotificationStatusRequest,
    FetchFailureResponse,
    HealthItemResponse,
    InsightFeedbackRequest,
    InsightFeedbackResponse,
    InsightLabelsRequest,
    MessageResponse,
    MailInsightResponse,
    NotificationStatusRequest,
    QueueStatusRequest,
    SearchMailResponse,
    SecretaryInspectionRequest,
    SecretaryInspectionResponse,
    SendDraftResponse,
    StatusResponse,
    StartupSummaryResponse,
    SyncStateResponse,
    TranslationResponse,
    TriageRecentRequest,
    TriageRecentResponse,
    TriageResponse,
    action_to_response,
    draft_to_response,
    fetch_failure_to_response,
    insight_feedback_to_response,
    message_to_response,
    mail_insight_to_response,
    search_result_to_response,
    secretary_inspection_to_response,
    send_result_to_response,
    translation_to_response,
    triage_to_response,
    startup_summary_to_response,
    sync_state_to_response,
)


def create_app(
    *,
    mail_client_factory: Callable[[], MailClient] | None = None,
    agent_factory: Callable[[], MailAgent] | None = None,
    state_store_factory: Callable[[], StateStore] | None = None,
    sync_service_factory: Callable[[], MailSyncService] | None = None,
    session_token: str | None = None,
    mail_config_factory: Callable[[], MailConfig] | None = None,
    deepseek_config_factory: Callable[[], DeepSeekConfig] | None = None,
    local_health_factory: Callable[[], list[HealthCheckItem]] | None = None,
    shutdown_callback: Callable[[], None] | None = None,
) -> FastAPI:
    if session_token is not None and len(session_token) < 32:
        raise ValueError("desktop session token must contain at least 32 characters")
    app = FastAPI(title="QQ Mail Agent Web API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.mail_client_factory = mail_client_factory or (lambda: MailClient(load_mail_config()))
    app.state.agent_factory = agent_factory or _build_deepseek_agent
    app.state.state_store_factory = state_store_factory or (lambda: StateStore(load_app_config().db_path))
    app.state.sync_service_factory = sync_service_factory
    app.state.mail_config_factory = mail_config_factory or load_mail_config
    app.state.deepseek_config_factory = deepseek_config_factory or load_deepseek_config
    app.state.local_health_factory = local_health_factory or run_local_health_checks
    app.state.shutdown_callback = shutdown_callback
    app.state.secretary_inspection_lock = Lock()

    @app.middleware("http")
    async def desktop_session_auth(request: Request, call_next):
        if (
            session_token is not None
            and request.method != "OPTIONS"
            and request.url.path.startswith("/api/")
        ):
            authorization = request.headers.get("authorization", "")
            scheme, separator, provided = authorization.partition(" ")
            authorized = (
                separator == " "
                and scheme.lower() == "bearer"
                and bool(provided)
                and hmac.compare_digest(provided, session_token)
            )
            if not authorized:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)

    dist_dir = Path(__file__).resolve().parents[2] / "web" / "dist"
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def index():
        index_file = dist_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"ok": True, "detail": "Web API is running. Start Vite dev server for the UI."}

    @app.get("/api/health/local", response_model=list[HealthItemResponse])
    def local_health():
        return [
            HealthItemResponse(name=item.name, ok=item.ok, detail=item.detail)
            for item in app.state.local_health_factory()
        ]

    @app.post("/api/health/imap", response_model=HealthItemResponse)
    def imap_health(request: ConfirmRequest):
        _require_confirmation(request)
        item = check_imap_login(app.state.mail_config_factory())
        return HealthItemResponse(name=item.name, ok=item.ok, detail=item.detail)

    @app.post("/api/health/smtp", response_model=HealthItemResponse)
    def smtp_health(request: ConfirmRequest):
        _require_confirmation(request)
        item = check_smtp_login(app.state.mail_config_factory())
        return HealthItemResponse(name=item.name, ok=item.ok, detail=item.detail)

    @app.post("/api/health/deepseek", response_model=HealthItemResponse)
    def deepseek_health(request: ConfirmRequest):
        _require_confirmation(request)
        item = check_deepseek_connectivity(app.state.deepseek_config_factory())
        return HealthItemResponse(name=item.name, ok=item.ok, detail=item.detail)

    @app.get("/api/messages/recent", response_model=list[MessageResponse])
    def recent_messages(
        client: Annotated[MailClient, Depends(_get_mail_client)],
        store: Annotated[StateStore, Depends(_get_state_store)],
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        try:
            messages = client.list_real_recent(limit, offset=offset)
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        for message in messages:
            store.upsert_mail(message)
        return [message_to_response(message, include_body=False) for message in messages]

    @app.get("/api/messages/{uid}", response_model=MessageResponse)
    def message_detail(
        uid: str,
        client: Annotated[MailClient, Depends(_get_mail_client)],
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        message = _get_message_or_404(client, uid)
        store.upsert_mail(message)
        return message_to_response(message, include_body=True)

    @app.post("/api/messages/{uid}/mark-seen", response_model=StatusResponse)
    def mark_seen(
        uid: str,
        request: ConfirmRequest,
        client: Annotated[MailClient, Depends(_get_mail_client)],
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        _require_confirmation(request)
        try:
            marked = client.mark_real_seen(uid)
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        if not marked:
            raise HTTPException(status_code=404, detail="邮件不存在或 UID 无效")
        # Preserve the legacy PC queue workflow. Desktop automation uses the
        # independent insight/reply/notification states instead.
        store.set_triage_queue_status(_normalize_uid_for_store(uid), "done")
        store.log_action("mark_seen", uid=_normalize_uid_for_store(uid), detail="Marked as seen from web UI")
        return StatusResponse(ok=True, detail="已同步标记为已读")

    @app.post("/api/messages/{uid}/move-to-trash", response_model=StatusResponse)
    def move_to_trash(
        uid: str,
        request: ConfirmRequest,
        client: Annotated[MailClient, Depends(_get_mail_client)],
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        _require_confirmation(request)
        try:
            mailbox = client.move_real_to_trash([uid])
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        normalized_uid = _normalize_uid_for_store(uid)
        store.set_triage_queue_status(normalized_uid, "done")
        store.log_action("move_to_trash", uid=normalized_uid, detail=f"Moved to {mailbox} from web UI")
        return StatusResponse(ok=True, detail=f"已移动到 {mailbox}")

    @app.post("/api/triage/recent", response_model=TriageRecentResponse)
    def triage_recent(
        request: TriageRecentRequest,
        client: Annotated[MailClient, Depends(_get_mail_client)],
        agent: Annotated[MailAgent, Depends(_get_agent)],
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        _require_confirmation(request)
        try:
            messages = client.list_real_recent(request.limit, offset=request.offset)
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        skipped_seen = 0
        if request.unread_only:
            kept = []
            for message in messages:
                if message.is_seen is True:
                    skipped_seen += 1
                    store.upsert_mail(message)
                    continue
                kept.append(message)
            messages = kept

        skipped_triaged = 0
        if request.skip_triaged:
            triaged = store.get_triaged_uids([message.id for message in messages])
            filtered = []
            for message in messages:
                if message.id in triaged:
                    skipped_triaged += 1
                    store.upsert_mail(message)
                    continue
                filtered.append(message)
            messages = filtered

        processed = []
        model_name = app.state.deepseek_config_factory().model
        for message in messages:
            result = agent.triage(message)
            store.save_triage(message, result, model=model_name)
            processed.append(triage_to_response(result, message=message))
        return TriageRecentResponse(processed=processed, skipped_seen=skipped_seen, skipped_triaged=skipped_triaged)

    @app.post("/api/secretary/inspection", response_model=SecretaryInspectionResponse)
    def secretary_inspection(
        request: SecretaryInspectionRequest,
        client: Annotated[MailClient, Depends(_get_mail_client)],
        agent: Annotated[MailAgent, Depends(_get_agent)],
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        _require_confirmation(request)
        inspection_lock = app.state.secretary_inspection_lock
        if not inspection_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="巡检正在进行，请稍后再试")
        try:
            try:
                report = SecretaryInspectionService(
                    client,
                    agent,
                    store,
                    model=app.state.deepseek_config_factory().model,
                ).inspect(limit=request.limit)
            except RuntimeError as error:
                raise HTTPException(
                    status_code=502,
                    detail="巡检暂时无法完成，请稍后重试",
                ) from error
        finally:
            inspection_lock.release()
        return secretary_inspection_to_response(report)

    @app.get("/api/triage/queue", response_model=list[TriageResponse])
    def triage_queue(
        store: Annotated[StateStore, Depends(_get_state_store)],
        limit: int = Query(default=20, ge=1, le=100),
        statuses: list[str] | None = Query(default=None),
    ):
        requested_statuses = tuple(statuses or ("pending", "later"))
        if "all" in requested_statuses:
            requested_statuses = ("pending", "later", "done", "skipped")
        try:
            rows = store.list_suggested_triage_queue(limit, statuses=requested_statuses)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return [triage_to_response(item) for item in rows]

    @app.get("/api/insights", response_model=list[MailInsightResponse])
    def mail_insights(
        store: Annotated[StateStore, Depends(_get_state_store)],
        limit: int = Query(default=100, ge=1, le=500),
        importance: str | None = None,
        needs_reply: bool | None = None,
        reply_pending: bool | None = None,
        analysis_status: str | None = None,
        min_confidence: float | None = Query(default=None, ge=0, le=1),
        reply_status: str | None = None,
        notification_status: str | None = None,
        include_stale: bool = False,
    ):
        try:
            rows = store.list_mail_insights(
                limit,
                importance=importance,
                needs_reply=needs_reply,
                reply_pending=reply_pending,
                analysis_status=analysis_status,
                min_confidence=min_confidence,
                reply_status=reply_status,
                notification_status=notification_status,
                include_stale=include_stale,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return [
            mail_insight_to_response(
                item,
                store.get_latest_mail_insight_feedback_by_mail_key(item.mail_key),
            )
            for item in rows
        ]

    @app.get("/api/insights/{uid}", response_model=MailInsightResponse)
    def mail_insight(
        uid: str,
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        insight = store.get_mail_insight(_normalize_uid_for_store(uid))
        if insight is None:
            raise HTTPException(status_code=404, detail="本地邮件洞察不存在")
        feedback = store.get_latest_mail_insight_feedback_by_mail_key(insight.mail_key)
        return mail_insight_to_response(insight, feedback)

    @app.patch("/api/insights/{uid}/labels", response_model=MailInsightResponse)
    def update_mail_insight_labels(
        uid: str,
        request: InsightLabelsRequest,
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        try:
            insight = store.update_mail_insight_labels(
                _normalize_uid_for_store(uid),
                importance=request.importance,
                needs_reply=request.needs_reply,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if insight is None:
            raise HTTPException(status_code=404, detail="本地邮件洞察不存在")
        feedback = store.get_latest_mail_insight_feedback_by_mail_key(insight.mail_key)
        return mail_insight_to_response(insight, feedback)

    @app.post("/api/insights/{uid}/feedback", response_model=InsightFeedbackResponse)
    def save_mail_insight_feedback(
        uid: str,
        request: InsightFeedbackRequest,
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        try:
            feedback = store.save_mail_insight_feedback(
                _normalize_uid_for_store(uid),
                feedback=request.feedback,
                comment=request.comment,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if feedback is None:
            raise HTTPException(status_code=404, detail="本地邮件洞察不存在")
        return insight_feedback_to_response(feedback)

    @app.post("/api/insights/{uid}/notification-status", response_model=StatusResponse)
    def set_notification_status(
        uid: str,
        request: NotificationStatusRequest,
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        try:
            updated = store.set_notification_status(
                _normalize_uid_for_store(uid),
                request.status,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not updated:
            raise HTTPException(status_code=404, detail="本地邮件洞察不存在")
        return StatusResponse(ok=True, detail="通知状态已更新")

    @app.post("/api/desktop/notification-status", response_model=StatusResponse)
    def set_desktop_notification_status(
        request: DesktopNotificationStatusRequest,
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        try:
            updated = store.set_notification_status_by_mail_key(
                request.mail_key,
                request.status,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not updated:
            raise HTTPException(status_code=404, detail="本地邮件洞察不存在")
        return StatusResponse(ok=True, detail="桌面通知状态已更新")

    @app.get("/api/desktop/sync-state", response_model=SyncStateResponse | None)
    def desktop_sync_state(store: Annotated[StateStore, Depends(_get_state_store)]):
        state = store.get_sync_state()
        return sync_state_to_response(state) if state is not None else None

    @app.get("/api/desktop/fetch-failures", response_model=list[FetchFailureResponse])
    def desktop_fetch_failures(
        store: Annotated[StateStore, Depends(_get_state_store)],
        limit: int = Query(default=100, ge=1, le=500),
    ):
        state = store.get_sync_state()
        if state is None:
            return []
        failures = store.list_quarantined_fetch_failures(
            uid_validity=state.uid_validity,
            mailbox=state.mailbox,
            limit=limit,
        )
        return [fetch_failure_to_response(failure) for failure in failures]

    @app.get(
        "/api/desktop/startup-summary/latest",
        response_model=StartupSummaryResponse,
    )
    def latest_startup_summary(store: Annotated[StateStore, Depends(_get_state_store)]):
        summary = store.get_latest_startup_summary()
        if summary is None:
            raise HTTPException(status_code=404, detail="尚无启动汇总")
        return startup_summary_to_response(summary)

    @app.post("/api/desktop/startup-summary/{summary_id}/ack", response_model=StatusResponse)
    def acknowledge_startup_summary(
        summary_id: int,
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        if not store.mark_startup_summary_delivery(summary_id, "acknowledged"):
            raise HTTPException(status_code=404, detail="启动汇总不存在")
        return StatusResponse(ok=True, detail="启动汇总已确认展示")

    @app.post("/api/desktop/sync", response_model=StartupSummaryResponse)
    def desktop_sync(service: Annotated[MailSyncService, Depends(_get_sync_service)]):
        try:
            report = service.sync(trigger="manual")
        except SyncAlreadyRunningError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail="邮件同步暂时不可用") from error
        return StartupSummaryResponse(**report.to_payload())

    @app.post("/api/desktop/shutdown", response_model=StatusResponse)
    def desktop_shutdown():
        callback = app.state.shutdown_callback
        if callback is None:
            raise HTTPException(status_code=503, detail="桌面关闭服务未启用")
        callback()
        return StatusResponse(ok=True, detail="桌面 sidecar 正在退出")

    @app.post("/api/triage/{uid}/status", response_model=StatusResponse)
    def set_queue_status(
        uid: str,
        request: QueueStatusRequest,
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        try:
            updated = store.set_triage_queue_status(_normalize_uid_for_store(uid), request.status)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not updated:
            raise HTTPException(status_code=404, detail="本地分类记录不存在")
        store.log_action("queue_status", uid=_normalize_uid_for_store(uid), detail=f"Set queue status to {request.status}")
        return StatusResponse(ok=True, detail="队列状态已更新")

    @get_search_route(app)
    def search_messages(
        store: Annotated[StateStore, Depends(_get_state_store)],
        limit: int = Query(default=20, ge=1, le=100),
        keyword: str | None = None,
        is_seen: bool | None = None,
        classification: str | None = None,
        queue_status: str | None = None,
    ):
        try:
            results = store.search_mail_items(
                limit,
                keyword=keyword,
                is_seen=is_seen,
                classification=classification,
                queue_status=queue_status,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return [search_result_to_response(item) for item in results]

    @app.post("/api/messages/{uid}/translate", response_model=TranslationResponse)
    def translate_message(
        uid: str,
        request: ConfirmRequest,
        client: Annotated[MailClient, Depends(_get_mail_client)],
        agent: Annotated[MailAgent, Depends(_get_agent)],
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        _require_confirmation(request)
        message = _get_message_or_404(client, uid)
        translation = agent.translate_message(message)
        store.upsert_mail(message)
        store.log_action("translate", uid=message.id, detail="Translated from web UI; translation body not persisted")
        return translation_to_response(translation)

    @app.post("/api/messages/{uid}/draft", response_model=DraftResponse)
    def draft_message(
        uid: str,
        request: ConfirmRequest,
        client: Annotated[MailClient, Depends(_get_mail_client)],
        agent: Annotated[MailAgent, Depends(_get_agent)],
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        _require_confirmation(request)
        message = _get_message_or_404(client, uid)
        draft = agent.draft_reply(message)
        store.upsert_mail(message)
        stored = DraftService(client, store).save_generated_draft(draft)
        store.set_triage_queue_status(message.id, "done")
        store.log_action("draft_reply", uid=message.id, detail=f"Saved draft {stored.draft_id} from web UI")
        return draft_to_response(stored)

    @app.get("/api/drafts", response_model=list[DraftResponse])
    def list_drafts(
        store: Annotated[StateStore, Depends(_get_state_store)],
        status: str = Query(default="pending"),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        try:
            drafts = store.list_drafts(limit=limit, status=status)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return [draft_to_response(draft) for draft in drafts]

    @app.get("/api/drafts/{draft_id}", response_model=DraftResponse)
    def get_draft(draft_id: str, store: Annotated[StateStore, Depends(_get_state_store)]):
        draft = store.get_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="草稿不存在")
        return draft_to_response(draft)

    @app.patch("/api/drafts/{draft_id}", response_model=DraftResponse)
    def update_draft(draft_id: str, request: DraftUpdateRequest, store: Annotated[StateStore, Depends(_get_state_store)]):
        if not store.update_draft(draft_id, subject=request.subject, body=request.body):
            raise HTTPException(status_code=404, detail="草稿不存在或已发送")
        store.log_action("edit_draft", detail=f"Edited draft {draft_id} from web UI")
        draft = store.get_draft(draft_id)
        assert draft is not None
        return draft_to_response(draft)

    @app.post("/api/drafts/{draft_id}/send", response_model=SendDraftResponse)
    def send_draft(
        draft_id: str,
        request: ConfirmRequest,
        client: Annotated[MailClient, Depends(_get_mail_client)],
        store: Annotated[StateStore, Depends(_get_state_store)],
    ):
        _require_confirmation(request)
        try:
            result = DraftService(client, store).send_stored_draft(
                draft_id,
                dry_run=False,
                source="web UI",
            )
        except DraftNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except DraftConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DraftSendFailedError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except DraftSendUncertainError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if isinstance(result, str):  # pragma: no cover - real sends are typed results
            raise HTTPException(status_code=500, detail=result)
        return send_result_to_response(result)

    @app.get("/api/actions", response_model=list[ActionLogResponse])
    def actions(store: Annotated[StateStore, Depends(_get_state_store)], limit: int = Query(default=30, ge=1, le=100)):
        return [action_to_response(item) for item in store.list_actions(limit)]

    return app


def get_search_route(app: FastAPI):
    return app.get("/api/search/messages", response_model=list[SearchMailResponse])


def _get_mail_client(request: Request) -> MailClient:
    return request.app.state.mail_client_factory()


def _get_agent(request: Request) -> MailAgent:
    return request.app.state.agent_factory()


def _get_state_store(request: Request) -> StateStore:
    return request.app.state.state_store_factory()


def _get_sync_service(request: Request) -> MailSyncService:
    factory = request.app.state.sync_service_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="桌面同步服务未启用")
    return factory()


def _build_deepseek_agent() -> MailAgent:
    return MailAgent(llm_client=DeepSeekClient(load_deepseek_config()))


def _require_confirmation(request: ConfirmRequest) -> None:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="此操作需要 confirmed=true")


def _get_message_or_404(client: MailClient, uid: str):
    try:
        message = client.get_real_message(uid)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if message is None:
        raise HTTPException(status_code=404, detail="邮件不存在或 UID 无效")
    return message


def _normalize_uid_for_store(uid: str) -> str:
    value = uid.strip()
    if value.startswith("uid:"):
        return value
    return f"uid:{value}"


def main() -> None:
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)


app = create_app()


if __name__ == "__main__":
    main()

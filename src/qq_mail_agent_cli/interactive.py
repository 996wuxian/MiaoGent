from qq_mail_agent_cli.agent import MailAgent
from qq_mail_agent_cli.config import load_app_config, load_deepseek_config, load_mail_config
from qq_mail_agent_cli.health import HealthCheckItem, check_deepseek_connectivity, check_imap_login, check_smtp_login, run_local_health_checks
from qq_mail_agent_cli.llm_client import DeepSeekClient
from qq_mail_agent_cli.mail_client import MailClient
from qq_mail_agent_cli.models import MailMessage, MailTranslation, SuggestedAction, TriageResult
from qq_mail_agent_cli.services import DraftService, DraftServiceError
from qq_mail_agent_cli.storage import StateStore, StoredDraft, StoredMailSearchResult, StoredTriage
from pathlib import Path
from textwrap import fill
from dataclasses import replace
import webbrowser


MENU = """
QQ Mail Agent

1. 邮件处理面板
2. DeepSeek 分类最近邮件
3. 草稿箱 / 编辑 / 发送
4. 操作记录
5. 配置体检
0. 退出
"""


def main() -> int:
    config = load_mail_config()
    client = MailClient(config)
    store = StateStore(load_app_config().db_path)

    while True:
        print(MENU)
        choice = input("请选择: ").strip()
        try:
            if choice == "1":
                _message_workbench_flow(client, store)
            elif choice == "2":
                _triage_real_messages_flow(client, store)
            elif choice == "3":
                _draft_send_flow(client, store)
            elif choice == "4":
                _show_action_log(store)
            elif choice == "5":
                _config_health_flow()
            elif choice == "0":
                print("已退出。")
                return 0
            else:
                print("无效选项。")
        except Exception as error:
            print(f"执行失败: {error}")


def _ask_limit(default: int = 5) -> int:
    value = input(f"读取数量，默认 {default}: ").strip()
    if not value:
        return default
    try:
        limit = int(value)
    except ValueError:
        print(f"不是有效数字，使用默认 {default}。")
        return default
    return max(1, min(limit, 50))


def _browse_real_messages(client: MailClient, store: StateStore) -> None:
    limit = _ask_limit()
    offset = 0
    while True:
        messages = client.list_real_recent(limit, offset=offset)
        if not messages:
            print("没有更多邮件。")
            return
        page = offset // limit + 1
        print(f"\n第 {page} 页，每页 {limit} 封")
        print("-" * 40)
        for message in messages:
            store.upsert_mail(message)
        _show_messages(messages, allow_snippet=True)
        if len(messages) < limit:
            print("已到最后一页。")
            return
        if not _ask_yes_no("继续下一页?", default=False):
            return
        offset += limit


def _ask_yes_no(prompt: str, *, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "是", "1"}


def _confirm_send_to_ai() -> bool:
    return _ask_yes_no("确认将邮件内容发送给 DeepSeek 处理?", default=False)


def _confirm_translate_with_ai() -> bool:
    return _ask_yes_no("确认将邮件内容发送给 DeepSeek 翻译?", default=False)


def _ai_agent() -> MailAgent:
    return MailAgent(llm_client=DeepSeekClient(load_deepseek_config()))


def _show_messages(messages: list[MailMessage], *, allow_snippet: bool = False) -> None:
    if not messages:
        print("没有邮件。")
        return
    for index, message in enumerate(messages, start=1):
        print(f"[{index}] {message.id} {_seen_label(message)}")
        print(f"    发件人: {_clip(message.sender, 88)}")
        print(f"    主题:   {_clip(message.subject, 88)}")
        if message.date:
            print(f"    时间:   {message.date}")
        if allow_snippet and message.snippet:
            print("    摘要:")
            print(_indent_wrapped(message.snippet, indent="      ", width=82))
        print()


def _triage_messages(messages: list[MailMessage], agent: MailAgent, store: StateStore | None = None, model: str = "rules") -> None:
    if not messages:
        print("没有邮件。")
        return
    results = [(message, agent.triage(message)) for message in messages]
    if store is not None:
        for message, result in results:
            store.save_triage(message, result, model=model)
            store.log_action("triage", uid=message.id, detail=f"{result.classification.value}: {result.reason}")
    _show_triage_summary(results)


def _triage_real_messages_flow(client: MailClient, store: StateStore) -> None:
    if not _confirm_send_to_ai():
        return
    messages = client.list_real_recent(_ask_limit(default=20))
    if _ask_yes_no("只分类未读邮件?", default=True):
        messages = _filter_unread_messages(messages)
        if not messages:
            print("没有未读邮件需要分类。")
            return
    if _ask_yes_no("跳过已分类邮件?", default=True):
        messages = _filter_untriaged_messages(messages, store)
        if not messages:
            print("没有新的未分类邮件需要分类。")
            return
    _triage_messages(messages, _ai_agent(), store=store, model="deepseek")
    print("分类完成。可进入菜单 1 邮件处理面板，按 AI 建议继续处理。")


def _filter_unread_messages(messages: list[MailMessage]) -> list[MailMessage]:
    return [message for message in messages if message.is_seen is False]


def _filter_untriaged_messages(messages: list[MailMessage], store: StateStore) -> list[MailMessage]:
    triaged_uids = store.get_triaged_uids([message.id for message in messages])
    return [message for message in messages if message.id not in triaged_uids]


def _show_triage_summary(results: list[tuple[MailMessage, TriageResult]]) -> None:
    groups = _group_triage_results(results)
    print()
    print("分类汇总")
    print("-" * 40)
    for group in groups:
        messages = group["messages"]
        first_message = messages[0]
        first_result = group["results"][0]
        ids = ", ".join(message.id for message in messages[:8])
        if len(messages) > 8:
            ids += f", ... +{len(messages) - 8}"
        print(f"[{first_result.classification.value}] {len(messages)} 封 - {first_message.subject}")
        print(f"    分类原因: {_clip(first_result.reason, 110)}")
        print(f"    建议动作: {_suggested_action_label(first_result.suggested_action.value)}")
        if first_result.action_reason:
            print(f"    动作原因: {_clip(first_result.action_reason, 110)}")
        print(f"    邮件: {ids}")
    print()
    print("分类明细")
    print("-" * 40)
    for group in groups:
        first_result = group["results"][0]
        print(f"{first_result.classification.value.upper()} / {len(group['messages'])} 封 / {group['messages'][0].subject}")
        for message, result in zip(group["messages"], group["results"], strict=True):
            print(
                f"    {message.id} {_seen_label(message)}  {message.sender}  "
                f"{_suggested_action_label(result.suggested_action.value)}  {_clip(result.reason, 80)}"
            )
        print()


def _group_triage_results(results: list[tuple[MailMessage, TriageResult]]):
    grouped = {}
    order = []
    for message, result in results:
        key = (result.classification.value, _normalize_subject(message.subject))
        if key not in grouped:
            grouped[key] = {"messages": [], "results": []}
            order.append(key)
        grouped[key]["messages"].append(message)
        grouped[key]["results"].append(result)
    return [grouped[key] for key in order]


def _show_draft(draft) -> None:
    print(f"Draft: {draft.id}")
    print(f"To: {draft.to}")
    print(f"Subject: {draft.subject}")
    print()
    print(draft.body)


def _move_to_trash_flow(client: MailClient, store: StateStore) -> None:
    print()
    print("移动邮件到垃圾箱")
    print("1. 单封移动")
    print("2. 批量选择移动")
    print("0. 返回")
    choice = input("请选择: ").strip()
    if choice == "0":
        return
    if choice == "1":
        raw_ids = input("请输入邮件 id，例如 uid:2670: ").strip()
        mail_ids = _parse_mail_id_list(raw_ids)
    elif choice == "2":
        mail_ids = _select_messages_for_trash(client)
    else:
        print("无效选项。")
        return

    if not mail_ids:
        if choice == "2":
            print("已取消或未选择邮件。")
        else:
            print("没有有效邮件 id。")
        return

    messages = []
    missing = []
    for mail_id in mail_ids:
        message = client.get_real_message(mail_id)
        if message is None:
            missing.append(mail_id)
        else:
            messages.append(message)

    if missing:
        print(f"以下邮件未找到，将跳过: {', '.join(missing)}")
    if not messages:
        print("没有可移动的邮件。")
        return

    print()
    print("将移动以下邮件到垃圾箱:")
    _show_messages(messages, allow_snippet=True)
    if not _ask_yes_no(f"确认移动 {len(messages)} 封邮件到垃圾箱?", default=False):
        print("已取消。")
        return
    trash = client.move_real_to_trash([message.id for message in messages])
    for message in messages:
        store.upsert_mail(message)
        store.log_action("move_to_trash", uid=message.id, detail=f"{message.subject} -> {trash}")
    print(f"已移动到垃圾箱: {trash}")


def _triage_results_flow(client: MailClient, store: StateStore) -> None:
    print()
    print("分类结果")
    print("1. 全部分类结果")
    print("2. 只看需要处理")
    print("3. 为需要处理邮件生成草稿")
    print("0. 返回")
    choice = input("请选择: ").strip()
    if choice == "1":
        _show_stored_triage(store)
    elif choice == "2":
        _show_stored_triage(store, classification="respond")
    elif choice == "3":
        _draft_for_respond_message(client, store)
    elif choice == "0":
        return
    else:
        print("无效选项。")


def _show_stored_triage(store: StateStore, *, classification: str | None = None) -> None:
    rows = store.list_triage_results(limit=_ask_limit(default=20), classification=classification)
    if not rows:
        print("暂无分类结果。")
        return
    for index, row in enumerate(rows, start=1):
        print(f"[{index}] {row.uid}")
        print(f"    分类: {_classification_label(row.classification)}")
        print(f"    建议: {_suggested_action_label(row.suggested_action)}")
        print(f"    主题: {row.subject or '(无主题)'}")
        print(f"    原因: {_clip(row.reason, 120)}")
        if row.action_reason:
            print(f"    建议原因: {_clip(row.action_reason, 120)}")
        print(f"    时间: {row.updated_at}")
        print()


def _draft_for_respond_message(client: MailClient, store: StateStore) -> None:
    rows = store.list_triage_results(limit=_ask_limit(default=20), classification="respond")
    if not rows:
        print("暂无需要处理的邮件。")
        return
    for index, row in enumerate(rows, start=1):
        print(f"[{index}] {row.uid}")
        print(f"    主题: {row.subject or '(无主题)'}")
        print(f"    原因: {_clip(row.reason, 100)}")
        print(f"    建议: {_suggested_action_label(row.suggested_action)}")
    raw = input("请选择要生成草稿的序号，支持 1,3-5,all；或 q 取消: ").strip().lower()
    if raw == "q":
        return
    try:
        indexes = _parse_selection(raw, max_index=len(rows))
    except ValueError as error:
        print(f"选择无效: {error}")
        return
    _draft_for_selected_respond_messages(client, store, rows, indexes)


def _draft_for_selected_respond_messages(
    client: MailClient,
    store: StateStore,
    rows: list[StoredTriage],
    indexes: list[int],
) -> None:
    selected_rows = [rows[index - 1] for index in indexes]
    if not selected_rows:
        print("没有选择任何邮件。")
        return
    if not _ask_yes_no(f"确认将 {len(selected_rows)} 封邮件内容发送给 DeepSeek 处理?", default=False):
        return

    agent = _ai_agent()
    successes = []
    failures = []
    total = len(selected_rows)
    for position, row in enumerate(selected_rows, start=1):
        print(f"[{position}/{total}] 正在生成 {row.uid} ...")
        try:
            message = client.get_real_message(row.uid)
            if message is None:
                raise RuntimeError("未找到该邮件")
            draft = agent.draft_reply(message)
            store.upsert_mail(message)
            stored = DraftService(client, store).save_generated_draft(draft)
            store.log_action("draft_generated", uid=message.id, detail=stored.subject)
            _set_queue_status(store, message.id, "done", announce=False)
            successes.append((message.id, stored.draft_id))
            print(f"    已保存草稿: {stored.draft_id}")
        except Exception as error:
            detail = str(error)
            failures.append((row.uid, detail))
            store.log_action("draft_failed", uid=row.uid, detail=detail)
            print(f"    失败: {detail}")

    print()
    print(f"批量生成完成：成功 {len(successes)} 封，失败 {len(failures)} 封。")
    if failures:
        print("失败明细:")
        for uid, detail in failures:
            print(f"    {uid}: {_clip(detail, 120)}")
    if successes:
        print("请到菜单 3 草稿箱查看待发送草稿。")


def _show_action_log(store: StateStore) -> None:
    rows = store.list_actions(limit=_ask_limit(default=30))
    if not rows:
        print("暂无操作记录。")
        return
    for row in rows:
        print(f"{row.id}\t{row.created_at}\t{row.action}\t{row.uid or ''}\t{_clip(row.detail, 100)}")


def _config_health_flow() -> None:
    print()
    print("配置体检")
    print("1. 本地配置检查")
    print("2. QQ IMAP 登录检查")
    print("3. QQ SMTP 登录检查")
    print("4. DeepSeek 连通检查")
    print("0. 返回")
    choice = input("请选择: ").strip()
    if choice == "1":
        _show_health_check_items(run_local_health_checks(), note="本地配置和 SQLite 可写检查，不登录 QQ 邮箱，不调用 DeepSeek。")
        return
    if choice == "2":
        if not _ask_yes_no("确认连接 QQ IMAP 并尝试登录? 不会读取邮件", default=False):
            print("已取消。")
            return
        _show_health_check_items([check_imap_login(load_mail_config())])
        return
    if choice == "3":
        if not _ask_yes_no("确认连接 QQ SMTP 并尝试登录? 不会发送邮件", default=False):
            print("已取消。")
            return
        _show_health_check_items([check_smtp_login(load_mail_config())])
        return
    if choice == "4":
        if not _ask_yes_no("确认向 DeepSeek 发送 ping 测试? 不包含邮件内容", default=False):
            print("已取消。")
            return
        _show_health_check_items([check_deepseek_connectivity(load_deepseek_config())])
        return
    if choice == "0":
        return
    print("无效选项。")


def _show_health_check_items(items: list[HealthCheckItem], *, note: str | None = None) -> None:
    print()
    print("体检结果")
    print("-" * 60)
    for item in items:
        status = "OK" if item.ok else "FAIL"
        print(f"[{status}] {item.name} {item.detail}")
    print()
    print("结果: 通过" if all(item.ok for item in items) else "结果: 需要补全配置")
    if note:
        print(f"说明: {note}")


def _translate_message_flow(client: MailClient, store: StateStore) -> None:
    mail_id = input("请输入邮件 id，例如 uid:2670: ").strip()
    message = client.get_real_message(mail_id)
    if message is None:
        print("未找到该邮件。")
        return
    if not _confirm_translate_with_ai():
        return
    translation = _ai_agent().translate_message(message)
    store.upsert_mail(message)
    store.log_action("translate", uid=message.id, detail=message.subject)
    _show_translation(message, translation)


def _message_workbench_flow(client: MailClient, store: StateStore) -> None:
    while True:
        print()
        print("邮件处理面板")
        print("1. 按 AI 建议处理")
        print("2. 查看最近邮件")
        print("3. 查看已处理 / 已跳过记录")
        print("4. 搜索 / 筛选邮件")
        print("0. 返回")
        choice = input("请选择: ").strip()
        if choice == "1":
            _suggestion_queue_flow(client, store)
            continue
        if choice == "2":
            _browse_recent_messages_for_workbench(client, store)
            continue
        if choice == "3":
            _queue_history_flow(store)
            continue
        if choice == "4":
            _mail_search_flow(client, store)
            continue
        if choice == "0":
            return
        print("无效选项。")


def _browse_recent_messages_for_workbench(client: MailClient, store: StateStore) -> None:
    limit = _ask_limit(default=10)
    offset = 0
    while True:
        messages = client.list_real_recent(limit, offset=offset)
        if not messages:
            print("没有更多邮件。")
            return
        page = offset // limit + 1
        print(f"\n邮件处理面板 - 第 {page} 页，每页 {limit} 封")
        print("-" * 40)
        for message in messages:
            store.upsert_mail(message)
        _show_messages(messages, allow_snippet=True)
        raw = input("选择邮件序号；n 下一页；q 返回: ").strip().lower()
        if raw == "q":
            return
        if raw == "n":
            if len(messages) < limit:
                print("已到最后一页。")
            else:
                offset += limit
            continue
        try:
            indexes = _parse_selection(raw, max_index=len(messages))
        except ValueError as error:
            print(f"选择无效: {error}")
            continue
        if len(indexes) != 1:
            print("一次只能处理一封邮件。")
            continue
        selected = messages[indexes[0] - 1]
        message = client.get_real_message(selected.id)
        if message is None:
            print("未找到该邮件。")
            continue
        moved = _message_actions_flow(client, store, message)
        if moved:
            print("该邮件已移动到垃圾箱，返回邮件列表。")


def _suggestion_queue_flow(client: MailClient, store: StateStore) -> None:
    rows = store.list_suggested_triage_queue(limit=_ask_limit(default=20))
    if not rows:
        print("暂无 AI 建议。请先返回主菜单选择 2 分类最近邮件。")
        return
    _show_suggestion_queue(rows)
    raw = input("请选择邮件序号，或 q 返回: ").strip().lower()
    if raw == "q":
        return
    try:
        indexes = _parse_selection(raw, max_index=len(rows))
    except ValueError as error:
        print(f"选择无效: {error}")
        return
    if len(indexes) != 1:
        print("一次只能处理一封邮件。")
        return
    row = rows[indexes[0] - 1]
    message = client.get_real_message(row.uid)
    if message is None:
        print("未找到该邮件。")
        return
    moved = _message_actions_flow(client, store, message)
    if moved:
        print("该邮件已移动到垃圾箱。")


def _queue_history_flow(store: StateStore) -> None:
    print()
    print("队列记录")
    print("1. 已处理")
    print("2. 已跳过")
    print("3. 全部状态")
    print("0. 返回")
    choice = input("请选择: ").strip()
    status_options = {
        "1": ("已处理", ("done",)),
        "2": ("已跳过", ("skipped",)),
        "3": ("全部状态", ("pending", "later", "done", "skipped")),
    }
    if choice == "0":
        return
    selected = status_options.get(choice)
    if selected is None:
        print("无效选项。")
        return

    title, statuses = selected
    rows = store.list_suggested_triage_queue(limit=_ask_limit(default=20), statuses=statuses)
    if not rows:
        print(f"暂无{title}队列记录。")
        return
    _show_suggestion_queue(rows, title=f"队列记录 - {title}")
    raw = input("请选择邮件序号，或 q 返回: ").strip().lower()
    if raw == "q":
        return
    try:
        indexes = _parse_selection(raw, max_index=len(rows))
    except ValueError as error:
        print(f"选择无效: {error}")
        return
    if len(indexes) != 1:
        print("一次只能恢复一封邮件。")
        return
    _queue_history_actions_flow(store, rows[indexes[0] - 1])


def _queue_history_actions_flow(store: StateStore, row: StoredTriage) -> None:
    print()
    print(f"队列记录: {row.uid} [{_queue_status_label(row.queue_status)}]")
    print(f"主题: {row.subject or '(无主题)'}")
    print("1. 改回待处理")
    print("2. 稍后处理")
    print("0. 返回")
    choice = input("请选择: ").strip()
    if choice == "1":
        _set_queue_status(store, row.uid, "pending")
        return
    if choice == "2":
        _set_queue_status(store, row.uid, "later")
        return
    if choice == "0":
        return
    print("无效选项。")


def _mail_search_flow(client: MailClient, store: StateStore) -> None:
    print()
    print("搜索 / 筛选邮件")
    print("1. 按关键词搜索主题 / 发件人")
    print("2. 只看未读")
    print("3. 只看已读")
    print("4. 按分类查看")
    print("5. 按队列状态查看")
    print("0. 返回")
    choice = input("请选择: ").strip()
    if choice == "0":
        return

    keyword = None
    is_seen = None
    classification = None
    queue_status = None
    if choice == "1":
        keyword = input("请输入关键词: ").strip()
        if not keyword:
            print("关键词不能为空。")
            return
    elif choice == "2":
        is_seen = False
    elif choice == "3":
        is_seen = True
    elif choice == "4":
        classification = _ask_classification_filter()
        if classification is None:
            return
    elif choice == "5":
        queue_status = _ask_queue_status_filter()
        if queue_status is None:
            return
    else:
        print("无效选项。")
        return

    rows = store.search_mail_items(
        limit=_ask_limit(default=20),
        keyword=keyword,
        is_seen=is_seen,
        classification=classification,
        queue_status=queue_status,
    )
    if not rows:
        print("暂无搜索结果。")
        return
    _show_mail_search_results(rows)
    raw = input("请选择邮件序号，或 q 返回: ").strip().lower()
    if raw == "q":
        return
    try:
        indexes = _parse_selection(raw, max_index=len(rows))
    except ValueError as error:
        print(f"选择无效: {error}")
        return
    if len(indexes) != 1:
        print("一次只能处理一封邮件。")
        return
    row = rows[indexes[0] - 1]
    message = client.get_real_message(row.uid)
    if message is None:
        print("未找到该邮件。")
        return
    moved = _message_actions_flow(client, store, message)
    if moved:
        print("该邮件已移动到垃圾箱。")


def _ask_classification_filter() -> str | None:
    print()
    print("选择分类")
    print("1. 忽略")
    print("2. 关注")
    print("3. 需要处理")
    print("0. 返回")
    choice = input("请选择: ").strip()
    values = {
        "1": "ignore",
        "2": "notify",
        "3": "respond",
    }
    if choice == "0":
        return None
    value = values.get(choice)
    if value is None:
        print("无效选项。")
    return value


def _ask_queue_status_filter() -> str | None:
    print()
    print("选择队列状态")
    print("1. 待处理")
    print("2. 稍后处理")
    print("3. 已处理")
    print("4. 已跳过")
    print("0. 返回")
    choice = input("请选择: ").strip()
    values = {
        "1": "pending",
        "2": "later",
        "3": "done",
        "4": "skipped",
    }
    if choice == "0":
        return None
    value = values.get(choice)
    if value is None:
        print("无效选项。")
    return value


def _show_mail_search_results(rows: list[StoredMailSearchResult]) -> None:
    print()
    print("搜索结果")
    print("-" * 40)
    for index, row in enumerate(rows, start=1):
        labels = [_stored_seen_label(row.is_seen)]
        if row.queue_status:
            labels.append(f"[{_queue_status_label(row.queue_status)}]")
        print(f"[{index}] {row.uid} {' '.join(labels)}")
        print(f"    发件人: {_clip(row.sender or '(未知)', 88)}")
        print(f"    主题:   {_clip(row.subject or '(无主题)', 88)}")
        if row.date:
            print(f"    时间:   {row.date}")
        if row.classification:
            print(f"    分类:   {_classification_label(row.classification)}")
        if row.suggested_action:
            print(f"    建议:   {_suggested_action_label(row.suggested_action)}")
        print()


def _show_suggestion_queue(rows: list[StoredTriage], *, title: str = "AI 建议队列") -> None:
    print()
    print(title)
    print("-" * 40)
    for index, row in enumerate(rows, start=1):
        print(f"[{index}] {row.uid} [{_queue_status_label(row.queue_status)}]")
        print(f"    建议: {_suggested_action_label(row.suggested_action)}")
        print(f"    分类: {_classification_label(row.classification)}")
        print(f"    主题: {row.subject or '(无主题)'}")
        print(f"    原因: {_clip(row.reason, 110)}")
        if row.action_reason:
            print(f"    建议原因: {_clip(row.action_reason, 110)}")
        print()


def _message_actions_flow(client: MailClient, store: StateStore, message: MailMessage) -> bool:
    while True:
        print()
        print(f"邮件处理: {message.id} {_seen_label(message)}")
        print(f"主题: {_clip(message.subject or '(无主题)', 100)}")
        _show_message_suggestion(store, message.id)
        print("1. 查看全文")
        print("2. DeepSeek 翻译成中文")
        print("3. DeepSeek 生成回复草稿")
        print("4. 标记为已读")
        print("5. 移动到垃圾箱")
        print("6. 标记为已处理")
        print("7. 稍后处理")
        print("8. 跳过")
        print("0. 返回邮件列表")
        choice = input("请选择: ").strip()
        if choice == "1":
            message = _show_full_message_action(client, store, message)
            continue
        if choice == "2":
            _translate_selected_message(store, message)
            continue
        if choice == "3":
            _draft_selected_message(store, message)
            continue
        if choice == "4":
            message = _mark_message_seen(client, store, message)
            continue
        if choice == "5":
            if _move_selected_message_to_trash(client, store, message):
                return True
            continue
        if choice == "6":
            _set_queue_status(store, message.id, "done")
            return False
        if choice == "7":
            _set_queue_status(store, message.id, "later")
            return False
        if choice == "8":
            _set_queue_status(store, message.id, "skipped")
            return False
        if choice == "0":
            return False
        print("无效选项。")


def _show_full_message_action(client: MailClient, store: StateStore, message: MailMessage) -> MailMessage:
    _show_full_message(message)
    _show_message_resources(message)
    if message.html_body and _ask_yes_no(
        "此邮件包含 HTML。导出到本地并用浏览器打开? 远程图片可能被浏览器加载",
        default=False,
    ):
        export_path = _export_html(message)
        print(f"已导出: {export_path}")
        webbrowser.open(export_path.resolve().as_uri())
    if message.is_seen is not True and _ask_yes_no("是否将此邮件标记为已读并同步 QQ 邮箱?", default=False):
        return _mark_message_seen(client, store, message, require_confirmation=False)
    return message


def _translate_selected_message(store: StateStore, message: MailMessage) -> None:
    if not _confirm_translate_with_ai():
        return
    translation = _ai_agent().translate_message(message)
    store.upsert_mail(message)
    store.log_action("translate", uid=message.id, detail=message.subject)
    _show_translation(message, translation)


def _draft_selected_message(store: StateStore, message: MailMessage) -> None:
    if not _confirm_send_to_ai():
        return
    draft = _ai_agent().draft_reply(message)
    store.upsert_mail(message)
    stored = store.save_draft(draft)
    store.log_action("draft_generated", uid=message.id, detail=stored.subject)
    _set_queue_status(store, message.id, "done", announce=False)
    _show_stored_draft(stored)
    print("已保存草稿，请到菜单 3 草稿箱查看待发送草稿。")


def _mark_message_seen(
    client: MailClient,
    store: StateStore,
    message: MailMessage,
    *,
    require_confirmation: bool = True,
) -> MailMessage:
    if message.is_seen is True:
        print("该邮件已是已读。")
        return message
    if require_confirmation and not _ask_yes_no("确认将此邮件标记为已读并同步 QQ 邮箱?", default=False):
        print("已取消标记已读。")
        return message
    if client.mark_real_seen(message.id):
        seen_message = replace(message, is_seen=True)
        store.upsert_mail(seen_message)
        store.log_action("mark_seen", uid=message.id, detail=message.subject)
        _set_queue_status(store, message.id, "done", announce=False)
        print("已同步标记为已读。")
        return seen_message
    print("标记已读失败。")
    return message


def _move_selected_message_to_trash(client: MailClient, store: StateStore, message: MailMessage) -> bool:
    print()
    print("将移动以下邮件到垃圾箱:")
    _show_messages([message], allow_snippet=True)
    if not _ask_yes_no("确认移动 1 封邮件到垃圾箱?", default=False):
        print("已取消。")
        return False
    trash = client.move_real_to_trash([message.id])
    store.upsert_mail(message)
    store.log_action("move_to_trash", uid=message.id, detail=f"{message.subject} -> {trash}")
    _set_queue_status(store, message.id, "done", announce=False)
    print(f"已移动到垃圾箱: {trash}")
    return True


def _set_queue_status(store: StateStore, mail_id: str, status: str, *, announce: bool = True) -> bool:
    set_status = getattr(store, "set_triage_queue_status", None)
    if set_status is None:
        return False
    updated = set_status(mail_id, status)
    if not updated:
        if announce:
            print("该邮件暂无 AI 建议队列记录，无法更新处理状态。")
        return False
    log_action = getattr(store, "log_action", None)
    if log_action is not None:
        log_action("queue_status", uid=mail_id, detail=status)
    if announce:
        print(f"AI 建议队列状态已更新为: {_queue_status_label(status)}")
    return True


def _show_message_suggestion(store: StateStore, mail_id: str) -> None:
    get_triage_result = getattr(store, "get_triage_result", None)
    if get_triage_result is None:
        print("AI 建议: 暂无")
        return
    row = get_triage_result(mail_id)
    if row is None:
        print("AI 建议: 暂无")
        return
    print(f"AI 建议: {_suggested_action_label(row.suggested_action)}")
    print(f"队列状态: {_queue_status_label(row.queue_status)}")
    if row.action_reason:
        print(f"建议原因: {_clip(row.action_reason, 100)}")


def _show_translation(message: MailMessage, translation: MailTranslation) -> None:
    print()
    print(f"ID: {message.id} {_seen_label(message)}")
    print(f"原主题: {message.subject}")
    print(f"中文主题: {translation.subject_zh}")
    print("-" * 60)
    print("中文翻译:")
    print(_wrap_preserving_lines(translation.body_zh or "(无翻译内容)", width=88))
    print("-" * 60)


def _draft_send_flow(client: MailClient, store: StateStore) -> None:
    print()
    print("草稿")
    print("1. 查看待发送草稿")
    print("2. 查看已发送草稿")
    print("3. 查看全部草稿")
    print("0. 返回")
    choice = input("请选择: ").strip()
    if choice == "0":
        return
    status_by_choice = {
        "1": "pending",
        "2": "sent",
        "3": "all",
    }
    status = status_by_choice.get(choice)
    if status is None:
        print("无效选项。")
        return
    _browse_drafts(client, store, status=status)


def _browse_drafts(client: MailClient, store: StateStore, *, status: str) -> None:
    drafts = store.list_drafts(limit=_ask_limit(default=20), status=status)
    if not drafts:
        print(f"暂无{_draft_status_view_label(status)}草稿。")
        return
    _show_draft_list(drafts)
    raw = input("请选择要查看的草稿序号，或 q 取消: ").strip().lower()
    if raw == "q":
        return
    try:
        indexes = _parse_selection(raw, max_index=len(drafts))
    except ValueError as error:
        print(f"选择无效: {error}")
        return
    if len(indexes) != 1:
        print("一次只能查看一封草稿。")
        return
    draft = drafts[indexes[0] - 1]
    if draft.send_status not in {"pending", "failed"}:
        _show_stored_draft(draft)
        if draft.send_status == "sent":
            print("已发送草稿只读，不能编辑或重复发送。")
        else:
            print("该草稿当前不可编辑或发送。")
        return
    _draft_actions_flow(client, store, draft.draft_id)


def _show_draft_list(drafts: list[StoredDraft]) -> None:
    for index, draft in enumerate(drafts, start=1):
        print(f"[{index}] {draft.draft_id}")
        print(f"    状态: {_draft_status_label(draft)}")
        if draft.sent_at:
            print(f"    发送时间: {draft.sent_at}")
        if draft.send_error:
            print(f"    状态说明: {_clip(draft.send_error, 120)}")
        print(f"    To: {draft.to_addr}")
        print(f"    Subject: {draft.subject}")
        print(f"    回复线程: {'有' if draft.reply_to_message_id else '无'}")
        print(f"    Preview: {_clip(draft.body_preview, 120)}")
        print()


def _draft_status_label(draft: StoredDraft) -> str:
    labels = {
        "pending": "待发送",
        "sending": "发送中",
        "sent": "已发送",
        "failed": "发送失败，可重试",
        "unknown": "发送结果不确定，已锁定",
    }
    return labels.get(draft.send_status, draft.send_status)


def _draft_status_view_label(status: str) -> str:
    labels = {
        "pending": "待发送",
        "sent": "已发送",
        "all": "",
    }
    return labels.get(status, "")


def _draft_actions_flow(client: MailClient, store: StateStore, draft_id: str) -> None:
    while True:
        draft = store.get_draft(draft_id)
        if draft is None or draft.send_status not in {"pending", "failed"}:
            print("草稿不存在或当前状态不允许编辑和发送。")
            return
        _show_stored_draft(draft)
        print("1. 发送")
        print("2. 编辑主题")
        print("3. 编辑正文")
        print("0. 返回")
        choice = input("请选择: ").strip()
        if choice == "1":
            _send_stored_draft(client, store, draft)
            return
        if choice == "2":
            _edit_draft_subject(store, draft)
            continue
        if choice == "3":
            _edit_draft_body(store, draft)
            continue
        if choice == "0":
            return
        print("无效选项。")


def _show_stored_draft(draft: StoredDraft) -> None:
    print()
    print(f"Draft: {draft.draft_id}")
    print(f"状态: {_draft_status_label(draft)}")
    print(f"To: {draft.to_addr}")
    print(f"Subject: {draft.subject}")
    print(f"回复线程: {'有' if draft.reply_to_message_id else '无'}")
    print("-" * 60)
    print(_wrap_preserving_lines(draft.body, width=88))
    print("-" * 60)


def _edit_draft_subject(store: StateStore, draft: StoredDraft) -> None:
    subject = input("请输入新主题，空输入取消: ").strip()
    if not subject:
        print("已取消编辑主题。")
        return
    if store.update_draft(draft.draft_id, subject=subject, body=draft.body):
        store.log_action("draft_edited", uid=draft.uid, detail=f"subject: {subject}")
        print("主题已保存。")
    else:
        print("主题保存失败，草稿可能已发送或不存在。")


def _edit_draft_body(store: StateStore, draft: StoredDraft) -> None:
    print("请输入新正文。单独输入 .save 保存，输入 .cancel 取消。")
    body = _read_multiline_body()
    if body is None:
        print("已取消编辑正文。")
        return
    if not body.strip():
        print("正文不能为空，已取消保存。")
        return
    if store.update_draft(draft.draft_id, subject=draft.subject, body=body):
        store.log_action("draft_edited", uid=draft.uid, detail="body")
        print("正文已保存。")
    else:
        print("正文保存失败，草稿可能已发送或不存在。")


def _read_multiline_body() -> str | None:
    lines = []
    while True:
        line = input()
        command = line.strip().lower()
        if command == ".save":
            return "\n".join(lines)
        if command == ".cancel":
            return None
        lines.append(line)


def _send_stored_draft(client: MailClient, store: StateStore, draft: StoredDraft) -> None:
    if not _ask_yes_no(f"确认发送到 {draft.to_addr}?", default=False):
        print("已取消发送。")
        return
    try:
        result = DraftService(client, store).send_stored_draft(
            draft.draft_id,
            dry_run=False,
            source="interactive CLI",
        )
    except DraftServiceError as error:
        print(f"发送失败: {error}")
        return
    print(result)


def _parse_mail_id_list(raw_value: str) -> list[str]:
    values = []
    for part in raw_value.replace("\n", ",").split(","):
        value = part.strip()
        if not value:
            continue
        if value.isdigit():
            value = f"uid:{value}"
        values.append(value)
    return values


def _select_messages_for_trash(client: MailClient) -> list[str]:
    limit = _ask_limit(default=10)
    offset = 0
    while True:
        messages = client.list_real_recent(limit, offset=offset)
        if not messages:
            print("没有更多邮件。")
            return []
        page = offset // limit + 1
        print(f"\n第 {page} 页，每页 {limit} 封")
        print("-" * 40)
        _show_messages(messages, allow_snippet=True)
        raw_selection = input("选择要移动的序号，支持 1,3-5,all；n 下一页；q 取消: ").strip().lower()
        if raw_selection == "q":
            return []
        if raw_selection == "n":
            offset += limit
            continue
        try:
            selected_indexes = _parse_selection(raw_selection, max_index=len(messages))
        except ValueError as error:
            print(f"选择无效: {error}")
            continue
        return [messages[index - 1].id for index in selected_indexes]


def _parse_selection(raw_value: str, *, max_index: int) -> list[int]:
    value = raw_value.strip().lower()
    if not value:
        raise ValueError("请输入序号、范围、all、n 或 q。")
    if value == "all":
        return list(range(1, max_index + 1))
    selected = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"范围格式错误: {token}")
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"范围起点不能大于终点: {token}")
            selected.extend(range(start, end + 1))
        else:
            if not token.isdigit():
                raise ValueError(f"不是有效序号: {token}")
            selected.append(int(token))
    if not selected:
        raise ValueError("没有选择任何邮件。")
    unique = []
    for index in selected:
        if index < 1 or index > max_index:
            raise ValueError(f"序号超出范围: {index}")
        if index not in unique:
            unique.append(index)
    return unique


def _show_full_message(message: MailMessage) -> None:
    print()
    print(f"ID: {message.id} {_seen_label(message)}")
    print(f"发件人: {message.sender}")
    print(f"收件人: {message.recipient}")
    print(f"主题: {message.subject}")
    if message.date:
        print(f"时间: {message.date}")
    print("-" * 60)
    print(_indent_wrapped(message.body or "(无正文)", indent="", width=88))
    print("-" * 60)


def _show_message_resources(message: MailMessage) -> None:
    print("资源:")
    print(f"  HTML 富文本: {'有' if message.html_body else '无'}")
    print(f"  远程图片: {len(message.remote_images)}")
    print(f"  内嵌图片: {len(message.inline_images)}")
    print(f"  附件: {len(message.attachments)}")
    if message.attachments:
        for attachment in message.attachments[:10]:
            size = f" {attachment.size} bytes" if attachment.size is not None else ""
            print(f"    - {attachment.filename} ({attachment.content_type}{size})")


def _export_html(message: MailMessage, export_dir: Path | None = None) -> Path:
    if not message.html_body:
        raise RuntimeError("This message has no HTML body to export.")
    root = export_dir or Path.cwd() / ".mail_exports"
    root.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(message.id) + ".html"
    path = root / filename
    path.write_text(_wrap_html_document(message), encoding="utf-8")
    return path


def _wrap_html_document(message: MailMessage) -> str:
    return (
        "<!doctype html>\n"
        "<html><head><meta charset=\"utf-8\">"
        f"<title>{_escape_html(message.subject)}</title>"
        "</head><body>\n"
        f"<!-- Exported from {message.id}. Remote resources may load in browser. -->\n"
        f"{message.html_body}\n"
        "</body></html>\n"
    )


def _safe_filename(value: str) -> str:
    safe = []
    for char in value:
        if char.isalnum() or char in {"-", "_"}:
            safe.append(char)
        else:
            safe.append("-")
    return "".join(safe).strip("-") or "mail"


def _seen_label(message: MailMessage) -> str:
    if message.is_seen is True:
        return "[已读]"
    if message.is_seen is False:
        return "[未读]"
    return "[未知]"


def _stored_seen_label(value: bool | None) -> str:
    if value is True:
        return "[已读]"
    if value is False:
        return "[未读]"
    return "[未知]"


def _classification_label(value: str) -> str:
    labels = {
        "ignore": "忽略",
        "notify": "关注",
        "respond": "需要处理",
    }
    return labels.get(value, value)


def _suggested_action_label(value: str) -> str:
    labels = {
        SuggestedAction.READ_FULL.value: "查看全文",
        SuggestedAction.TRANSLATE.value: "翻译成中文",
        SuggestedAction.DRAFT_REPLY.value: "生成回复草稿",
        SuggestedAction.MARK_SEEN.value: "标记已读",
        SuggestedAction.MOVE_TO_TRASH.value: "移动到垃圾箱",
        SuggestedAction.NO_ACTION.value: "无需处理",
    }
    return labels.get(value, value)


def _queue_status_label(value: str) -> str:
    labels = {
        "pending": "待处理",
        "later": "稍后处理",
        "done": "已处理",
        "skipped": "已跳过",
    }
    return labels.get(value, value)


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _normalize_subject(subject: str) -> str:
    normalized = " ".join(subject.split()).strip()
    prefixes = ("Re:", "RE:", "Fw:", "FW:", "Fwd:", "FWD:")
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
    return normalized or "(无主题)"


def _indent_wrapped(value: str, *, indent: str, width: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        return indent
    return fill(
        normalized,
        width=width,
        initial_indent=indent,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _wrap_preserving_lines(value: str, *, width: int) -> str:
    if not value:
        return ""
    wrapped_lines = []
    for line in value.splitlines():
        if not line.strip():
            wrapped_lines.append("")
            continue
        wrapped_lines.append(
            fill(
                line.strip(),
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(wrapped_lines)


if __name__ == "__main__":
    raise SystemExit(main())

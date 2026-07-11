# QQ Mail Agent CLI 架构说明

更新时间：2026-07-10

这份文档用于从架构角度理解 `qq-mail-agent-cli`。它描述当前已经实现的能力和边界，不把项目夸大为生产级邮箱系统，也不声称已经接入 LangGraph。

## 一句话架构

`qq-mail-agent-cli` 是一个以 Python 为邮件 Agent Core、以 React 为共享工作台、以 Tauri 为 Windows 常驻外壳的本机邮件 Agent：用 IMAP UID 增量同步和 IDLE 感知邮件，用 DeepSeek 做洞察与草稿生成，用 SQLite 保存可恢复状态，最终发送仍由用户确认。

```text
Windows / CLI / browser
  -> Tauri shell or direct Python entry
  -> MailClient (IMAP UID catch-up + IDLE wake-up)
  -> MailSyncService
  -> MailAgent + DeepSeek
  -> MailInsight / local Draft / StartupSummary
  -> StateStore(SQLite WAL)
  -> React / CLI human review
  -> DraftService + atomic draft claim
  -> explicit SMTP send / IMAP append sent copy
```

核心原则是：桌面后台可以自动读取新邮件文本、调用 DeepSeek、保存摘要和生成本地草稿；不能自动发送、移动垃圾箱或永久删除。邮箱 `\Seen`、Agent 分析状态、回复状态和通知状态相互独立，stdout 事件也不等于通知已经送达。

## Windows 桌面 Agent

```text
Windows 登录 --autostart
-> Tauri 主窗口保持隐藏，托盘常驻
-> 从 Windows 凭据管理器读取授权码 / API Key
-> 通过环境变量启动 PyInstaller sidecar
-> sidecar 绑定动态 127.0.0.1 端口并输出 ready
-> Rust 将随机会话 token 只交给当前 WebView 内存
-> UIDVALIDITY + last_processed_uid 补偿同步
-> AI 洞察；needs_reply=true 时生成本地草稿
-> startup_summary 持久化并发一条 Windows toast
-> IMAP IDLE 只作为唤醒信号，醒来后仍按游标 catch-up
-> important / urgent 进入通知 outbox
-> Rust 成功创建 toast 后按 mail_key ACK notified
-> 点击 toast 显示窗口并消费持久的导航目标
```

Tauri 负责窗口、托盘、单实例、首次默认自启及用户开关、Windows toast 点击、凭据和 sidecar 有界退避重启。Python 负责邮箱协议、AI、SQLite、增量同步、IDLE 和 loopback API。React 不直接保存密钥或会话 token。

桌面通知策略是：启动补偿同步发一条汇总；普通 `sync_summary` 只更新工作台、不弹系统通知；单封通知只接受分析成功且等级为 `important / urgent` 的事件。低置信度、解析失败和隔离邮件使用 `attention_required` 刷新待查看数据，不伪造重要等级。

## 秘书巡检编排

Web 的“开始巡检”不是另一套邮箱客户端能力，而是对现有感知、决策和状态工具的一次显式 Agent 编排：

```text
用户确认开始巡检
-> MailClient 读取最新 20 封（BODY.PEEK，不改变已读）
-> 过滤已读和本地已分类邮件
-> MailAgent 逐封分类，单封失败继续
-> StateStore 保存成功分类
-> 合并 pending / later 队列
-> 生成 reply / review / status / no_action 四组处理计划
-> 用户打开计划项后进入现有人工处理流程
```

`SecretaryInspectionService` 不调用标记已读、生成草稿、SMTP 发送或移动垃圾箱。它只负责观察、决策、汇总和制定计划；真实副作用仍由用户进入单封邮件后单独触发。巡检只在 `action_log` 保存计数摘要，不持久化邮件正文或完整报告。

## 当前能力边界

当前已经支持：

- 读取 QQ 邮箱最近邮件、分页展示、显示已读/未读状态。
- 查看真实邮件全文并同步标记已读；Web 打开未读邮件后自动标记已读，CLI 保留显式标记入口。
- 识别 HTML、远程图片、内嵌图片和附件数量。
- 将 HTML 邮件导出到本地浏览器查看。
- DeepSeek 分类邮件：`ignore`、`notify`、`respond`。
- DeepSeek 推荐下一步动作：查看全文、翻译、生成草稿、标记已读、移动垃圾箱、无需处理。
- DeepSeek 翻译英文邮件为中文。
- DeepSeek 生成回复草稿。
- SQLite 保存邮件元信息、分类结果、四态建议队列、草稿版本、发送状态和操作记录。
- 草稿编辑、二次确认、SMTP 发送、IMAP 保存已发送副本；Web/CLI 的发送路径共享 `DraftService`。
- 草稿发送状态 `pending / sending / sent / failed / unknown`，通过 SQLite 原子 claim 阻止并发重复投递。
- 同一基础草稿重新生成时创建唯一版本，并通过 `base_draft_id`、`draft_version`、`supersedes_id` 保留版本关系。
- 单封或批量移动邮件到垃圾箱。
- 配置体检：本地配置检查、IMAP 登录检查、SMTP 登录检查、DeepSeek ping。
- 本机 Web 工作台：最近邮件、AI 待办、元信息搜索、四态队列、邮件操作、草稿、操作记录和配置体检。
- Web 明暗主题，以及移动端“列表 -> 阅读 -> 操作/草稿”单面板流程。
- Windows Tauri 常驻桌面端、托盘关闭语义、单实例、可关闭的开机自启和 sidecar 有界重启。
- UIDVALIDITY/UID 增量游标、首次有限窗口、失败隔离、通知 outbox、启动摘要 ACK 与 IMAP IDLE 断线恢复。
- 正交邮件洞察、五类查询视图，以及待回复邮件自动生成但不自动发送的本地草稿。
- Windows 凭据管理器密钥存储、AppData 普通配置、动态 loopback API 和会话 Bearer token。

当前暂不支持：

- 自动发送邮件。
- 自动永久删除邮件。
- HTML 回复、附件回复、CC、BCC。
- 多账号管理。
- prompt 版本管理和离线评测集。
- LangGraph 显式状态图。
- macOS / Linux 桌面打包。

## 模块职责

### `models.py`

数据协议层。定义 Agent 内部流转的稳定对象：

- `MailMessage`：邮件输入。
- `TriageResult`：分类和建议动作。
- `Draft`：回复草稿。
- `MailTranslation`：翻译结果。
- `DraftSendResult`：发送结果。

学习重点：先稳定数据结构，再谈 Agent 流程。

### `mail_client.py`

邮箱工具层。封装真实 IMAP / SMTP 副作用：

- 列表读取和全文读取。
- `BODY.PEEK[]` 只读读取，避免列表读取自动标记已读。
- 标记已读（CLI 显式触发，Web 打开未读邮件后自动触发）。
- 移动到垃圾箱。
- SMTP 发送回复。
- IMAP 保存已发送副本。

学习重点：Agent 的 tool 是真实副作用边界，不只是函数调用。

### `llm_client.py`

DeepSeek 通道层。只负责调用 OpenAI-compatible `/chat/completions` 接口和返回模型内容。

学习重点：低层 LLM 客户端不写邮件业务规则，方便后续替换模型或增加评测。

### `agent.py`

AI 决策和生成层。负责：

- `triage()`：分类和推荐动作。
- `draft_reply()`：生成回复草稿。
- `translate_message()`：翻译邮件。

学习重点：Agent 核心是结构化输入输出和可控失败处理，不是把所有逻辑塞进 prompt。

### `storage.py`

状态层。本地 SQLite 保存：

- 邮件元信息。
- 分类结果。
- 建议队列状态：`pending / later / done / skipped`。
- 草稿正文、版本关系和发送状态。
- 操作日志。
- 邮件洞察、分析/回复/通知独立状态。
- `mailbox + UIDVALIDITY + last_processed_uid` 同步游标。
- 启动摘要、通知 outbox、失败重试和隔离记录。

它不保存原始邮件完整正文、HTML、附件或密钥，但会保存本应用生成的草稿正文。

发送前，`claim_draft_for_send()` 在 `BEGIN IMMEDIATE` 事务中把 `pending` 或 `failed` 原子更新为 `sending`，并记录本次 `attempt_id`；完成与失败更新都要求草稿仍属于同一次发送尝试。该状态转换是 Web/CLI 防止并发重复 SMTP 投递的持久化边界。

学习重点：有状态后，Agent 才能避免重复分类、保留草稿演进历史，并为真实发送提供原子占用。

### `services/draft_service.py`

CLI 与 Web 共用的草稿服务层。负责：

- 从 SQLite 读取指定草稿，拒绝不存在、已发送、发送中或结果不确定的草稿。
- 保存新生成的草稿版本。
- 原子 claim 草稿后调用 SMTP，并将结果收敛到 `sent / failed / unknown`。
- SMTP 成功但本地完成状态无法写入时锁定草稿，避免自动重投。

参数式 `send`、交互菜单和 Web API 都复用这个服务，不再各自拼接发送状态逻辑。

### `services/mail_sync_service.py` / `services/imap_idle_watcher.py`

桌面后台编排层。`MailSyncService` 按持久 UID 游标拉取、逐封分析、保存洞察和预生成草稿；一封失败不会阻塞后续邮件。`ImapIdleWatcher` 把 IDLE 当作唤醒信号，连接/续租/恢复后都通过同一个增量同步入口 catch-up，并在不支持 IDLE 时退化到低频轮询。

重复 IDLE、重连和 stdout 重放都依赖数据库幂等键，不以邮箱已读状态判断是否处理过。它们不调用 SMTP 或垃圾箱操作。

### `desktop_worker.py`

生产 sidecar 入口。只接受 `127.0.0.1` 和动态/受控端口，从 `QQ_MAIL_AGENT_SESSION_TOKEN` 环境变量读取随机 token，启动 FastAPI、启动补偿同步和 IDLE watcher，并监控 Tauri 父进程。父进程消失后自行退出。

sidecar stdout 只输出 `QQMAIL_EVENT {json}` 脱敏事件；stderr 被 Rust 排空但不复制到日志，避免供应商异常携带邮件内容。

### `interactive.py`

当前手写工作流和 CLI 编排层。负责：

- 主菜单和子菜单。
- 邮件处理面板。
- AI 建议队列。
- 单封邮件操作面板。
- 人工确认。
- 把工具、Agent 和状态层串起来。

学习重点：在接 LangGraph 之前，`interactive.py` 就是这个项目的 workflow orchestrator。

### `web_server.py`

本机 Web API 层。负责把 HTTP 请求转成现有核心模块调用：

- `MailClient`：读取、标记已读、移动垃圾箱、发送草稿。
- `MailAgent`：分类、翻译、生成草稿。
- `StateStore`：保存邮件元信息、分类、队列、草稿和日志。
- `DraftService`：统一草稿版本保存与真实发送状态转换。
- `health.py`：配置体检。

它不重新实现 Agent 逻辑，只是新增一个浏览器入口。默认只监听 `127.0.0.1`。

学习重点：Web 入口应该复用核心能力，而不是复制一套业务逻辑。

### `web/`

React / TypeScript / Vite / TailwindCSS 前端工作台。桌面端采用三栏结构：

- 左侧“最近 / AI 待办 / 搜索”：分页浏览最近邮件；按 `pending / later / done / skipped` 查看本地队列；按主题/发件人、已读、分类和队列状态搜索 SQLite 元信息。
- 中间阅读区：邮件全文、资源提示和翻译结果。打开未读邮件后自动同步标记已读，并由后端把已有本地队列记录更新为 `done`。
- 右侧“操作 / 草稿 / 记录”：邮件动作、`pending / sent / all` 草稿筛选、草稿编辑和发送、操作日志。
- 顶栏配置体检：本地检查，以及逐项确认后的 IMAP、SMTP、DeepSeek 连通检查。
- light / dark theme；移动端按“列表 -> 阅读 -> 操作/草稿”一次显示一个面板。

学习重点：前端只是 human review surface，不能降低 DeepSeek、发送和删除的确认要求。

### `platform/`

- `platform/pc`：现有浏览器开发入口，不移动 `web/`。
- `platform/cli`：现有 Python CLI 适配入口，不复制 Core。
- `platform/tauri`：Windows 壳、托盘、自启、通知、凭据和 sidecar supervision。

生产打包先由 `packaging/qq_mail_agent_sidecar.spec` 生成 target-triple sidecar，再由 `tauri.bundle.conf.json` 作为 build-only 配置把它加入 NSIS；源码 `.env`、SQLite、日志和邮件导出都不进入安装包。

### `health.py`

配置和外部依赖体检层。负责：

- 检查本地环境变量是否存在。
- 检查 SQLite 路径是否可写。
- 用户确认后测试 IMAP、SMTP、DeepSeek 连通性。
- 输出时隐藏授权码和 API Key。

学习重点：真实 Agent 项目要能定位配置问题，同时不能泄漏密钥。

## Agent 主链路

最完整的处理链路是：

```text
1. 用户进入 wx_email
2. MailClient 通过 IMAP 读取邮件列表
3. 邮件被转成 MailMessage
4. 用户确认后，MailAgent 调用 DeepSeek 分类
5. 分类结果 TriageResult 写入 StateStore
6. 用户进入 CLI 邮件处理面板或 Web 工作台，按最近邮件、AI 待办或搜索结果选择邮件
7. Web 打开未读邮件后自动同步已读；`mark-seen` 同时把已有本地队列记录更新为 `done`
8. 用户翻译、生成草稿、调整队列状态或移动垃圾箱
9. 生成草稿时，Draft 作为新版本写入 StateStore，状态为 `pending`，并记录它替代的上一版本
10. 用户进入草稿箱，编辑、保存并确认发送
11. DraftService 从 SQLite 原子 claim 草稿：`pending / failed -> sending`
12. MailClient 通过 SMTP 发送，并尝试通过 IMAP APPEND 保存已发送副本
13. DraftService 将状态收敛为 `sent / failed / unknown`，StateStore 记录 action_log
```

这条链路体现了 Agent 的五个基本组成：

| Agent 组成 | 当前实现 |
| --- | --- |
| 感知 | `MailClient` 读取 QQ 邮箱 |
| 决策 | `MailAgent.triage()` 调用 DeepSeek |
| 工具 | IMAP、SMTP、SQLite、DeepSeek |
| 状态 | `StateStore` 保存分类、草稿、队列和日志 |
| 人工审批 | `interactive.py` / Web 工作台在 DeepSeek、发送和删除前确认；Web 打开邮件自动标记已读是明确例外 |

## 状态流转

分类结果有本地队列状态：

```text
pending -> done
pending -> later
pending -> skipped
later   -> done
later   -> skipped
done/skipped -> pending/later
```

含义：

- `pending`：待处理，默认进入 AI 建议队列。
- `later`：稍后处理，仍进入队列，但优先级低于待处理。
- `done`：已处理，默认不再进入待办队列。
- `skipped`：已跳过，默认不再进入待办队列。

注意：这个状态只代表本地 workflow 进度，不等于 QQ 邮箱的已读、已删除或已发送状态。不过当前 `mark-seen` 成功后会主动把已有分类记录更新为 `done`，因此 Web 打开未读邮件时，该邮件可能从待处理队列移到已处理。

草稿发送状态：

```text
pending --atomic claim--> sending -> sent
failed  --atomic claim--> sending -> sent
                              \-> failed
                              \-> unknown
```

含义：

- `pending`：待发送，可编辑、可发送。
- `sending`：一次发送已获得原子占用，其他 Web/CLI 请求不能再次投递。
- `sent`：SMTP 已完成；如果 IMAP 保存已发送副本失败，警告写入 `send_error`，状态仍是 `sent`，不会重发。
- `failed`：SMTP 调用明确失败，可编辑并由用户显式重试。
- `unknown`：SMTP 投递调用抛出异常，或 SMTP 可能已完成但本地完成状态写入失败；无法证明邮件未投递时，为避免重复发送而锁定。

进程在 `sending` 期间中断也可能留下锁定的 `sending`。当前没有把 `sending / unknown` 解锁为可重试的自动恢复操作；用户需先人工核对 QQ 邮箱，再重新生成一个草稿版本继续处理。新版本会保留 `supersedes_id`，但它不会自动判断旧版本是否已经投递，所以核对前发送新版本仍可能重复投递。

草稿版本流转独立于发送状态：

```text
base draft v1 --superseded by--> base draft v2 --superseded by--> v3
```

重新生成不会覆盖旧草稿；唯一 `draft_id`、`base_draft_id`、`draft_version` 和 `supersedes_id` 保留待发送、已发送和异常版本历史。

## Human-in-the-loop 安全边界

当前安全策略：

- Web 打开未读邮件后自动标记已读，这是保留的产品行为；请求序列校验确保快速切换时只处理当前有效选择。
- 真实邮件内容发送给 DeepSeek 前必须确认。
- 翻译真实邮件前必须确认。
- 生成真实邮件草稿前必须确认。
- 移动到垃圾箱前必须确认。
- 发送草稿前必须展示完整 `To` / `Subject` / `Body` 并确认。
- 已发送草稿只读，避免重复发送。
- `sending / unknown` 草稿也只读并拒绝发送；`failed` 只允许人工显式重试。
- SQLite 原子 claim 保证同一草稿的并发 Web/CLI 发送请求只有一个能进入 SMTP。
- 建议动作不会自动执行。
- 配置体检的 IMAP / SMTP / DeepSeek 外部检查必须单独确认。
- Web API 默认只绑定 `127.0.0.1`，不作为公网服务。
- Web 前端不展示、不保存授权码或 API Key。
- `list --real` 默认不展示正文摘要。
- SQLite 不保存原始邮件完整正文、HTML、附件或密钥。

这个项目适合学习真实 Agent 的原因在这里：模型可以参与决策，但真实副作用必须经过人。

## 本地状态和隐私边界

`StateStore` 会保存：

- 邮件 UID、发件人、主题、时间、已读状态等元信息。
- 分类结果、分类理由、建议动作、建议原因。
- 本地队列状态。
- 本应用生成的草稿、版本关系、发送状态、错误和发送尝试元数据。
- 操作日志。

`StateStore` 不保存：

- QQ 邮箱授权码。
- DeepSeek API Key。
- 原始邮件完整正文。
- 原始 HTML。
- 附件内容。
- 翻译后的正文。

这能让 CLI 有记忆，同时减少本地敏感数据沉积。

## 与 LangGraph 的映射

当前没有接入 LangGraph，但概念可以直接映射：

| 当前实现 | LangGraph 概念 |
| --- | --- |
| `MailMessage` / `TriageResult` / `Draft` | State 字段 |
| `MailClient.list_real_recent()` | fetch mails node / tool |
| `MailAgent.triage()` | triage node |
| `MailAgent.draft_reply()` | draft node |
| `MailAgent.translate_message()` | translate node |
| `StateStore` | checkpoint / memory / persistence / atomic send claim |
| `interactive.py` 人工确认 | human-in-the-loop interrupt |
| `web_server.py` + `web/` | human review surface / local control plane |
| `DraftService.send_stored_draft()` | shared send workflow / idempotency boundary |
| `classification` / `suggested_action` | conditional edges |

未来 LangGraph 版本可以拆成：

```text
fetch_mails
-> filter_unread_and_untriaged
-> triage
-> route_by_suggested_action
   -> no_action: save_result
   -> translate: human_review
   -> draft_reply: draft
   -> mark_seen: human_review
   -> move_to_trash: human_review
-> human_review
-> execute_tool_or_skip
-> log_result
```

迁移时不要先追求图复杂，而是先把现在 `interactive.py` 里的稳定流程抽成纯 workflow/service，再把这些函数挂到 graph node 上。

## 后续演进路径

建议按这个顺序演进：

1. 保持当前 CLI 可用，先沉淀学习文档和操作经验。
2. 把 `interactive.py` 中稳定的业务动作拆到 service/workflow 层。
3. 增加离线样例和分类评测，避免 prompt 变更后质量不可控。
4. 再引入 LangGraph，把状态、节点、条件边和 human interrupt 显式化。
5. 后续再考虑桌面打包、多账号、附件和 HTML 回复。

当前最重要的不是继续堆功能，而是能清楚讲出：输入是什么、模型判断什么、工具能做什么、状态怎么保存、人在哪里确认。

## 测试与验证边界

后端与 CLI：

```powershell
python -m pytest -p no:cacheprovider
```

Web（在 `web/` 目录）：

```powershell
npm run test -- --run
npm exec -- tsc --noEmit
npm run build
```

Tauri（在 `platform/tauri/src-tauri/` 目录）：

```powershell
cargo fmt --check
cargo check --locked
cargo clippy --locked -- -D warnings
cargo test --locked
```

生产 release 由项目根目录的 `scripts/build-desktop.ps1` 生成 PyInstaller sidecar 和 NSIS 安装包，并输出两者的 SHA-256。安装包构建通过只能证明打包输入和编译链有效，不能替代登录自启、通知点击、托盘退出、睡眠恢复和干净机器安装/卸载 smoke。

这些命令覆盖 mock/fake 邮件客户端、SQLite 状态迁移、原子发送 claim、CLI/Web 共享发送路径和前端交互。自动化测试不会登录真实 QQ 邮箱，不会调用真实 DeepSeek，也不会执行真实 SMTP 投递；真实服务的账号配置、网络差异和模型输出质量仍需用户明确操作后单独验证。

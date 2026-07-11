# QQ Mail Agent CLI 结构检查报告

更新时间：2026-07-10

本报告用于阶段性检查 `qq-mail-agent-cli` 的代码结构。结论面向学习型 Agent 项目，不按生产邮箱系统的标准无限拔高。

## 结论

当前结构已从“CLI + 手动 Web 工作台”扩展为“Python Agent Core + 共享 React 工作台 + Windows Tauri 常驻壳”。邮箱协议、AI 决策、状态、草稿发送边界、增量同步、IDLE、桌面生命周期和平台入口各自有明确责任。

本轮已经把最关键的重复业务逻辑——草稿版本保存和真实发送状态转换——抽到 `services/draft_service.py`，供参数式 CLI、交互菜单和 Web 复用。SQLite 的原子 claim 也补上了同一草稿并发重复 SMTP 投递的状态边界。

主要残余风险是 Windows 安装/自启/通知点击仍需要隔离环境实机 smoke、真实模型质量缺少脱敏评测，以及 `sending / unknown` 草稿缺少人工核销工作流。现阶段不建议引入 LangGraph 大重构；先积累真实使用反馈和评测样例。

## 模块边界

| 模块 | 当前职责 | 判断 |
| --- | --- | --- |
| `models.py` | 定义邮件、分类、草稿、翻译、发送结果 | 边界清晰，应保持稳定 |
| `config.py` | 源码模式从环境加载配置；安装版环境由 Tauri 安全注入 | 边界清晰，不打印 secret |
| `llm_client.py` | DeepSeek OpenAI-compatible 请求封装 | 职责单一，不应加入邮件业务 |
| `agent.py` | 分类、草稿、翻译的 AI 决策层 | 边界合理，后续可加 prompt 版本和评测 |
| `mail_client.py` | IMAP / SMTP 工具和真实邮箱副作用 | 边界合理，后续只补协议能力 |
| `storage.py` | SQLite 本地状态、队列、草稿、日志 | 边界合理，是 Agent memory/checkpoint 雏形 |
| `services/draft_service.py` | 草稿版本保存、SQLite 原子 claim、CLI/Web 共用发送状态机 | 新增共享业务边界，避免入口漂移 |
| `services/mail_sync_service.py` | UID 增量同步、洞察、草稿预生成、outbox 与启动摘要 | 桌面 Agent 的核心无副作用编排 |
| `services/imap_idle_watcher.py` | IDLE 唤醒、续租、断线重连、低频降级 | 只负责唤醒，数据正确性仍由游标保证 |
| `desktop_worker.py` | loopback API、启动同步、IDLE、父进程回收、stdout 事件 | sidecar 入口清晰，不拥有 UI 生命周期 |
| `health.py` | 本地配置和外部连通性检查 | 边界清晰，适合作为运维入口 |
| `interactive.py` | CLI 菜单、工作流编排、人工确认 | 当前偏重，后续需要拆分 |
| `main.py` | 参数式命令入口，从 SQLite 读取指定草稿并调用 DraftService | 可保留为脚本化入口 |
| `web_server.py` / `web_schemas.py` | 本机 HTTP API 和稳定响应协议 | 复用核心模块，没有复制邮件 Agent 逻辑 |
| `web/src/App.tsx` | Web 工作台状态与流程编排 | 功能完整但仍偏集中，需靠交互测试保护 |
| `web/src/components/` / `web/src/hooks/` | 草稿、弹窗、通用 UI 和并发操作控制 | 已开始按职责拆分，方向合理 |
| `platform/tauri/src-tauri` | 托盘、自启、单实例、凭据、通知点击、sidecar supervision | Rust 只做桌面系统能力，不复制邮件业务 |
| `packaging/` / `scripts/build-*.ps1` | PyInstaller sidecar 和 Tauri/NSIS 可复现构建 | 产物与源码、密钥分离 |

## 当前主要风险

### 1. Windows 行为仍需安装态 smoke

自动化和编译可以验证状态机、事件协议和打包输入，但不能完全证明 Windows 登录自启、通知中心点击、托盘生命周期、睡眠恢复和卸载清理。

建议：

- 在没有源码 Python 的隔离 Windows 用户或 VM 安装 NSIS。
- 验证首次配置、手动启动显示、自启隐藏、关闭到托盘和托盘退出。
- 用 fake sidecar 走“启动汇总 -> 点击打开”和“重要邮件 -> 点击定位”，再由用户明确授权真实 IMAP IDLE 验收。
- 安装包和 sidecar 记录 SHA-256；不把一次本机成功夸大为所有 Windows 环境都通过。
- 当前本机构建产物未做 Authenticode 代码签名，分发到其他机器时可能触发 Windows SmartScreen；正式分发前需要签名证书和签名流水线。
- 当前 Python packaging extra 使用版本下限而非完整 lock；脚本会记录 Python/PyInstaller 版本并做 artifact gate，但跨机器的字节级可复现仍需后续增加 constraints/lock。
- 构建脚本为避免误用旧产物会保留隔离 Cargo target，长期多次构建会占用较多磁盘；清理构建证据必须由用户明确确认。

### 2. `interactive.py` 偏胖

它现在包含：

- 菜单展示。
- 用户输入读取。
- 邮件列表分页。
- 单封邮件操作。
- 批量选择解析。
- DeepSeek 调用确认。
- 状态更新。
- 输出格式化。

影响：

- 新功能容易继续堆在同一个文件里。
- 局部修改可能影响多个菜单路径。
- 后续迁移 LangGraph 时，需要先拆出可复用 workflow 函数。

建议：

- 暂时不大改。
- 下一次新增较大能力时，优先抽 `workflow/service`，不要再直接扩大 `interactive.py`。

### 3. 模型质量缺少离线评测

当前有结构化 JSON 解析测试，但没有一组固定邮件样例来评估分类质量、建议动作和草稿质量。

影响：

- prompt 改动后，只能人工观察结果。
- 很难判断分类是否真的变好。

建议：

- 新增脱敏样例集。
- 为 `triage()` 输出建立基本期望。
- 先评分类和建议动作，再评草稿质量。

### 4. `sending / unknown` 缺少人工核销工作流

当前发送状态是：

```text
pending / failed -> sending -> sent / failed / unknown
```

`StateStore.claim_draft_for_send()` 使用 SQLite 原子更新和 `attempt_id`，Web 与 CLI 又统一通过 `DraftService`，因此同一草稿的并发请求不会重复进入 SMTP。SMTP 投递调用抛出异常时会保守进入锁定的 `unknown`，因为异常可能发生在服务器已接收邮件之后；本地完成状态无法确认时同样进入 `unknown`。

残余边界：

- 进程在发送途中退出时可能留下 `sending`。
- `sending / unknown` 当前没有自动超时恢复或人工核销按钮，这是为了默认避免重复投递。
- 当前恢复方式是先人工核对 QQ 邮箱，再重新生成一个草稿版本；版本历史能保留替代关系，但不能判断旧邮件是否已经发出。

建议：后续如增加恢复能力，应提供“核对为已发送 / 核对为未发送并解锁”的显式审计动作，而不是按时间自动把 `sending` 改回 `pending`。

### 5. 真实邮箱副作用仍需保守

当前已经有二次确认和测试覆盖，但 IMAP / SMTP 是真实副作用边界。

需要继续保持：

- 不自动发送。
- 不自动永久删除。
- 移动垃圾箱不 `EXPUNGE`。
- SMTP 成功后即使保存已发送副本失败，也不能自动重发。
- `unknown` 或遗留 `sending` 未人工核对前不能直接解锁重发。
- 所有错误信息避免泄漏授权码和 API Key。

### 6. 本地状态不是邮箱真实状态

`queue_status` 是本地工作流状态，不等于邮件已读、已删除、已回复。

影响：

- 用户可能误解“已处理”等于邮箱已完成动作。

当前处理：

- 文档和菜单里已经强调本地状态含义。
- 队列历史支持把 `done/skipped` 恢复到 `pending/later`。
- Web 打开未读邮件会自动调用 `mark-seen`；成功后，后端将已有本地队列记录同步为 `done`。这是产品约定的联动，但仍不意味着邮件已经回复或归档。

### 7. Web 工作台编排仍集中在 `App.tsx`

Web 已经实现：

- 左侧“最近 / AI 待办 / 搜索”，以及 `pending / later / done / skipped` 四态队列。
- 右侧“操作 / 草稿 / 记录”，以及草稿 `pending / sent / all` 筛选。
- 配置体检、light/dark theme、移动端单面板导航。
- 异步选择序列校验、草稿 dirty guard、操作级互斥和发送时锁定选择。

这些状态仍主要由 `App.tsx` 编排。现有规模可接受，但下一次增加后台同步、snooze 或多账号时，应优先抽专用 hook/service，避免继续扩大单组件状态图。后续 UI 迭代还应继续强化“本地处理状态”和“邮箱服务器状态”的视觉区分。

## 暂不建议重构的部分

这些模块当前先保持稳定：

- `mail_client.py`：真实 IMAP / SMTP 行为已经通过多轮问题修正，暂不为抽象而拆分。
- `storage.py`：当前状态模型已覆盖四态队列、草稿版本和原子发送 claim，先不要提前设计复杂仓储层。
- `services/draft_service.py`：已经是 CLI/Web 共享的最小边界，不再为模式完整性添加接口或工厂。
- `agent.py`：分类、草稿、翻译三类能力清晰，后续加评测前不要拆散。
- `health.py`：配置体检刚独立出来，职责明确。

不建议为了“看起来像架构”提前引入接口、工厂、插件系统或多层继承。这个项目当前更需要稳定行为、测试和清晰文档。

## 后续可拆分方向

当 `interactive.py` 再次明显增长时，推荐按业务稳定性拆：

```text
src/qq_mail_agent_cli/
  workflows/
    triage_workflow.py
    message_workbench.py
  services/
    draft_service.py  # 已实现
    queue_service.py
  ui/
    formatters.py
    prompts.py
```

建议职责：

- `workflows/triage_workflow.py`：分类、过滤未读、跳过已分类、保存结果。
- `workflows/message_workbench.py`：单封邮件处理动作编排。
- `services/draft_service.py`：已承接草稿版本保存、发送和状态更新；后续只在出现新的稳定共用语义时扩展。
- `services/queue_service.py`：队列状态查询、排序、恢复。
- `ui/formatters.py`：邮件、分类、草稿、资源信息的终端展示。
- `ui/prompts.py`：yes/no、limit、选择器、多行输入。

拆分原则：

- 先拆出已经稳定、测试覆盖好的逻辑。
- 拆分后行为必须保持不变。
- 每次拆一小块，配回归测试。
- 不为了 LangGraph 一次性重写整个 CLI。

## 测试覆盖情况

当前 Python 测试覆盖了很多关键路径：

- 参数式 CLI 的 list、triage、draft、translate、send。
- mock agent 分类、草稿、翻译。
- DeepSeek 结构化 JSON 解析。
- 缺少 key / 邮箱配置时的错误提示。
- 配置体检和外部检查确认。
- 真实邮件列表默认不展示摘要。
- 已读邮件不重复询问标记已读。
- HTML 导出和邮件资源统计。
- 移动垃圾箱前置选择和 UID 处理。
- SMTP 发送、线程头、已发送副本失败不重发。
- SQLite 分类、队列、搜索、草稿、迁移。
- AI 建议队列、队列历史、搜索筛选。
- 单封处理面板中的翻译、草稿、标记已读、移动垃圾箱确认。
- 批量生成草稿和单封失败不中断。
- 最近邮件分页。
- 参数式 `send --yes-send` 从 SQLite 读取指定草稿，不再发送硬编码 mock 草稿。
- 草稿 `pending / sending / sent / failed / unknown` 转换和 SQLite 原子 claim。
- Web/CLI 共享 `DraftService` 的成功、失败、冲突和发送结果不确定路径。
- 草稿重生成的唯一版本 ID、`supersedes_id` 和已发送历史保留。
- Web 搜索、四态队列、草稿筛选、配置体检与自动标记已读 API。

Web 侧 Vitest 还覆盖快速切换邮件、五类 Agent 视图、桌面凭据表单不回显 secret、自启开关、打开后自动标记已读、未保存草稿切换保护、保存后发送同一份内容和移动端/弹窗关键交互。Rust 侧测试覆盖 loopback 地址白名单、启动汇总数字 ID 契约、通知内容脱敏、通知等级门禁、启动重要邮件 defer 去重和普通同步摘要静默策略。

2026-07-10 本轮本机验收结果：Python `152 passed`；Vitest `22 passed`，TypeScript 与 Vite production build 通过；Rust `fmt/check/clippy/test --locked` 通过，`7 passed`；Tauri release 与 NSIS 构建通过。最终安装包为 `20,153,316` bytes，SHA-256 `3F08DA87EFE10B532B0C40CE0D9171BE2EEFBCBD224D17E891D80D26C843BF2A`；sidecar 为 `17,517,544` bytes，SHA-256 `302B0742744918B90ADF1948D972DD6B3597B68719AF0A8CD40DB5671EFF5FBE`。NSIS 输入清单明确包含 sidecar，且 NSIS/PyInstaller 清单未发现 `.env`、SQLite、密钥配置文件或项目绝对路径。

验证命令：

```powershell
python -m pytest -p no:cacheprovider
cd web
npm run test -- --run
npm exec -- tsc --noEmit
npm run build
cd ..\platform\tauri\src-tauri
cargo fmt --check
cargo check --locked
cargo clippy --locked -- -D warnings
cargo test --locked
```

这些自动化使用 mock/fake 客户端和临时 SQLite，不会登录真实 QQ 邮箱、调用真实 DeepSeek 或执行真实 SMTP 投递。因此残余风险仍包括 QQ IMAP IDLE 在断网/睡眠后的真实恢复、Windows 登录自启与通知点击、干净机器安装/卸载、未签名安装包的 SmartScreen 提示、真实模型输出质量，以及 `sending / unknown` 的人工核对流程。

## LangGraph 迁移前置条件

在迁移 LangGraph 前，建议先完成三件事：

1. 在现有 `DraftService` 基础上，只把 `interactive.py` 中下一批稳定且多入口复用的业务动作抽成 workflow/service 函数。
2. 建立脱敏样例和分类评测，避免 graph 化后难以判断质量。
3. 明确哪些节点允许真实副作用，哪些节点必须 human interrupt。

迁移时的合理映射：

```text
MailMessage / TriageResult / Draft -> State
MailClient -> tools
MailAgent.triage -> triage node
MailAgent.draft_reply -> draft node
MailAgent.translate_message -> translate node
StateStore -> checkpoint / memory / atomic send claim
interactive.py confirmation -> Human-in-the-loop interrupt
suggested_action -> conditional edge
DraftService -> shared send workflow / idempotency boundary
```

结论：这个项目已经具备迁移 LangGraph 的概念基础，并完成了第一块共享服务拆分；下一步仍应优先做评测沉淀和小规模行为驱动拆分，而不是直接重写成 graph。

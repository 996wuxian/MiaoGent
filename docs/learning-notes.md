# QQ 邮箱 Agent CLI 学习笔记

更新时间：2026-07-07

这个项目的学习目标不是做一个完整邮箱客户端，而是通过一个真实可操作的邮件场景，理解 AI Agent 从“读取外部信息”到“做决策”、再到“调用工具执行动作”的完整链路。

## 一句话理解

`qq-mail-agent-cli` 是一个基于 Python 的 QQ 邮箱 AI Agent CLI：

```text
IMAP 感知邮件
-> DeepSeek 决策分类 / 推荐动作 / 翻译辅助
-> SQLite 记录状态
-> 人工检查和编辑草稿
-> SMTP 执行回复
-> IMAP 保存已发送副本
```

这条链路里，AI 不直接自动发邮件。它先给出分类和草稿，真正的发送、删除、标记已读都需要你在 CLI 里确认。

## 第一阶段只看这些入口

如果你刚开始读代码，不要一上来全看。先按这个顺序看 8 个入口：

1. `docs/architecture.md`
   先看整体链路、模块职责、状态流转和 LangGraph 映射。

2. `src/qq_mail_agent_cli/models.py`
   看它定义了 Agent 流转的数据对象：邮件、附件、分类结果、草稿、翻译结果、发送结果。

3. `src/qq_mail_agent_cli/mail_client.py`
   看 Agent 能调用哪些真实邮箱工具：读取邮件、查看全文、标记已读、移动垃圾箱、SMTP 发送、保存已发送副本。

4. `src/qq_mail_agent_cli/llm_client.py`
   看 DeepSeek 是怎么被调用的，以及模型返回的 JSON 是怎么解析出来的。

5. `src/qq_mail_agent_cli/agent.py`
   看“AI 决策层”怎么把邮件变成分类结果和回复草稿。

6. `src/qq_mail_agent_cli/storage.py`
   看本地 SQLite 如何记录邮件元信息、分类结果、草稿和操作日志。

7. `src/qq_mail_agent_cli/interactive.py`
   看这些能力怎么被串成交互式 CLI 菜单。

8. `src/qq_mail_agent_cli/health.py`
   看真实项目如何检查配置、网络依赖和密钥存在性，同时不泄漏 secret。

## 每个核心文件的作用

### `models.py`

这是项目的数据协议层。

你可以把它理解成 Agent 内部流转的“标准格式”。真实邮件从 IMAP 读出来以后，会被转成 `MailMessage`；DeepSeek 分类后，会变成 `TriageResult`；生成回复后，会变成 `Draft`；翻译英文邮件后，会变成 `MailTranslation`。

重点看：

- `MailClassification`：分类枚举，包含 `ignore`、`notify`、`respond`。
- `SuggestedAction`：建议动作枚举，包含查看全文、翻译、生成草稿、标记已读、移动垃圾箱、无需处理。
- `MailMessage`：邮件对象，包含 id、发件人、主题、正文、是否已读、附件信息、线程头。
- `TriageResult`：分类结果，包含分类、分类理由、建议动作和建议原因。
- `Draft`：回复草稿，包含收件人、主题、正文、关联原邮件和线程信息。
- `MailTranslation`：翻译结果，包含中文主题和中文正文。
- `DraftSendResult`：发送结果，区分 SMTP 是否成功、已发送副本是否保存成功。

学习重点：Agent 项目必须先把外部世界的数据转成稳定结构，否则后面的 LLM、工具、状态存储都会互相耦合。

### `config.py`

这是配置加载层。

它从 `.env` 读取 QQ 邮箱和 DeepSeek 配置，然后组装成配置对象。项目没有把 `.env` 交给文档或日志输出，这是安全边界。

重点看：

- `QQMailConfig`：IMAP、SMTP、邮箱账号配置。
- `DeepSeekConfig`：API 地址、模型、超时。
- `AppConfig`：本地 SQLite 路径。
- `load_config()`：统一读取环境变量。

学习重点：真实 Agent 一定要把密钥、账号、模型配置和业务代码分开。

### `llm_client.py`

这是 DeepSeek 客户端。

项目使用 DeepSeek 的 OpenAI-compatible `/chat/completions` 接口，并用 Python 标准库 `urllib` 发请求。LLM 返回内容后，代码会尝试解析 JSON。

重点看：

- 只封装聊天补全接口，不把业务逻辑写进客户端。
- 超时从配置读取。
- 返回内容解析失败时会抛出明确错误。

学习重点：LLM 客户端应该只是“模型通道”，不要承担邮件业务判断，否则后续换模型或加评测会很难。

### `agent.py`

这是 Agent 的决策层。

它负责三件事：

- `triage()`：判断邮件是忽略、通知还是需要回复。
- `draft_reply()`：为某封邮件生成回复草稿。
- `translate_message()`：把某封邮件翻译成中文。

当前有两种模式：

- mock / 规则模式：不调用 DeepSeek，方便本地测试。
- DeepSeek 模式：把邮件摘要或正文发送给模型，要求模型返回结构化 JSON。

重点看：

- 分类 prompt 怎么要求输出 `classification`、`reason`、`suggested_action` 和 `action_reason`。
- 草稿 prompt 怎么要求输出 `to`、`subject`、`body`。
- 翻译 prompt 怎么要求输出 `subject_zh` 和 `body_zh`。
- 草稿会保留原邮件 `Message-ID` / `References`，用于后续线程回复。

学习重点：Agent 的核心不是“调用大模型”，而是把模型放在一个明确的决策边界里，让输入、输出、失败处理都有结构。

### `mail_client.py`

这是邮箱工具层，也是这个项目最接近真实业务的部分。

它封装了 Agent 可以执行的工具：

- 通过 IMAP 读取最近邮件。
- 通过 IMAP 获取某封邮件全文。
- 使用 `BODY.PEEK[]` 避免列表读取时自动标记已读。
- 手动标记邮件为已读。
- 移动邮件到垃圾箱。
- 解析 HTML、图片、附件。
- 通过 SMTP 发送纯文本回复。
- 通过 IMAP `APPEND` 保存已发送副本。

重点看：

- `list_real_recent()`：读取真实邮件列表。
- `get_real_message()`：读取某封邮件全文。
- `mark_seen()`：同步已读状态到 QQ 邮箱。
- `move_to_trash()`：移动到垃圾箱，不永久删除。
- `send_draft()`：发送草稿。
- `append_sent_copy()`：保存已发送副本。

学习重点：Agent 的“工具”不只是函数名，而是带有副作用的真实操作。越接近真实世界，越需要确认、降级和错误处理。

### `storage.py`

这是状态层。

Agent 不是一次性脚本。它需要知道哪些邮件已经分类过、哪些草稿待发送、哪些草稿已经发送、用户做过哪些操作。

SQLite 保存：

- `mail_items`：邮件元信息。
- `triage_results`：分类结果。
- `drafts`：生成的草稿、编辑后的草稿、发送状态。
- `action_log`：操作记录。

重点看：

- 不保存原始邮件完整正文、HTML、附件或密钥。
- 会保存本应用生成的草稿正文。
- `get_triaged_uids()` 用来跳过已分类邮件，减少重复调用模型。
- 已发送草稿只读，避免重复发送。

学习重点：Agent 要进入工作流，必须有状态；但状态保存要控制边界，不能把敏感内容无脑落库。

### `interactive.py`

这是 CLI 编排层。

用户真正使用的 `wx_email` 菜单基本都在这里。它把上面的能力串起来：

- 浏览真实邮件。
- 调用 DeepSeek 分类。
- 查看全文并标记已读。
- 移动邮件到垃圾箱。
- 查看分类结果。
- 批量生成回复草稿。
- 查看、编辑、发送草稿。
- 翻译英文邮件。
- 查看操作记录。

重点看：

- 主菜单已经收敛为 4 个入口：邮件处理面板、DeepSeek 分类、草稿箱、操作记录。
- 菜单 1 是邮件处理面板，可先按 AI 建议队列处理，也可查看最近邮件；选中一封后集中执行查看、翻译、生成草稿、标记已读、移动垃圾箱和本地队列状态管理。
- 菜单 2 默认只分类未读且本地未分类过的邮件。
- 菜单 2 的分类结果会给出建议动作，但不会自动执行。
- 菜单 3 支持查看待发送、已发送、全部草稿，并在确认后发送。
- 菜单 5 是配置体检，支持本地配置检查，也支持确认后做 IMAP、SMTP 和 DeepSeek 连通检查。
- 真实发送前必须展示完整内容并二次确认。

学习重点：在没有 LangGraph 之前，`interactive.py` 就是当前项目的“手写工作流编排器”。

### `health.py`

这是配置体检层。

它负责检查本地 `.env` / 环境变量是否配置完整，SQLite 状态目录是否可写，并在用户确认后检查 QQ IMAP、QQ SMTP 和 DeepSeek 是否能连通。

重点看：

- 本地配置检查不访问外部网络。
- IMAP 检查只登录退出，不读取邮件。
- SMTP 检查只登录退出，不发送邮件。
- DeepSeek 检查只发送非邮件 `ping`。
- 授权码和 API Key 只显示已配置 / 未配置，不打印真实值。

学习重点：真实 Agent 不只是功能能跑，还要能安全定位配置问题。

### `main.py`

这是参数式 CLI 入口。

它提供 `list`、`triage`、`draft`、`send` 等命令，适合脚本化测试。但你日常学习更建议先用 `wx_email` 交互菜单，因为它更接近真实操作流程。

学习重点：参数式 CLI 适合自动化，交互式 CLI 适合人工参与的 Agent 工作流。

## 当前 Agent 链路

完整链路可以这样理解：

```text
1. 用户在 wx_email 菜单选择邮件处理面板
2. MailClient 通过 IMAP 读取邮件列表
3. 邮件被转成 MailMessage
4. 用户确认后，MailAgent 把邮件交给 DeepSeek 分类并推荐下一步动作
5. 分类结果 TriageResult 写入 SQLite，包含 classification、suggested_action 和 queue_status
6. 用户在邮件处理面板选择“按 AI 建议处理”，从本地建议队列里选中邮件
7. MailAgent 调用 DeepSeek 生成 Draft
8. Draft 写入 SQLite，状态为待发送
9. 用户进入菜单 3 查看草稿
10. 用户可编辑主题和正文
11. 用户确认后，MailClient 通过 SMTP 发送
12. 发送成功后，MailClient 尝试用 IMAP 保存已发送副本
13. StateStore 更新草稿状态和操作日志
```

翻译链路更短：

```text
1. 用户输入邮件 UID
2. MailClient 读取真实邮件全文
3. 用户确认把邮件内容发送给 DeepSeek
4. MailAgent 调用 DeepSeek 翻译
5. CLI 展示中文主题和正文翻译
6. StateStore 只记录 translate 动作，不保存翻译正文
```

邮件处理面板是当前最接近 Agent 工作台的入口：

```text
1. 用户选择按 AI 建议处理、查看最近邮件、查看队列历史或搜索筛选邮件
2. AI 建议处理从 SQLite 读取待处理/稍后处理的分类结果，并按 queue_status 和 suggested_action 排序
3. 查看最近邮件则分页读取 QQ 邮箱邮件
4. 搜索筛选从 SQLite 读取本地邮件元信息、分类和队列状态
5. 用户选择一封邮件进入单封处理面板
6. 用户决定查看、翻译、生成草稿、标记已读、移动垃圾箱或更新本地队列状态
7. 每个高风险动作单独确认
8. 队列历史可回看已处理/已跳过记录，并把误操作改回待处理或稍后处理
9. StateStore 记录邮件元信息、队列状态和操作日志
```

这个流程有三个关键点：

- DeepSeek 负责分类、草稿和翻译，不直接操作邮箱。
- 用户负责确认破坏性动作和真实发送。
- SQLite 负责把多轮操作串起来。

AI 建议队列是把模型判断转成“人类待办列表”的一步：

```text
triage_results.suggested_action
triage_results.queue_status
-> 按处理状态和动作优先级排序
-> 用户选中一封
-> 进入 human review 单封处理面板
-> 完成、跳过或稍后处理
-> 从队列历史中回看或恢复状态
```

它不会自动执行建议动作，只是把“下一步可能该做什么”排在更顺手的位置。

`queue_status` 是这个项目里的 workflow state：

- `pending`：待处理，默认进入建议队列。
- `later`：稍后处理，仍进入建议队列，但排在待处理之后。
- `done`：已处理，默认不再进入建议队列。
- `skipped`：已跳过，默认不再进入建议队列。

生成草稿、标记已读、移动垃圾箱成功后会自动把 `queue_status` 改为 `done`。查看全文和翻译不会自动完成，因为这两个动作更像理解邮件内容，不一定代表事情已经处理完。

队列历史让这个状态闭环可逆：

```text
done / skipped
-> 默认不进入待处理队列
-> 可在队列历史中查看
-> 可改回 pending 或 later
```

这个恢复只修改本地 workflow state，不会恢复 QQ 邮箱里的邮件位置、已读状态或发送状态。

配置体检是可运维性入口：

```text
.env / 环境变量
-> 本地配置存在性检查
-> SQLite 可写检查
-> 告诉用户是否需要补配置
-> 用户确认后检查外部依赖连通性
```

本地配置检查不访问外部网络。IMAP、SMTP、DeepSeek 连通检查需要用户单独确认：IMAP 只登录退出，不读取邮件；SMTP 只登录退出，不发送邮件；DeepSeek 只发送非邮件 `ping` 测试。这样能定位配置、网络、授权码或 API Key 问题，同时不触碰真实邮件内容。

搜索 / 筛选入口是本地索引层：

```text
mail_items.sender / subject / is_seen
triage_results.classification / queue_status
-> 本地 SQLite 查询
-> 用户选中 UID
-> MailClient.get_real_message(uid)
-> 进入单封处理面板
```

它不是 QQ 邮箱全量搜索，也不搜索邮件正文。它只对程序已经读取或分类过的邮件元信息生效，目的是让 CLI 工作台更容易定位邮件，同时避免为了搜索正文而保存敏感内容。

## 为什么它已经是一个 Agent

它符合一个基础 Agent 的核心结构：

| Agent 组成 | 本项目对应实现 |
| --- | --- |
| 感知输入 | `MailClient.list_real_recent()` / `get_real_message()` 从 QQ 邮箱读取邮件 |
| 决策 | `MailAgent.triage()` 调用 DeepSeek 判断邮件类型 |
| 下一步建议 | `TriageResult.suggested_action` 表示建议查看、翻译、生成草稿等 |
| 生成 | `MailAgent.draft_reply()` 生成回复草稿 |
| 翻译辅助 | `MailAgent.translate_message()` 将英文邮件转成中文 |
| 工具 | IMAP、SMTP、SQLite、DeepSeek |
| 状态 | `StateStore` 保存邮件元信息、分类、建议队列状态、草稿、发送记录 |
| 可运维性 | 配置体检检查本地环境、密钥存在性和 SQLite 可写性 |
| 人工审批 | `interactive.py` 发送前、删除前、发给 DeepSeek 前都要求确认 |
| 行动执行 | 标记已读、移动垃圾箱、SMTP 回复、保存已发送 |

但它还不是 LangGraph Agent，因为当前的工作流是手写在 CLI 菜单里的，还没有显式的 graph state、node、edge、router 和 checkpoint。

## 和 LangGraph 的对应关系

后续升级 LangGraph 时，可以这样映射：

| 当前实现 | LangGraph 中的概念 |
| --- | --- |
| `MailMessage` / `TriageResult` / `Draft` / `MailTranslation` | State 字段 |
| `MailClient.list_real_recent()` | fetch mails node / tool |
| `MailAgent.triage()` | triage node |
| `MailAgent.draft_reply()` | draft node |
| `MailAgent.translate_message()` | translate node |
| `StateStore` | checkpoint / memory / persistence |
| `interactive.py` 邮件处理面板 | human review node |
| `interactive.py` 人工确认 | human-in-the-loop interrupt |
| `send_draft()` | send tool |
| `classification == respond` | conditional edge |

一个未来的 LangGraph 版本可以长这样：

```text
fetch_mails
-> filter_unread_and_untriaged
-> triage
-> route_by_classification
   -> ignore: save_result
   -> notify: save_result
   -> respond: draft_reply
-> human_review
-> send_or_skip
-> save_sent_copy
-> log_result
```

## 当前安全设计

这个项目最重要的安全边界是：

- 默认不自动发送邮件。
- 默认不自动删除邮件。
- 移动垃圾箱前必须确认。
- 真实发送前必须展示完整 `To` / `Subject` / `Body` 并确认。
- 发送成功但保存已发送副本失败时，不重复发送。
- 真实邮件内容发送给 DeepSeek 前必须确认。
- 建议动作不会自动执行；它只是给邮件处理面板提供参考。
- 翻译真实邮件前必须确认，翻译结果只在终端展示，不默认保存到 SQLite。
- 邮件处理面板不会降低安全等级；它只是减少 UID 复制和菜单跳转。
- 菜单 2 默认只分类未读且本地未分类过的邮件，减少重复模型调用。
- `list --real` 默认不展示正文摘要，只有 `--snippet` 才展示。
- SQLite 不保存原始邮件完整正文、HTML、附件或密钥。
- `.env` 不应该提交，也不应该写入文档。

## 当前限制

这个项目是学习型 Agent，不是生产邮箱系统。当前限制包括：

- 只支持纯文本回复，不支持 HTML 回复。
- 不支持附件回复。
- 不支持 CC / BCC。
- 不支持自动重试和失败队列。
- 不支持 prompt 版本管理。
- 没有离线评测集，分类质量主要靠人工观察。
- 没有 LangGraph 的显式状态机和中断恢复。
- 没有多账号管理。
- 没有权限系统。
- 没有 Web / 桌面 UI。

这些不是当前阶段的问题。第一阶段的重点是把 Agent 的核心闭环跑通。

## 你应该怎么学习

建议按 5 个阶段学：

### 第一阶段：先建立全局地图

只看：

- `docs/architecture.md`
- `docs/structure-review.md`

目标：先知道这个项目的 Agent 链路、模块边界、当前风险和后续 LangGraph 映射。

### 第二阶段：读懂数据和工具

只看：

- `models.py`
- `mail_client.py`
- `llm_client.py`

目标：能说清楚“邮件进来以后，被转成什么对象，真实邮箱工具能做什么，DeepSeek 是怎么被调用的”。

### 第三阶段：读懂 AI 决策和状态

再看：

- `agent.py`
- `storage.py`

目标：能说清楚“AI 怎么分类和生成草稿、为什么需要 SQLite、为什么需要本地队列状态和草稿状态”。

### 第四阶段：读懂工作台和安全边界

再看：

- `interactive.py`
- `health.py`
- `tests/test_cli.py`

目标：能说清楚“人工确认在哪里、真实发送和删除为什么不能自动执行、配置体检如何避免泄漏密钥、测试保护了哪些关键路径”。

### 第五阶段：跑通关键菜单并准备 LangGraph

只跑这些菜单：

- 菜单 2：DeepSeek 分类最近邮件。
- 菜单 1：邮件处理面板。
- 菜单 3：草稿箱 / 编辑 / 发送。
- 菜单 4：操作记录。
- 菜单 5：配置体检。

然后把当前手写流程画成图：

```text
读取 -> 过滤 -> 分类 -> 路由 -> 生成草稿 -> 人工确认 -> 发送 -> 记录
```

目标：能从用户视角讲完整闭环，并解释“我现在为什么还没用 LangGraph，以及下一步怎么迁移”。

## 面试时怎么讲这个项目

可以这样讲：

> 我做了一个 QQ 邮箱 AI Agent CLI，用 Python 接入 QQ 邮箱 IMAP/SMTP 和 DeepSeek。它可以读取真实邮件，默认筛选未读且本地未分类邮件，调用模型做 ignore/notify/respond 分类，并把结果保存到 SQLite。对于需要回复的邮件，它支持批量生成草稿，用户可以在 CLI 里编辑和确认，最后通过 SMTP 发送，并用 IMAP 尝试同步到已发送。整个链路保留了 human-in-the-loop，真实发送、删除和发送邮件内容给模型都需要二次确认。

注意不要说它已经是生产级邮箱系统，也不要说它全自动处理邮箱。更准确的说法是：这是一个可运行的 AI Agent 学习项目，已经跑通真实邮箱工具调用和人工审批闭环。

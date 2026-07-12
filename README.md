# MiaoGent

<p align="center">
  <img src="platform/tauri/web/src/assets/miaogent-logo.png" width="112" alt="MiaoGent logo" />
</p>

<p align="center">
  <strong>本地优先的 QQ 邮箱 AI Agent 桌面应用 / Local-first QQ Mail AI Agent desktop app.</strong>
</p>

<p align="center">
  <a href="#中文">中文</a> ·
  <a href="#english">English</a> ·
  <a href="#license">License</a>
</p>

## 中文

MiaoGent 是一个本地优先、安全优先的 QQ 邮箱 AI Agent。它可以在 Windows 桌面端常驻托盘，通过 IMAP 同步邮件，用 AI 判断重要程度、识别待回复邮件、生成回复草稿，并把需要你处理的内容集中到工作台里。

核心边界很明确：MiaoGent 可以帮你阅读、分类、总结和起草，但不会在没有你明确确认的情况下发送邮件、删除邮件或永久清理邮箱内容。

### 功能

- Windows 桌面应用，基于 Tauri。
- 托盘常驻，关闭窗口默认缩到系统托盘。
- 登录自启后后台静默整理邮件。
- IMAP IDLE 监听新邮件。
- AI 分类：一般、重要、紧急、待回复。
- 对需要回复的邮件生成本地草稿。
- 发送前必须人工确认。
- React 工作台：邮件列表、阅读区、AI 建议、草稿、操作记录。
- 原生通知：只对重要/紧急等需要关注的内容提醒。
- 应用内检查更新，基于 GitHub Release 签名产物。
- SQLite 本地状态：邮件元信息、AI 洞察、草稿、队列状态和操作日志。
- 本地 sidecar 后端只绑定 `127.0.0.1`。

### 不会做什么

- 不会自动发送回复。
- 不会永久删除邮件。
- 不会暴露公网服务。
- 不会把密钥写入仓库。
- 不会把整个邮箱上传到第三方服务器。

### 安全边界

| 范围 | 行为 |
| --- | --- |
| 邮箱访问 | 使用你自己的 QQ 邮箱配置，通过 IMAP/SMTP 访问。 |
| AI 使用 | 只有分类、翻译、摘要或生成草稿需要时，才把相关邮件内容发送给配置的模型。 |
| 发送邮件 | 永远不自动发送；必须打开草稿、核对并确认。 |
| 删除邮件 | 移动到垃圾箱需要确认；未实现永久删除。 |
| 密钥 | `.env` 被忽略；桌面端密钥保存到 Windows 凭据管理器。 |
| 本地服务 | sidecar 只监听 `127.0.0.1`，并使用运行期 Bearer token。 |
| 本地数据 | SQLite、日志、导出 HTML、构建产物都不应提交到 Git。 |

### 架构

```text
QQ Mail IMAP/SMTP
        │
        ▼
 Python Core ── SQLite local state
        │
        └── Tauri Desktop App
                  │
                  ├── Tray / autostart
                  ├── Native notifications
                  ├── FastAPI loopback sidecar
                  └── React workbench
```

### 快速开始

```powershell
git clone git@github.com:996wuxian/MiaoGent.git
cd MiaoGent
Copy-Item .env.example .env
```

填写你自己的配置：

```env
QQ_MAIL_ADDRESS=
QQ_MAIL_AUTH_CODE=
DEEPSEEK_API_KEY=
```

QQ 邮箱需要使用客户端授权码，不是登录密码。

安装开发依赖：

```powershell
python -m pip install -e ".[desktop,packaging,dev]"
cd platform\tauri\web
npm install
cd ..
npm install
```

### 桌面端开发

```powershell
python -m pip install -e ".[desktop,packaging,dev]"
cd platform\tauri
npm install
npm run dev
```

构建 Windows 安装包：

```powershell
.\scripts\build-desktop.ps1
```

注意：

- 默认没有 Authenticode 代码签名，Windows 可能提示安全警告。
- Updater 产物需要 `TAURI_SIGNING_PRIVATE_KEY`。
- 公共 Release 使用 GitHub Actions secret，不能提交私钥。
- 构建产物、sidecar exe、`.env` 和本地数据库都被 Git 忽略。

### 常用验证命令

Python：

```powershell
python -m pytest -q
```

前端：

```powershell
cd platform\tauri\web
npm run test -- --run
npm exec -- tsc --noEmit
npm run build
```

Tauri / Rust：

```powershell
cd platform\tauri\src-tauri
cargo fmt --check
cargo check --locked
cargo test --locked
```

### 数据与隐私

发布或 fork 前，请确认没有提交这些本地数据：

- `.env`
- `.mail_agent_state/`
- `.mail_exports/`
- `logs/`
- `*.sqlite`
- `*.db`
- `build/`
- `platform/tauri/web/dist/`
- `platform/tauri/src-tauri/target/`
- `platform/tauri/src-tauri/binaries/*.exe`

### 文档

- [架构说明](docs/architecture.md)
- [结构评审](docs/structure-review.md)
- [学习笔记](docs/learning-notes.md)
- [平台说明](platform/README.md)

## English

MiaoGent is a local-first, safety-first QQ Mail AI Agent desktop app. It runs quietly in the Windows tray, syncs mail through IMAP, classifies messages with an LLM, highlights important and urgent mail, prepares reply drafts, and gives you a focused workbench for handling what matters.

The main rule is simple: MiaoGent can help you read, classify, summarize and draft, but it will not send or delete mail without explicit user confirmation.

### Features

- Windows desktop app powered by Tauri.
- Tray resident agent with close-to-tray behavior.
- Silent background mail sync after Windows login.
- IMAP IDLE watcher for new mail.
- AI labels: general, important, urgent and needs-reply.
- Local draft generation for messages that need a response.
- Human-in-the-loop sending.
- React workbench for mail list, reader, AI suggestions, drafts and activity logs.
- Native notifications for important or urgent items.
- Manual in-app update checks using signed GitHub Release artifacts.
- SQLite local state for metadata, insights, drafts, queues and logs.
- Local-only sidecar backend bound to `127.0.0.1`.

### What it does not do

- It does not auto-send replies.
- It does not permanently delete mail.
- It does not expose a public web service.
- It does not store secrets in the repository.
- It does not upload your full mailbox to a hosted service.

### Safety model

| Area | Behavior |
| --- | --- |
| Mail access | Uses your own QQ Mail configuration through IMAP/SMTP. |
| LLM usage | Sends relevant mail content to the configured model only when classification, translation, summarization or drafting needs it. |
| Sending | Never sends automatically; drafts must be reviewed and confirmed. |
| Deletion | Move-to-trash requires confirmation; permanent deletion is not implemented. |
| Secrets | `.env` is ignored; desktop secrets are stored in Windows Credential Manager. |
| Local server | The sidecar listens on `127.0.0.1` and uses a runtime Bearer token. |
| Local data | SQLite state, logs, exported HTML and build artifacts should not be committed. |

### Quick start

```powershell
git clone git@github.com:996wuxian/MiaoGent.git
cd MiaoGent
Copy-Item .env.example .env
```

Fill in your own values:

```env
QQ_MAIL_ADDRESS=
QQ_MAIL_AUTH_CODE=
DEEPSEEK_API_KEY=
```

QQ Mail requires a client authorization code instead of your login password.

Install dependencies:

```powershell
python -m pip install -e ".[desktop,packaging,dev]"
cd platform\tauri\web
npm install
cd ..
npm install
```

### Desktop development

```powershell
python -m pip install -e ".[desktop,packaging,dev]"
cd platform\tauri
npm install
npm run dev
```

Build a Windows installer:

```powershell
.\scripts\build-desktop.ps1
```

Notes:

- The installer is not Authenticode-signed by default.
- Windows may show a warning for unsigned builds.
- Updater artifacts require `TAURI_SIGNING_PRIVATE_KEY`.
- Public releases use a GitHub Actions secret. Do not commit the private key.
- Build outputs, the generated sidecar executable, `.env` and local databases are ignored by Git.

### Development commands

```powershell
python -m pytest -q
```

```powershell
cd platform\tauri\web
npm run test -- --run
npm exec -- tsc --noEmit
npm run build
```

```powershell
cd platform\tauri\src-tauri
cargo fmt --check
cargo check --locked
cargo test --locked
```

### Privacy

Before publishing your fork, make sure local data and secrets are not staged:

- `.env`
- `.mail_agent_state/`
- `.mail_exports/`
- `logs/`
- `*.sqlite`
- `*.db`
- `build/`
- `platform/tauri/web/dist/`
- `platform/tauri/src-tauri/target/`
- `platform/tauri/src-tauri/binaries/*.exe`

## License

MiaoGent is released under the [MIT License](LICENSE).

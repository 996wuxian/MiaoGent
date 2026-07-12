# MiaoGent

<p align="center">
  <img src="platform/tauri/web/src/assets/miaogent-logo.png" width="112" alt="MiaoGent logo" />
</p>

<p align="center">
  <strong>Local-first QQ Mail AI Agent desktop app for Windows.</strong>
</p>

<p align="center">
  <a href="#features">Features</a> ·
  <a href="#safety-model">Safety</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#desktop-app">Desktop App</a> ·
  <a href="#license">License</a>
</p>

MiaoGent is a local-first, safety-first QQ Mail assistant. It can read your mailbox through IMAP, classify new mail with an LLM, highlight important and urgent messages, prepare reply drafts, and keep a Windows desktop tray app running quietly in the background.

The core rule is simple: **MiaoGent can help you read, classify and draft, but it will not send or delete mail without explicit user action.**

## Features

- **Windows desktop app** powered by Tauri.
- **Tray resident agent** with close-to-tray behavior.
- **Startup summary** for newly synced mail.
- **IMAP IDLE watcher** for new-mail wakeups.
- **AI priority labels**: general, important, urgent and needs-reply.
- **Draft generation** for emails that need a response.
- **Human-in-the-loop sending**: drafts must be reviewed and confirmed manually.
- **Bundled React workbench** with mail list, reader, actions, drafts and activity log.
- **Manual in-app update check** through signed GitHub Release artifacts.
- **SQLite local state** for metadata, insights, drafts and operation logs.
- **Local-only backend** bound to `127.0.0.1`.

## What it does not do

- It does not auto-send replies.
- It does not permanently delete mail.
- It does not expose a public web service.
- It does not store real secrets in the repository.
- It does not upload your full mailbox to a server.

## Safety model

MiaoGent is designed around explicit boundaries:

| Area | Behavior |
| --- | --- |
| Mail access | Reads QQ Mail through IMAP/SMTP using your own account configuration. |
| LLM usage | Sends selected mail content to the configured LLM only when a feature requires classification, translation or drafting. |
| Sending | Never sends automatically. The final draft must be opened, reviewed and confirmed. |
| Deletion | Move-to-trash requires explicit confirmation; permanent deletion is not implemented. |
| Secrets | `.env` is ignored. Desktop secrets are stored through Windows Credential Manager. |
| Local server | The sidecar backend binds to `127.0.0.1` and uses a runtime Bearer token. |
| Local data | SQLite state and exported mail HTML are ignored and should not be committed. |

## Architecture

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

## Project structure

```text
.
├── src/qq_mail_agent_cli/      # Python core, mail client, storage, API and desktop worker
├── platform/
│   └── tauri/                  # Windows desktop app and bundled React renderer
├── scripts/                    # Desktop/sidecar build scripts
├── tests/                      # Python regression tests
├── docs/                       # Architecture and learning notes
└── .env.example                # Local development configuration template
```

## Quick start

### 1. Clone

```powershell
git clone git@github.com:996wuxian/MiaoGent.git
cd MiaoGent
```

### 2. Create local config

```powershell
Copy-Item .env.example .env
```

Fill in your own values:

```env
QQ_MAIL_ADDRESS=
QQ_MAIL_AUTH_CODE=
DEEPSEEK_API_KEY=
```

QQ Mail requires a client authorization code instead of your login password.

### 3. Install development dependencies

```powershell
python -m pip install -e ".[desktop,packaging,dev]"
cd platform\tauri\web
npm install
cd ..
npm install
```

## Desktop app

For Windows desktop development:

```powershell
python -m pip install -e ".[desktop,packaging,dev]"
cd platform\tauri
npm install
npm run dev
```

To build a Windows installer:

```powershell
.\scripts\build-desktop.ps1
```

Notes:

- The installer is not code-signed by default.
- Windows may show a security warning for unsigned builds.
- Updater artifacts require `TAURI_SIGNING_PRIVATE_KEY`. Public releases use a GitHub Actions secret; do not commit the private key.
- Build outputs are ignored by Git.
- The generated Python sidecar executable is not committed.

## Development commands

Python tests:

```powershell
python -m pytest -q
```

Renderer tests and build:

```powershell
cd platform\tauri\web
npm run test -- --run
npm exec -- tsc --noEmit
npm run build
```

Tauri checks:

```powershell
cd platform\tauri\src-tauri
cargo fmt --check
cargo check --locked
cargo test --locked
```

## Configuration

`.env.example` contains only empty placeholders and safe defaults.

Important variables:

| Variable | Description |
| --- | --- |
| `QQ_MAIL_ADDRESS` | Your QQ Mail address. |
| `QQ_MAIL_AUTH_CODE` | QQ Mail client authorization code. Do not commit it. |
| `QQ_MAIL_IMAP_HOST` | Defaults to `imap.qq.com`. |
| `QQ_MAIL_IMAP_PORT` | Defaults to `993`. |
| `QQ_MAIL_SMTP_HOST` | Defaults to `smtp.qq.com`. |
| `QQ_MAIL_SMTP_PORT` | Defaults to `465`. |
| `DEEPSEEK_API_KEY` | Your LLM API key. Do not commit it. |
| `DEEPSEEK_BASE_URL` | Defaults to `https://api.deepseek.com`. |
| `DEEPSEEK_MODEL` | Defaults to `deepseek-chat`. |

## Data and privacy

Ignored local paths include:

- `.env`
- `.mail_agent_state/`
- `.mail_exports/`
- `logs/`
- `*.sqlite`
- `*.db`
- `build/`
- `web/`
- `platform/tauri/web/dist/`
- `platform/tauri/src-tauri/target/`
- `platform/tauri/src-tauri/binaries/*.exe`

Before publishing your fork, check that none of these files are staged.

## Documentation

- [Architecture](docs/architecture.md)
- [Structure review](docs/structure-review.md)
- [Learning notes](docs/learning-notes.md)
- [Platform notes](platform/README.md)

## Roadmap ideas

- Better onboarding and configuration diagnostics.
- More robust IMAP IDLE recovery after sleep/network changes.
- Rich-text draft editing.
- Attachment awareness.
- Evaluation harness for classification and draft quality.
- Authenticode signing for Windows installers.
- macOS/Linux desktop packaging.

## License

MiaoGent is released under the [MIT License](LICENSE).

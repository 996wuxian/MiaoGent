# Windows Tauri platform

This directory contains the Windows desktop distribution. It bundles the React
renderer from `web/` and the Python mail-agent core from `../../src`.

## Runtime lifecycle

```text
Windows login --autostart
-> hidden Tauri window + tray
-> Python sidecar on dynamic 127.0.0.1 port
-> startup UID catch-up and draft preparation
-> one startup-summary toast
-> IMAP IDLE background wait
-> important/urgent toast only
-> close window hides; tray Exit stops both processes
```

The Rust shell owns autostart, tray, single-instance behavior, sidecar
supervision, Windows Credential Manager access and native toast click routing.
The sidecar owns IMAP, AI analysis, SQLite state and the loopback FastAPI API.
The WebView only receives a per-process API token in memory.

## GitHub release runtime model

The desktop release is a self-contained NSIS installer. A user downloading
MiaoGent from GitHub does not need to install Python, run `uvicorn`, or deploy a
public backend.

The installer bundles:

- the Tauri desktop executable;
- the React frontend assets;
- the PyInstaller sidecar `qq-mail-agent-worker.exe`.
- signed updater metadata for application-driven upgrades after the first
  updater-capable install.

At runtime the Tauri process starts the sidecar automatically. The sidecar
starts FastAPI on a random `127.0.0.1` port and receives a random session token
through the process environment. The WebView obtains the current loopback URL
and token from Tauri only for the current process. The API is not exposed to the
LAN or the public internet.

User secrets must remain outside the release artifact:

- QQ mail authorization code and DeepSeek API key are stored in Windows
  Credential Manager.
- `.env`, SQLite state, logs, WebView cache and mail exports are not packaged.

## In-app updates

MiaoGent uses the official Tauri updater with signed GitHub Release artifacts.
The app checks:

```text
https://github.com/996wuxian/MiaoGent/releases/latest/download/latest.json
```

Release assets for Windows should include:

- `MiaoGent_<version>_x64-setup.exe`;
- `MiaoGent_<version>_x64-setup.exe.sig`;
- `latest.json`;
- `SHA256SUMS.txt`;
- `build-metadata.json`.

The updater signing public key is stored in `src-tauri/tauri.conf.json`. The
private key must be kept outside the repository and provided through
`TAURI_SIGNING_PRIVATE_KEY` in GitHub Actions or a local environment variable.

`v0.1.13` is the first updater-capable release. Earlier versions cannot update
themselves in-app and must be manually upgraded once.

## Local storage

Default desktop storage follows Windows per-user app directories:

- minimal desktop configuration:
  `%APPDATA%\com.wuxian.qqmailagent\desktop-config.json`;
- business state by default:
  `%APPDATA%\com.wuxian.qqmailagent\state.sqlite3`;
- WebView/cache/log data by default:
  `%LOCALAPPDATA%\com.wuxian.qqmailagent`.

The settings UI can move the business state to a user-selected root. MiaoGent
creates a controlled child directory and uses that as the sidecar `--data-dir`:

```text
<selected root>\MiaoGent\data
```

The WebView data directory can also be set to a controlled child directory and
takes effect after restarting MiaoGent:

```text
<selected root>\MiaoGent\webview
```

The minimal desktop config remains in `%APPDATA%` so the app can find the
custom storage locations during startup. Credentials remain in Windows
Credential Manager and are not moved to user-selected folders.

## Commands

```powershell
# Development: uses Python source directly and does not require a sidecar exe
npm run dev

# Production: calls ../../scripts/build-desktop.ps1
npm run build
```

Production uses `src-tauri/tauri.bundle.conf.json` to add the generated
`qq-mail-agent-worker-<target-triple>.exe` as `externalBin`. Keeping this in a
build-only config allows ordinary `cargo check/test/clippy` to run before the
PyInstaller artifact exists.

Do not place `.env`, database files, logs, mail exports or credentials in this
directory. Generated binaries are ignored by Git.

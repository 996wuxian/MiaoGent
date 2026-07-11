# Platform entry

MiaoGent now ships as a Tauri desktop app.

- `tauri/`: Windows desktop shell, tray lifecycle, autostart, notifications,
  bundled React renderer and Python sidecar packaging.

Shared product logic remains in `src/qq_mail_agent_cli/`. The React renderer is
kept under `platform/tauri/web/` because it is no longer distributed as a
standalone browser platform.

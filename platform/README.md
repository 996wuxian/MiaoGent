# Platform entries

This directory keeps platform-specific launch and packaging code separate while
reusing the same product core:

- `pc/`: browser-based local workbench entry for the existing `web/` app.
- `cli/`: terminal entry for the existing Python CLI.
- `tauri/`: Windows desktop shell, tray lifecycle, autostart and notifications.

Shared code remains in `web/` and `src/qq_mail_agent_cli/`. Platform adapters
must not copy mail, AI, draft or storage business logic.

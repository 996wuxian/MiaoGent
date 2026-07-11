# Desktop sidecar binaries

This directory only contains generated PyInstaller sidecars. Run
`scripts/build-sidecar.ps1` from the repository root to create the target-triple
binary required by `tauri.bundle.conf.json`.

Generated `.exe` files are intentionally ignored by Git. They are inputs to the
local Tauri/NSIS build, not source files, and must never contain `.env` or account
credentials.

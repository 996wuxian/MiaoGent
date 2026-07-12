# AGENTS.md

## Release workflow rule

- When a requested change needs a GitHub Release, finish local verification, commit, push `main`, create and push the version tag, then stop after confirming that GitHub Actions has been triggered.
- Do not wait for the Release workflow to finish, do not poll until assets appear, and do not spend extra tokens watching GitHub Actions unless wuxian explicitly asks for release completion verification.
- Final handoff should include the commit, tag, workflow trigger status if cheaply available, and the Release URL pattern.

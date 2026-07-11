$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$env:PYTHONPATH = Join-Path $root "src"

Push-Location $root
try {
    python -m qq_mail_agent_cli
}
finally {
    Pop-Location
}

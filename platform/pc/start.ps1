$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$web = Join-Path $root "web"
$env:PYTHONPATH = Join-Path $root "src"

$backend = Start-Process `
    -FilePath "python" `
    -ArgumentList @("-m", "qq_mail_agent_cli.web_server") `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru

try {
    npm --prefix $web run dev
}
finally {
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id
    }
}

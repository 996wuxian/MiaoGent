param(
    [string]$PythonExecutable = "python",
    [string]$TargetTriple = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$spec = Join-Path $root "packaging\qq_mail_agent_sidecar.spec"

$hostLine = rustc -vV | Where-Object { $_ -like "host:*" } | Select-Object -First 1
if (-not $hostLine) {
    throw "Unable to determine the Rust host target triple."
}
$hostTriple = ($hostLine -replace "^host:\s*", "").Trim()
if (-not $TargetTriple) {
    $TargetTriple = $hostTriple
}
if ($TargetTriple -notmatch "windows") {
    throw "The first desktop release only supports a Windows target triple."
}
if ($TargetTriple -ne $hostTriple) {
    throw "Cross-compiling the Python sidecar is not supported. Requested $TargetTriple, host is $hostTriple."
}

$buildId = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$distDir = Join-Path $root "build\sidecar-dist\$buildId"
$workDir = Join-Path $root "build\sidecar-work\$buildId"
$binaryDir = Join-Path $root "platform\tauri\src-tauri\binaries"
$destination = Join-Path $binaryDir "miaogent-worker-$TargetTriple.exe"

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null

& $PythonExecutable -m PyInstaller --noconfirm --distpath $distDir --workpath $workDir $spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller sidecar build failed with exit code $LASTEXITCODE."
}

$built = Join-Path $distDir "miaogent-worker.exe"
if (-not (Test-Path -LiteralPath $built)) {
    throw "PyInstaller did not produce $built."
}
Copy-Item -LiteralPath $built -Destination $destination -Force
$helpText = (& $destination --help 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $helpText -notmatch "--data-dir") {
    throw "Built sidecar failed its --help smoke check."
}
$artifact = Get-Item -LiteralPath $destination
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $destination
$pythonVersion = (& $PythonExecutable --version 2>&1 | Out-String).Trim()
$pyInstallerVersion = (& $PythonExecutable -m PyInstaller --version 2>&1 | Out-String).Trim()

[pscustomobject]@{
    Path = $artifact.FullName
    Bytes = $artifact.Length
    SHA256 = $hash.Hash
    TargetTriple = $TargetTriple
    Python = $pythonVersion
    PyInstaller = $pyInstallerVersion
    Smoke = "--help passed"
}

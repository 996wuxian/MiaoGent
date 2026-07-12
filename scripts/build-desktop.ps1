param(
    [string]$PythonExecutable = "python",
    [string]$TargetTriple = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$sidecarScript = Join-Path $PSScriptRoot "build-sidecar.ps1"
$tauriCli = Join-Path $root "platform\tauri\node_modules\.bin\tauri.cmd"
$tauriConfig = Join-Path $root "platform\tauri\src-tauri\tauri.conf.json"
$bundleConfig = Join-Path $root "platform\tauri\src-tauri\tauri.bundle.conf.json"

if (-not (Test-Path -LiteralPath $tauriCli)) {
    throw "Tauri dependencies are missing. Run npm install in platform/tauri first."
}
if (-not (Test-Path -LiteralPath $bundleConfig)) {
    throw "Tauri bundle override is missing: $bundleConfig"
}

$tauriConfigJson = Get-Content -Raw -LiteralPath $tauriConfig | ConvertFrom-Json
$mainWindow = $tauriConfigJson.app.windows | Select-Object -First 1
if ($mainWindow) {
    if ($mainWindow.url -ne "index.html") {
        throw "Tauri main window must load index.html, got '$($mainWindow.url)'."
    }
}
else {
    $libRs = Join-Path $root "platform\tauri\src-tauri\src\lib.rs"
    if (-not (Select-String -LiteralPath $libRs -SimpleMatch 'WebviewUrl::App("index.html".into())' -Quiet)) {
        throw "Tauri main window is created dynamically, but lib.rs does not load index.html."
    }
}
$frontendDist = $tauriConfigJson.build.frontendDist
if ([System.IO.Path]::IsPathRooted($frontendDist)) {
    throw "Tauri frontendDist must stay repository-relative, got '$frontendDist'."
}
$resolvedFrontendDist = [System.IO.Path]::GetFullPath(
    (Join-Path (Join-Path $root "platform\tauri\src-tauri") $frontendDist)
)
$expectedWebDist = [System.IO.Path]::GetFullPath((Join-Path $root "platform\tauri\web\dist"))
if ($resolvedFrontendDist -ne $expectedWebDist) {
    throw "Tauri frontendDist must resolve to $expectedWebDist, got $resolvedFrontendDist."
}

$bundleOverride = Get-Content -Raw -LiteralPath $bundleConfig | ConvertFrom-Json
if ($bundleOverride.PSObject.Properties.Name -contains "build") {
    $buildOverride = $bundleOverride.build
    $forbiddenBuildKeys = @("frontendDist", "devUrl", "beforeBuildCommand", "beforeDevCommand")
    $overriddenBuildKeys = @(
        foreach ($key in $forbiddenBuildKeys) {
            if ($buildOverride.PSObject.Properties.Name -contains $key) {
                $key
            }
        }
    )
    if ($overriddenBuildKeys.Count -gt 0) {
        throw "Bundle override must not override Tauri frontend entry settings: $($overriddenBuildKeys -join ', ')."
    }
}

$createsUpdaterArtifacts = $false
if (
    $tauriConfigJson.bundle -and
    ($tauriConfigJson.bundle.PSObject.Properties.Name -contains "createUpdaterArtifacts")
) {
    $createsUpdaterArtifacts = [bool]$tauriConfigJson.bundle.createUpdaterArtifacts
}
if ($createsUpdaterArtifacts -and -not $env:TAURI_SIGNING_PRIVATE_KEY) {
    $defaultSigningKey = Join-Path (Join-Path $env:USERPROFILE ".tauri") "miaogent.key"
    if (Test-Path -LiteralPath $defaultSigningKey) {
        $env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw -LiteralPath $defaultSigningKey
    }
    else {
        throw "Updater artifacts are enabled but TAURI_SIGNING_PRIVATE_KEY is not set. Generate a key with 'npm run tauri -- signer generate --ci --write-keys `$env:USERPROFILE\.tauri\miaogent.key' or configure the GitHub Actions secret."
    }
}

$hostLine = rustc -vV | Where-Object { $_ -like "host:*" } | Select-Object -First 1
if (-not $hostLine) {
    throw "Unable to determine the Rust host target triple."
}
$hostTriple = ($hostLine -replace "^host:\s*", "").Trim()
if (-not $TargetTriple) {
    $TargetTriple = $hostTriple
}
if ($TargetTriple -ne $hostTriple -or $TargetTriple -notmatch "windows") {
    throw "Desktop packaging only supports the current Windows host triple ($hostTriple)."
}

$sidecarArtifact = & $sidecarScript -PythonExecutable $PythonExecutable -TargetTriple $TargetTriple |
    Select-Object -Last 1
if ($LASTEXITCODE -ne 0) {
    throw "Sidecar build failed with exit code $LASTEXITCODE."
}
if (-not $sidecarArtifact.Path -or -not (Test-Path -LiteralPath $sidecarArtifact.Path)) {
    throw "Sidecar build did not return a valid artifact."
}

$buildId = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$cargoTargetDir = Join-Path $root "build\tauri-target\$buildId"
if (Test-Path -LiteralPath $cargoTargetDir) {
    throw "Unique Cargo target already exists: $cargoTargetDir"
}
$previousCargoTargetDir = $env:CARGO_TARGET_DIR
$env:CARGO_TARGET_DIR = $cargoTargetDir

Push-Location (Join-Path $root "platform\tauri")
try {
    & $tauriCli build --config $bundleConfig --target $TargetTriple --ci
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
    $env:CARGO_TARGET_DIR = $previousCargoTargetDir
}

$frontendIndex = Join-Path $resolvedFrontendDist "index.html"
if (-not (Test-Path -LiteralPath $frontendIndex)) {
    throw "Frontend build does not contain index.html at $frontendIndex."
}
$frontendHtml = Get-Content -Raw -LiteralPath $frontendIndex
if ($frontendHtml -notmatch '<div id="root"></div>') {
    throw "Frontend index.html does not look like the React app entry."
}

$releaseRoot = Join-Path $cargoTargetDir "$TargetTriple\release"
$bundleRoot = Join-Path $releaseRoot "bundle\nsis"
$installer = Get-ChildItem -LiteralPath $bundleRoot -Filter "*.exe" -File |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if (-not $installer) {
    throw "Tauri did not produce an NSIS installer under $bundleRoot."
}
$releaseSidecar = Join-Path $releaseRoot "qq-mail-agent-worker.exe"
if (-not (Test-Path -LiteralPath $releaseSidecar)) {
    throw "Tauri release staging does not contain qq-mail-agent-worker.exe."
}
$releaseSidecarHash = Get-FileHash -Algorithm SHA256 -LiteralPath $releaseSidecar
if ($releaseSidecarHash.Hash -ne $sidecarArtifact.SHA256) {
    throw "Tauri release sidecar hash does not match the PyInstaller artifact."
}
$nsisScript = Get-ChildItem -LiteralPath (Join-Path $releaseRoot "nsis") -Filter "installer.nsi" -File -Recurse |
    Select-Object -First 1
if (-not $nsisScript -or -not (Select-String -LiteralPath $nsisScript.FullName -SimpleMatch 'oname=qq-mail-agent-worker.exe' -Quiet)) {
    throw "NSIS input does not include qq-mail-agent-worker.exe."
}
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $installer.FullName
$signaturePath = "$($installer.FullName).sig"
$signatureHash = ""
if ($createsUpdaterArtifacts) {
    if (-not (Test-Path -LiteralPath $signaturePath)) {
        throw "Updater signature was not produced: $signaturePath"
    }
    $signatureHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $signaturePath).Hash
}

[pscustomobject]@{
    Path = $installer.FullName
    Bytes = $installer.Length
    SHA256 = $hash.Hash
    SignaturePath = if ($createsUpdaterArtifacts) { $signaturePath } else { "" }
    SignatureSHA256 = $signatureHash
    SidecarPath = $releaseSidecar
    SidecarSHA256 = $releaseSidecarHash.Hash
    CargoTargetDir = $cargoTargetDir
    TargetTriple = $TargetTriple
}

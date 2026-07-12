param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [Parameter(Mandatory = $true)]
    [string]$SignaturePath,

    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [string]$Notes = "MiaoGent desktop update."
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Installer does not exist: $InstallerPath"
}
if (-not (Test-Path -LiteralPath $SignaturePath)) {
    throw "Updater signature does not exist: $SignaturePath"
}

$normalizedVersion = $Version.Trim()
if (-not $normalizedVersion) {
    throw "Version is required."
}
$tag = if ($normalizedVersion.StartsWith("v")) { $normalizedVersion } else { "v$normalizedVersion" }
$metadataVersion = $normalizedVersion.TrimStart("v")

$installer = Get-Item -LiteralPath $InstallerPath
$signature = (Get-Content -Raw -LiteralPath $SignaturePath).Trim()
if (-not $signature) {
    throw "Updater signature is empty: $SignaturePath"
}

$releaseBase = "https://github.com/$Repository/releases/download/$tag"
$payload = [ordered]@{
    version = $metadataVersion
    notes = $Notes
    pub_date = (Get-Date).ToUniversalTime().ToString("o")
    platforms = [ordered]@{
        "windows-x86_64" = [ordered]@{
            signature = $signature
            url = "$releaseBase/$($installer.Name)"
        }
    }
}

$parent = Split-Path -Parent $OutputPath
if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Get-Item -LiteralPath $OutputPath

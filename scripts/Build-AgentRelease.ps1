[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = "",
    [string]$PrivateKey = "dev-secrets\update_private.pem",
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $project
try {
    $sourceVersion = (Get-Content -LiteralPath AGENT_VERSION -Raw).Trim()
    if (-not $Version) { $Version = $sourceVersion }
    if ($Version -ne $sourceVersion) { throw "AGENT_VERSION contains $sourceVersion; expected $Version." }
    if (-not (Test-Path -LiteralPath $Python)) { throw "Python environment not found: $Python" }
    if (-not (Test-Path -LiteralPath $PrivateKey)) { throw "Signing key not found: $PrivateKey" }
    & $Python scripts\release_tools.py build-agent-release --project $project --version $Version --private-key $PrivateKey
    if ($LASTEXITCODE -ne 0) { throw "Signed Agent release build failed." }
    $bundle = "release-output\v$Version\HosMonitorAgent-$Version.hmagent"
    Write-Host "Built signed Agent update: $project\$bundle"
    Write-Host "SHA-256: $((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash)"
} finally {
    Pop-Location
}

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$MinimumVersion = "0.1.0",
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$PrivateKey = ".\dev-secrets\update_private.pem"
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $project
try {
    $sourceVersion = (Get-Content -LiteralPath VERSION -Raw).Trim()
    if ($sourceVersion -ne $Version) { throw "VERSION contains $sourceVersion; expected $Version." }
    if (-not (Test-Path -LiteralPath $PrivateKey)) { throw "Missing private signing key. Run scripts\New-UpdateSigningKey.ps1 once." }
    & $Python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; release stopped." }
    & $Python -m PyInstaller --noconfirm --clean HosMonitorServer.spec
    if ($LASTEXITCODE -ne 0) { throw "Server build failed." }
    Copy-Item -LiteralPath VERSION -Destination (Join-Path $project "dist\VERSION") -Force
    & $Python scripts\release_tools.py build-release --project $project --version $Version --minimum-version $MinimumVersion --private-key $PrivateKey
    if ($LASTEXITCODE -ne 0) { throw "Signed release creation failed." }
} finally { Pop-Location }

[CmdletBinding()]
param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $project
try {
    $version = (Get-Content -LiteralPath VERSION -Raw).Trim()
    $AgentToken = [string]$env:HOS_MONITOR_BUILD_AGENT_TOKEN
    if ($AgentToken.Length -lt 24) { throw "HOS_MONITOR_BUILD_AGENT_TOKEN must contain at least 24 characters." }
    New-Item -ItemType Directory -Path build -Force | Out-Null
    [ordered]@{ schema=1; agent_token=$AgentToken; version=$version } |
        ConvertTo-Json | Set-Content -LiteralPath "build\server-bootstrap.json" -Encoding UTF8
    if (-not $SkipTests) {
        & $Python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "Tests failed; Server Setup build stopped." }
    }
    & $Python -m PyInstaller --noconfirm --clean HosMonitorServer.spec
    if ($LASTEXITCODE -ne 0) { throw "Server build failed." }
    & $Python -m PyInstaller --noconfirm --clean HosMonitorUpdater.spec
    if ($LASTEXITCODE -ne 0) { throw "Updater build failed." }
    & $Python -m PyInstaller --noconfirm --clean HosMonitorServerControl.spec
    if ($LASTEXITCODE -ne 0) { throw "Server Control build failed." }
    & $Python -m PyInstaller --noconfirm --clean HosMonitorServerSetup.spec
    if ($LASTEXITCODE -ne 0) { throw "Server Setup build failed." }
    $versioned = "dist\HosMonitorServerSetup-$version.exe"
    Copy-Item -LiteralPath "dist\HosMonitorServerSetup.exe" -Destination $versioned -Force
    Write-Host "One-click Server installer: $project\$versioned"
    Write-Host "SHA-256: $((Get-FileHash -LiteralPath $versioned -Algorithm SHA256).Hash)"
} finally {
    if (Test-Path -LiteralPath "build\server-bootstrap.json") {
        Remove-Item -LiteralPath "build\server-bootstrap.json" -Force
    }
    Pop-Location
}

[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = "",
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $project
try {
    if (-not $Version) { $Version = (Get-Content -LiteralPath VERSION -Raw).Trim() }
    if ((Get-Content -LiteralPath VERSION -Raw).Trim() -ne $Version) { throw "VERSION does not match $Version." }
    if (-not (Test-Path -LiteralPath update_public.pem)) { throw "Missing update_public.pem. Run scripts\New-UpdateSigningKey.ps1 once." }
    if (-not $SkipBuild) {
        & $Python -m pip install -r requirements-dev.txt
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
        & $Python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "Tests failed; package build stopped." }
        & $Python -m PyInstaller --noconfirm --clean HosMonitorServer.spec
        if ($LASTEXITCODE -ne 0) { throw "Server build failed." }
        & $Python -m PyInstaller --noconfirm --clean HosMonitorUpdater.spec
        if ($LASTEXITCODE -ne 0) { throw "Updater build failed." }
    }
    foreach ($artifact in @("dist\HosMonitorServer.exe", "dist\HosMonitorUpdater.exe")) {
        if (-not (Test-Path -LiteralPath $artifact)) { throw "Missing build artifact: $artifact" }
    }
    Copy-Item -LiteralPath VERSION -Destination (Join-Path $project "dist\VERSION") -Force

    $stage = Join-Path $project "build\deployment-package"
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    foreach ($name in @("HosMonitorServer.exe", "HosMonitorUpdater.exe")) {
        Copy-Item -LiteralPath (Join-Path $project "dist\$name") -Destination $stage
    }
    foreach ($name in @("VERSION", "update_public.pem", "README.md", "THIRD_PARTY_NOTICES.md")) {
        Copy-Item -LiteralPath (Join-Path $project $name) -Destination $stage
    }
    Copy-Item -LiteralPath (Join-Path $project "agent\WinSW-x64.exe") -Destination $stage
    Copy-Item -Path (Join-Path $project "deployment\*") -Destination $stage
    $destination = Join-Path $project "dist\HosMonitorServer-$Version.zip"
    if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Force }
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $destination -CompressionLevel Optimal
    Write-Host "Deployment package: $destination"
} finally { Pop-Location }

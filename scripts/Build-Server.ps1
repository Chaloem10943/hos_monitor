[CmdletBinding()]
param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $project
try {
    & $Python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; build stopped." }
    & $Python -m PyInstaller --noconfirm --clean HosMonitorServer.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
    Copy-Item -LiteralPath VERSION -Destination (Join-Path $project "dist\VERSION") -Force
    Write-Host "Built: $project\dist\HosMonitorServer.exe"
    Write-Host "For a production installer run scripts\Build-DeploymentPackage.ps1."
} finally { Pop-Location }

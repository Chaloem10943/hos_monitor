[CmdletBinding()]
param(
    [ValidatePattern('^https?://')][string]$ServerUrl = "http://192.168.111.65:6001",
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $project
try {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $env:HOS_MONITOR_BUILD_AGENT_TOKEN = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; installer build stopped." }
    & .\scripts\Build-ServerInstaller.ps1 -Python $Python -SkipTests
    if ($LASTEXITCODE -ne 0) { throw "Server installer build failed." }
    $agentVersion = (Get-Content -LiteralPath AGENT_VERSION -Raw).Trim()
    & .\scripts\Build-AgentInstaller.ps1 -ServerUrl $ServerUrl -Version $agentVersion -Python $Python -SkipTests
    if ($LASTEXITCODE -ne 0) { throw "Agent installer build failed." }
    $serverVersion = (Get-Content -LiteralPath VERSION -Raw).Trim()
    Write-Host ""
    Write-Host "Fresh deployment pair is ready:"
    Write-Host "  dist\HosMonitorServerSetup-$serverVersion.exe"
    Write-Host "  dist\HosMonitorAgentSetup-$agentVersion.exe"
    Write-Host "Install Server first, then install Agent. Both use the same embedded token."
} finally {
    Remove-Item Env:HOS_MONITOR_BUILD_AGENT_TOKEN -ErrorAction SilentlyContinue
    Pop-Location
}

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ServerUrl,
    [Parameter(Mandatory=$true)][string]$AgentToken,
    [string]$AssetTag = "",
    [string]$Department = "",
    [string]$InstallDirectory = "$env:ProgramFiles\HosMonitor Agent",
    [string]$DataDirectory = "$env:ProgramData\HosMonitor"
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this installer from PowerShell as Administrator."
}
if ($AgentToken.Length -lt 24) { throw "AgentToken must contain at least 24 characters." }

$programFilesRoot = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
$programDataRoot = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\') + '\'
$safeInstall = [IO.Path]::GetFullPath($InstallDirectory)
$safeData = [IO.Path]::GetFullPath($DataDirectory)
if (-not $safeInstall.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallDirectory must be a child of $env:ProgramFiles"
}
if (-not $safeData.StartsWith($programDataRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDirectory must be a child of $env:ProgramData"
}
$InstallDirectory = $safeInstall
$DataDirectory = $safeData

$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$winswSource = Join-Path $source "WinSW-x64.exe"
if (-not (Test-Path -LiteralPath $winswSource)) {
    throw "WinSW-x64.exe is missing. Place the official WinSW x64 executable beside this installer."
}

New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
$serviceExe = Join-Path $InstallDirectory "HosMonitorAgentService.exe"
$serviceXml = Join-Path $InstallDirectory "HosMonitorAgentService.xml"
$agentScript = Join-Path $InstallDirectory "HosMonitorAgent.ps1"
$configPath = Join-Path $DataDirectory "agent-config.json"

$existing = Get-Service -Name "HosMonitorAgent" -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    if (-not (Test-Path -LiteralPath $serviceExe)) { throw "Existing service wrapper not found: $serviceExe" }
    & $serviceExe stop | Out-Null
    & $serviceExe uninstall | Out-Null
}

Copy-Item -LiteralPath (Join-Path $source "HosMonitorAgent.ps1") -Destination $agentScript -Force
Copy-Item -LiteralPath $winswSource -Destination $serviceExe -Force
$xml = Get-Content -LiteralPath (Join-Path $source "HosMonitorAgentService.xml.template") -Raw
$xml = $xml.Replace("{{AGENT_SCRIPT}}", $agentScript).Replace("{{CONFIG_PATH}}", $configPath)
$xml | Set-Content -LiteralPath $serviceXml -Encoding UTF8

$config = [ordered]@{
    server_url = $ServerUrl.TrimEnd("/")
    agent_token = $AgentToken
    asset_tag = $AssetTag
    department = $Department
}
$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8

# Config contains the shared token: only Administrators, SYSTEM and LocalService may access it.
& icacls.exe $DataDirectory /inheritance:r /grant:r "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "LOCAL SERVICE:(OI)(CI)M" | Out-Null
& icacls.exe $InstallDirectory /inheritance:r /grant:r "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "LOCAL SERVICE:(OI)(CI)RX" | Out-Null

& $serviceExe install
& $serviceExe start
Write-Host "HosMonitor Agent installed and started."
Write-Host "Config: $configPath"
Write-Host "Service: HosMonitorAgent"

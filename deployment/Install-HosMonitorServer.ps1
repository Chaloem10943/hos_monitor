[CmdletBinding()]
param(
    [string]$InstallDirectory = "$env:ProgramFiles\HosMonitor Server",
    [string]$DataDirectory = "$env:ProgramData\HosMonitorServer",
    [int]$Port = 6001
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this installer from PowerShell as Administrator."
}
if ($Port -lt 1 -or $Port -gt 65535) { throw "Port must be between 1 and 65535." }

$programFilesRoot = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
$programDataRoot = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\') + '\'
$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
if (-not $InstallDirectory.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallDirectory must be a child of $env:ProgramFiles"
}
if (-not $DataDirectory.StartsWith($programDataRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDirectory must be a child of $env:ProgramData"
}

$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$required = @("HosMonitorServer.exe", "HosMonitorUpdater.exe", "VERSION", "update_public.pem", "WinSW-x64.exe")
foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $name))) { throw "Missing package file: $name" }
}

New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
$serverWrapper = Join-Path $InstallDirectory "HosMonitorServerService.exe"
$updaterWrapper = Join-Path $InstallDirectory "HosMonitorUpdaterService.exe"
foreach ($service in @(
    @{Name="HosMonitorUpdater"; Wrapper=$updaterWrapper},
    @{Name="HosMonitorServer"; Wrapper=$serverWrapper}
)) {
    if ($null -ne (Get-Service -Name $service.Name -ErrorAction SilentlyContinue)) {
        if (-not (Test-Path -LiteralPath $service.Wrapper)) { throw "Existing wrapper is missing: $($service.Wrapper)" }
        & $service.Wrapper stop | Out-Null
        & $service.Wrapper uninstall | Out-Null
    }
}

foreach ($installedProcess in @(
    @{Name="HosMonitorServer.exe"; Path=(Join-Path $InstallDirectory "HosMonitorServer.exe")},
    @{Name="HosMonitorUpdater.exe"; Path=(Join-Path $InstallDirectory "HosMonitorUpdater.exe")}
)) {
    foreach ($attempt in 1..20) {
        $running = Get-CimInstance Win32_Process -Filter "Name='$($installedProcess.Name)'" -ErrorAction SilentlyContinue |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
                [string]::Equals($_.ExecutablePath, $installedProcess.Path, [StringComparison]::OrdinalIgnoreCase)
            }
        if (-not $running) { break }
        $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 250
    }
    $remaining = Get-CimInstance Win32_Process -Filter "Name='$($installedProcess.Name)'" -ErrorAction SilentlyContinue |
        Where-Object {
            -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
            [string]::Equals($_.ExecutablePath, $installedProcess.Path, [StringComparison]::OrdinalIgnoreCase)
        }
    if ($remaining) { throw "Unable to stop the installed process: $($installedProcess.Path)" }
}

function Copy-ProgramFile {
    param([Parameter(Mandatory=$true)][string]$Name)
    $sourcePath = Join-Path $source $Name
    $destinationPath = Join-Path $InstallDirectory $Name
    foreach ($attempt in 1..20) {
        try {
            Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force -ErrorAction Stop
            return
        } catch [System.IO.IOException] {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
}

Copy-ProgramFile "HosMonitorServer.exe"
Copy-ProgramFile "HosMonitorUpdater.exe"
Copy-Item -LiteralPath (Join-Path $source "VERSION") -Destination $InstallDirectory -Force
Copy-Item -LiteralPath (Join-Path $source "update_public.pem") -Destination (Join-Path $DataDirectory "update_public.pem") -Force
Copy-Item -LiteralPath (Join-Path $source "WinSW-x64.exe") -Destination $serverWrapper -Force
Copy-Item -LiteralPath (Join-Path $source "WinSW-x64.exe") -Destination $updaterWrapper -Force

$configPath = Join-Path $DataDirectory "config.yaml"
if (-not (Test-Path -LiteralPath $configPath)) {
    $agentTokenBytes = New-Object byte[] 32
    $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $randomGenerator.GetBytes($agentTokenBytes)
    } finally {
        $randomGenerator.Dispose()
    }
    $agentToken = [Convert]::ToBase64String($agentTokenBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    $config = [ordered]@{
        server = [ordered]@{ host = "0.0.0.0"; port = $Port; cookie_secure = $false }
        storage = [ordered]@{ data_dir = $DataDirectory; database = "hos_monitor.db" }
        security = [ordered]@{ agent_token = $agentToken; session_hours = 8 }
        monitoring = [ordered]@{ online_threshold_seconds = 300 }
        updates = [ordered]@{
            enabled = $false; backup_retention = 5
            public_key = "update_public.pem"; server_service_name = "HosMonitorServer"
        }
    }
    $config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configPath -Encoding UTF8
}

$serverXml = Get-Content -LiteralPath (Join-Path $source "HosMonitorServerService.xml.template") -Raw
$serverXml = $serverXml.Replace("{{SERVER_EXE}}", [System.Security.SecurityElement]::Escape((Join-Path $InstallDirectory "HosMonitorServer.exe")))
$serverXml = $serverXml.Replace("{{CONFIG_PATH}}", [System.Security.SecurityElement]::Escape($configPath))
$serverXml | Set-Content -LiteralPath (Join-Path $InstallDirectory "HosMonitorServerService.xml") -Encoding UTF8
$updaterXml = Get-Content -LiteralPath (Join-Path $source "HosMonitorUpdaterService.xml.template") -Raw
$updaterXml = $updaterXml.Replace("{{UPDATER_EXE}}", [System.Security.SecurityElement]::Escape((Join-Path $InstallDirectory "HosMonitorUpdater.exe")))
$updaterXml = $updaterXml.Replace("{{CONFIG_PATH}}", [System.Security.SecurityElement]::Escape($configPath))
$updaterXml | Set-Content -LiteralPath (Join-Path $InstallDirectory "HosMonitorUpdaterService.xml") -Encoding UTF8

& icacls.exe $DataDirectory /inheritance:r /grant:r "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "LOCAL SERVICE:(OI)(CI)M" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unable to apply the data-directory ACL." }
& icacls.exe $InstallDirectory /inheritance:r /grant:r "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "LOCAL SERVICE:(OI)(CI)RX" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unable to apply the install-directory ACL." }

& $updaterWrapper install
if ($LASTEXITCODE -ne 0) { throw "Unable to install HosMonitorUpdater." }
& $serverWrapper install
if ($LASTEXITCODE -ne 0) { throw "Unable to install HosMonitorServer." }
& $updaterWrapper start
& $serverWrapper start
Write-Host "HosMonitor Server and signed updater are installed and running."
Write-Host "Dashboard: http://localhost:$Port"
Write-Host "Config/data: $DataDirectory"

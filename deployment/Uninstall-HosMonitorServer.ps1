[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact="High")]
param(
    [string]$InstallDirectory = "$env:ProgramFiles\HosMonitor Server",
    [string]$DataDirectory = "$env:ProgramData\HosMonitorServer",
    [switch]$PurgeData
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this uninstaller from PowerShell as Administrator."
}
$programFilesRoot = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
$programDataRoot = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\') + '\'
$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
if (-not $InstallDirectory.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe install path." }
if (-not $DataDirectory.StartsWith($programDataRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe data path." }

foreach ($service in @(
    @{Name="HosMonitorUpdater"; Wrapper=(Join-Path $InstallDirectory "HosMonitorUpdaterService.exe")},
    @{Name="HosMonitorServer"; Wrapper=(Join-Path $InstallDirectory "HosMonitorServerService.exe")}
)) {
    if ($null -ne (Get-Service -Name $service.Name -ErrorAction SilentlyContinue)) {
        if (-not (Test-Path -LiteralPath $service.Wrapper)) { throw "Existing wrapper is missing: $($service.Wrapper)" }
        & $service.Wrapper stop | Out-Null
        & $service.Wrapper uninstall | Out-Null
    }
}
if (Test-Path -LiteralPath $InstallDirectory) {
    if ($PSCmdlet.ShouldProcess($InstallDirectory, "Remove HosMonitor program files")) {
        Remove-Item -LiteralPath $InstallDirectory -Recurse -Force
    }
}
if ($PurgeData -and (Test-Path -LiteralPath $DataDirectory)) {
    if ($PSCmdlet.ShouldProcess($DataDirectory, "Permanently remove HosMonitor database, config and backups")) {
        Remove-Item -LiteralPath $DataDirectory -Recurse -Force
    }
} else {
    Write-Host "Data preserved at $DataDirectory"
}

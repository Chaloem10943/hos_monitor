[CmdletBinding()]
param(
    [string]$InstallDirectory = "$env:ProgramFiles\HosMonitor Agent",
    [string]$DataDirectory = "$env:ProgramData\HosMonitor",
    [switch]$PurgeData
)

$ErrorActionPreference = "Stop"
Remove-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" -Name "HosMonitorWallpaper" -ErrorAction SilentlyContinue
$programFilesRoot = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
$programDataRoot = [IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\') + '\'
$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
if (-not $InstallDirectory.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing unexpected install directory: $InstallDirectory"
}
if (-not $DataDirectory.StartsWith($programDataRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing unexpected data directory: $DataDirectory"
}
$serviceExe = Join-Path $InstallDirectory "HosMonitorAgentService.exe"
if (Test-Path -LiteralPath $serviceExe) {
    & $serviceExe stop | Out-Null
    & $serviceExe uninstall | Out-Null
}
if (Test-Path -LiteralPath $InstallDirectory) { Remove-Item -LiteralPath $InstallDirectory -Recurse -Force }
if ($PurgeData -and (Test-Path -LiteralPath $DataDirectory)) {
    $resolved = (Resolve-Path -LiteralPath $DataDirectory).Path
    if (-not $resolved.StartsWith($programDataRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing to purge unexpected data directory: $resolved" }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
Write-Host "HosMonitor Agent uninstalled. Data is preserved unless -PurgeData was supplied."

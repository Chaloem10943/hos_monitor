[CmdletBinding()]
param(
    [string]$PolicyPath = "$env:ProgramData\HosMonitor\wallpaper\wallpaper-policy.json",
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$logDirectory = Join-Path $env:LOCALAPPDATA "HosMonitor"
$logPath = Join-Path $logDirectory "wallpaper.log"
$mutex = New-Object System.Threading.Mutex($false, "Local\HosMonitorWallpaper")
if (-not $mutex.WaitOne(0, $false)) { exit 0 }

function Write-WallpaperLog {
    param([string]$Message, [string]$Level = "INFO")
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    Add-Content -LiteralPath $logPath -Value ("{0} [{1}] {2}" -f (Get-Date).ToString("s"), $Level, $Message) -Encoding UTF8
}

if (-not ("HosMonitor.NativeWallpaper" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
namespace HosMonitor {
    public static class NativeWallpaper {
        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool SystemParametersInfo(int action, int parameter, string value, int flags);
    }
}
"@
}

function Remove-WallpaperPolicy {
    foreach ($target in @(
        @{Path="HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\System"; Names=@("Wallpaper","WallpaperStyle")},
        @{Path="HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\ActiveDesktop"; Names=@("NoChangingWallPaper")}
    )) {
        foreach ($name in $target.Names) {
            Remove-ItemProperty -LiteralPath $target.Path -Name $name -ErrorAction SilentlyContinue
        }
    }
    New-Item -Path "HKCU:\Software\HosMonitor" -Force | Out-Null
    Set-ItemProperty -LiteralPath "HKCU:\Software\HosMonitor" -Name "WallpaperRevision" -Value "disabled"
}

function Apply-WallpaperPolicy {
    param([object]$Policy)
    if (-not [bool]$Policy.enabled) {
        Remove-WallpaperPolicy
        Write-WallpaperLog "Wallpaper policy disabled"
        return
    }
    $imagePath = [IO.Path]::GetFullPath([string]$Policy.image_path)
    $allowedRoot = [IO.Path]::GetFullPath((Join-Path $env:ProgramData "HosMonitor\wallpaper")).TrimEnd('\') + '\'
    if (-not $imagePath.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Wallpaper path is outside the managed directory"
    }
    if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) { throw "Wallpaper image is missing" }

    $systemPolicy = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\System"
    $activeDesktop = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\ActiveDesktop"
    $desktop = "HKCU:\Control Panel\Desktop"
    New-Item -Path $systemPolicy -Force | Out-Null
    New-Item -Path $activeDesktop -Force | Out-Null
    Set-ItemProperty -LiteralPath $systemPolicy -Name "Wallpaper" -Value $imagePath
    Set-ItemProperty -LiteralPath $systemPolicy -Name "WallpaperStyle" -Value "10"
    Set-ItemProperty -LiteralPath $desktop -Name "Wallpaper" -Value $imagePath
    Set-ItemProperty -LiteralPath $desktop -Name "WallpaperStyle" -Value "10"
    Set-ItemProperty -LiteralPath $desktop -Name "TileWallpaper" -Value "0"
    New-ItemProperty -LiteralPath $activeDesktop -Name "NoChangingWallPaper" -PropertyType DWord -Value ($(if ([bool]$Policy.locked) { 1 } else { 0 })) -Force | Out-Null
    if (-not [HosMonitor.NativeWallpaper]::SystemParametersInfo(20, 0, $imagePath, 3)) {
        throw "Windows rejected the desktop wallpaper update"
    }
    New-Item -Path "HKCU:\Software\HosMonitor" -Force | Out-Null
    Set-ItemProperty -LiteralPath "HKCU:\Software\HosMonitor" -Name "WallpaperRevision" -Value ([string]$Policy.revision)
    Write-WallpaperLog "Wallpaper applied revision=$($Policy.revision)"
}

try {
    do {
        try {
            if (Test-Path -LiteralPath $PolicyPath) {
                $policy = Get-Content -LiteralPath $PolicyPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $current = (Get-ItemProperty -LiteralPath "HKCU:\Software\HosMonitor" -Name "WallpaperRevision" -ErrorAction SilentlyContinue).WallpaperRevision
                $wanted = if ([bool]$policy.enabled) { [string]$policy.revision } else { "disabled" }
                if ([string]$current -ne $wanted) { Apply-WallpaperPolicy -Policy $policy }
            }
        } catch {
            Write-WallpaperLog $_.Exception.Message "ERROR"
        }
        if (-not $Once) { Start-Sleep -Seconds 30 }
    } while (-not $Once)
} finally {
    try { $mutex.ReleaseMutex() } catch {}
    $mutex.Dispose()
}

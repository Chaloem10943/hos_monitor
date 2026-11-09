[CmdletBinding()]
param(
    [string]$Repository = "Chaloem10943/hos_monitor",
    [string]$ServerUrl = "http://127.0.0.1:6001",
    [string]$DownloadDirectory = "$env:ProgramData\HosMonitorServer\updates\downloads",
    [switch]$CheckOnly,
    [switch]$Force,
    [switch]$Install
)

$ErrorActionPreference = "Stop"

function Get-InstalledVersion {
    try {
        $res = Invoke-RestMethod -Uri "$ServerUrl/health" -Method Get -TimeoutSec 5 -ErrorAction Stop
        if ($res.version) { return [string]$res.version }
    } catch {}

    $localVersionFile = "$env:ProgramFiles\HosMonitor Server\VERSION"
    if (Test-Path -LiteralPath $localVersionFile) {
        return (Get-Content -LiteralPath $localVersionFile -Raw).Trim()
    }

    if ($PSScriptRoot) {
        $sourceVersionFile = Join-Path (Split-Path -Parent $PSScriptRoot) "VERSION"
        if (Test-Path -LiteralPath $sourceVersionFile) {
            return (Get-Content -LiteralPath $sourceVersionFile -Raw).Trim()
        }
    }

    return "0.0.0"
}

function Get-LatestGitHubRelease {
    param([string]$Repo)
    try {
        $json = & gh.exe release view --repo $Repo --json tagName,name,assets,publishedAt 2>$null
        if ($LASTEXITCODE -eq 0 -and $json) {
            return ($json | ConvertFrom-Json)
        }
    } catch {}

    $apiUrl = "https://api.github.com/repos/$Repo/releases/latest"
    $headers = @{ "User-Agent" = "HosMonitor-Updater" }
    return Invoke-RestMethod -Uri $apiUrl -Headers $headers -Method Get -TimeoutSec 15
}

function ConvertTo-VersionTuple {
    param([string]$Ver)
    $clean = $Ver.TrimStart('v').Trim()
    return [version]$clean
}

$currentVersion = Get-InstalledVersion
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " HosMonitor Update Checker (GitHub)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Installed Version : $currentVersion"
Write-Host "Repository        : $Repository"

Write-Host "`nChecking for updates on GitHub..." -ForegroundColor Yellow
$release = Get-LatestGitHubRelease -Repo $Repository
if (-not $release) {
    throw "Failed to fetch release information from GitHub repository: $Repository"
}

$latestTag = if ($release.tagName) { $release.tagName } else { $release.tag_name }
$latestVersion = $latestTag.TrimStart('v')
Write-Host "Latest Version    : $latestVersion ($latestTag)"

$isNewer = (ConvertTo-VersionTuple $latestVersion) -gt (ConvertTo-VersionTuple $currentVersion)

if (-not $isNewer -and -not $Force) {
    Write-Host "`n[OK] HosMonitor is up to date." -ForegroundColor Green
    return
}

if ($isNewer) {
    Write-Host "`n[UPDATE AVAILABLE] A newer version ($latestVersion) is available!" -ForegroundColor Magenta
} elseif ($Force) {
    Write-Host "`n[FORCE] Downloading release $latestVersion..." -ForegroundColor Yellow
}

if ($CheckOnly) {
    return
}

if (-not (Test-Path -LiteralPath $DownloadDirectory)) {
    New-Item -ItemType Directory -Path $DownloadDirectory -Force | Out-Null
}

$downloadedFiles = @()

# Use gh release download if gh is available
$hasGh = $false
try {
    $null = & gh.exe --version 2>$null
    if ($LASTEXITCODE -eq 0) { $hasGh = $true }
} catch {}

if ($hasGh) {
    Write-Host "Downloading release assets via GitHub CLI..." -ForegroundColor Gray
    & gh.exe release download "$latestTag" --repo $Repository --pattern "*.hmrelease" --pattern "*.hmagent" --pattern "*.sig" --pattern "*.json" --dir $DownloadDirectory --clobber
    if ($LASTEXITCODE -ne 0) {
        throw "gh release download failed."
    }
} else {
    Write-Host "Downloading release assets via Web API..." -ForegroundColor Gray
    $assetList = if ($release.assets) { $release.assets } else { @() }
    foreach ($asset in $assetList) {
        $assetName = $asset.name
        if ($assetName -match '\.(hmrelease|hmagent|sig|json)$') {
            $destPath = Join-Path $DownloadDirectory $assetName
            Write-Host "Downloading $assetName..." -ForegroundColor Gray
            $downloadUrl = if ($asset.browser_download_url) { $asset.browser_download_url } else { $asset.url }
            if ($downloadUrl) {
                Invoke-WebRequest -Uri $downloadUrl -OutFile $destPath -TimeoutSec 120
            }
        }
    }
}

$downloadedFiles = @(Get-ChildItem -Path $DownloadDirectory -File | Where-Object { $_.Name -match '\.(hmrelease|hmagent|sig|json)$' })

Write-Host "`nDownloaded assets saved to: $DownloadDirectory" -ForegroundColor Green
foreach ($item in $downloadedFiles) {
    Write-Host (" - {0} ({1:N0} bytes)" -f $item.Name, $item.Length)
}

$serverRelease = Join-Path $DownloadDirectory "HosMonitorServer-$latestVersion.hmrelease"
if (-not (Test-Path -LiteralPath $serverRelease)) {
    $found = Get-ChildItem -Path $DownloadDirectory -Filter "*.hmrelease" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { $serverRelease = $found.FullName }
}

if ($Install) {
    if (-not (Test-Path -LiteralPath $serverRelease)) {
        throw "Cannot install: .hmrelease package not found in $DownloadDirectory"
    }

    Write-Host "`n[INSTALLING] Staging release package for HosMonitorUpdater..." -ForegroundColor Yellow
    $configPath = "$env:ProgramData\HosMonitorServer\config.yaml"
    if (-not (Test-Path -LiteralPath $configPath)) {
        $devConfig = Join-Path (Split-Path -Parent $PSScriptRoot) "config.yaml"
        if (Test-Path -LiteralPath $devConfig) { $configPath = $devConfig }
    }

    $updaterExe = "$env:ProgramFiles\HosMonitor Server\HosMonitorUpdater.exe"
    $staged = $false

    if (Test-Path -LiteralPath $updaterExe) {
        Write-Host "Invoking HosMonitorUpdater.exe --stage..." -ForegroundColor Gray
        & $updaterExe --config "$configPath" --stage "$serverRelease" --requested-by "UpdateScript"
        if ($LASTEXITCODE -eq 0) { $staged = $true }
    }

    if (-not $staged) {
        # Try python in venv or path
        $pyCandidates = @(
            (Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Scripts\python.exe"),
            "python.exe"
        )
        foreach ($py in $pyCandidates) {
            try {
                $check = & $py --version 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $runnerScript = Join-Path (Split-Path -Parent $PSScriptRoot) "updater_runner.py"
                    if (Test-Path -LiteralPath $runnerScript) {
                        Write-Host "Invoking python updater_runner.py --stage..." -ForegroundColor Gray
                        & $py $runnerScript --config "$configPath" --stage "$serverRelease" --requested-by "UpdateScript"
                        if ($LASTEXITCODE -eq 0) { $staged = $true; break }
                    }
                }
            } catch {}
        }
    }

    if ($staged) {
        Write-Host "`n[SUCCESS] Release staged successfully!" -ForegroundColor Green
        Write-Host "HosMonitorUpdater service will now automatically:" -ForegroundColor Cyan
        Write-Host " 1. Back up database, config, and current binary"
        Write-Host " 2. Stop HosMonitorServer"
        Write-Host " 3. Apply new release files"
        Write-Host " 4. Start HosMonitorServer and verify health"
        Write-Host "`nPlease wait 10-15 seconds and refresh your Dashboard.`n"
        return
    } else {
        Write-Warning "Could not stage automatically via updater service. Please use manual upload below."
    }
}

Write-Host "`nTo apply Server update manually:" -ForegroundColor Cyan
Write-Host "1. Open HosMonitor Dashboard: $ServerUrl"
Write-Host "2. Go to 'System Updates' (อัปเดตระบบ)"
Write-Host "3. Upload: $serverRelease"
Write-Host "4. Enter Admin password, type 'UPDATE' and confirm.`n"
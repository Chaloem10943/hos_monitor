[CmdletBinding()]
param(
    [string]$Repository = "Chaloem10943/hos_monitor",
    [string]$ServerUrl = "http://127.0.0.1:6001",
    [string]$DownloadDirectory = "$env:ProgramData\HosMonitorServer\updates\downloads",
    [switch]$CheckOnly,
    [switch]$Force
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

Write-Host "`nTo apply Server update:" -ForegroundColor Cyan
Write-Host "1. Open HosMonitor Dashboard: $ServerUrl"
Write-Host "2. Go to 'System Updates' (อัปเดตระบบ)"
Write-Host "3. Upload: $(Join-Path $DownloadDirectory "HosMonitorServer-$latestVersion.hmrelease")"
Write-Host "4. Enter Admin password, type 'UPDATE' and confirm.`n"
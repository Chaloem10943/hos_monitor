[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory=$true)][string]$Repository,
    [string]$NotesFile = ""
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$release = Join-Path $project "release-output\v$Version"

$coreAssets = @(
    (Join-Path $release "manifest.json"),
    (Join-Path $release "manifest.sig"),
    (Join-Path $release "HosMonitorServer-update-$Version.zip"),
    (Join-Path $release "HosMonitorServer-$Version.hmrelease")
)
$assets = @()
foreach ($asset in $coreAssets) {
    if (Test-Path -LiteralPath $asset) {
        $assets += $asset
    }
}
if ($assets.Count -eq 0) {
    throw "No core release assets found in $release"
}

# Optional assets if present
$optionalAssets = @(
    (Join-Path $release "HosMonitorServerSetup-$Version.exe"),
    (Join-Path $release "HosMonitorAgent-$Version.hmagent"),
    (Join-Path $release "HosMonitorAgent-update-$Version.zip"),
    (Join-Path $release "HosMonitorAgentSetup-$Version.exe")
)
foreach ($opt in $optionalAssets) {
    if (Test-Path -LiteralPath $opt) {
        $assets += $opt
    }
}

& gh.exe auth status
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated." }

# Check if release already exists
$existing = & gh.exe release view "v$Version" --repo $Repository 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Release v$Version already exists on $Repository. Uploading/updating assets..." -ForegroundColor Cyan
    & gh.exe release upload "v$Version" @assets --repo $Repository --clobber
    if ($LASTEXITCODE -ne 0) { throw "Asset upload to existing release failed." }
} else {
    Write-Host "Creating new release v$Version on $Repository..." -ForegroundColor Cyan
    $arguments = @("release", "create", "v$Version", "--repo", $Repository, "--title", "HosMonitor v$Version")
    if ($NotesFile) { $arguments += @("--notes-file", $NotesFile) } else { $arguments += @("--generate-notes") }
    $arguments += $assets
    & gh.exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "GitHub release publishing failed." }
}
Write-Host "Successfully published HosMonitor v$Version to $Repository" -ForegroundColor Green
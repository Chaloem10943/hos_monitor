[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory=$true)][string]$Repository,
    [string]$NotesFile = ""
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$release = Join-Path $project "release-output\v$Version"
$assets = @(
    (Join-Path $release "manifest.json"),
    (Join-Path $release "manifest.sig"),
    (Join-Path $release "HosMonitorServer-update-$Version.zip"),
    (Join-Path $release "HosMonitorServer-$Version.hmrelease")
)
foreach ($asset in $assets) { if (-not (Test-Path -LiteralPath $asset)) { throw "Missing release asset: $asset" } }
& gh.exe auth status
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated." }
$arguments = @("release", "create", "v$Version", "--repo", $Repository, "--title", "HosMonitor v$Version")
if ($NotesFile) { $arguments += @("--notes-file", $NotesFile) } else { $arguments += @("--generate-notes") }
$arguments += $assets
& gh.exe @arguments
if ($LASTEXITCODE -ne 0) { throw "GitHub release publishing failed." }

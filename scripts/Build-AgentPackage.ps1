[CmdletBinding()]
param([string]$Version = "0.1.0")

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$agentDirectory = Join-Path $project "agent"
$wrapper = Join-Path $agentDirectory "WinSW-x64.exe"
if (-not (Test-Path -LiteralPath $wrapper)) { throw "Missing agent\WinSW-x64.exe" }
$expectedHash = "05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA"
$actualHash = (Get-FileHash -LiteralPath $wrapper -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) { throw "WinSW SHA-256 does not match the approved v2.12.0 binary." }
$dist = Join-Path $project "dist"
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$destination = Join-Path $dist "HosMonitorAgent-$Version.zip"
if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Force }
Compress-Archive -Path (Join-Path $agentDirectory "*"),(Join-Path $project "THIRD_PARTY_NOTICES.md") -DestinationPath $destination -CompressionLevel Optimal
Write-Host "Built: $destination"

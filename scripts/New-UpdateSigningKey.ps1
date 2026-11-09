[CmdletBinding()]
param([string]$Python = ".\.venv\Scripts\python.exe")

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$privateKey = Join-Path $project "dev-secrets\update_private.pem"
$publicKey = Join-Path $project "update_public.pem"
Push-Location $project
try {
    & $Python scripts\release_tools.py generate-key --private $privateKey --public $publicKey
    if ($LASTEXITCODE -ne 0) { throw "Signing key generation failed." }
    & icacls.exe $privateKey /inheritance:r /grant:r "$env:USERNAME`:(R,W)" "Administrators:(F)" "SYSTEM:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to restrict the private key ACL." }
    Write-Host "Keep dev-secrets\update_private.pem only on this development machine."
    Write-Host "Copy update_public.pem to production through the server installer."
} finally { Pop-Location }

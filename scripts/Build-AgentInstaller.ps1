[CmdletBinding()]
param(
    [ValidatePattern('^https?://')][string]$ServerUrl = "http://192.168.111.65:6001",
    [string]$AgentToken = "",
    [string]$ServerConfigPath = "",
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = "",
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $project
try {
    $sourceVersion = (Get-Content -LiteralPath AGENT_VERSION -Raw).Trim()
    if (-not $Version) { $Version = $sourceVersion }
    if ($Version -ne $sourceVersion) { throw "AGENT_VERSION contains $sourceVersion; expected $Version." }
    if ([string]::IsNullOrWhiteSpace($AgentToken)) {
        $AgentToken = [string]$env:HOS_MONITOR_BUILD_AGENT_TOKEN
    }
    if ([string]::IsNullOrWhiteSpace($ServerConfigPath) -and (Test-Path -LiteralPath "production-config.yaml")) {
        $ServerConfigPath = "production-config.yaml"
    }
    if ([string]::IsNullOrWhiteSpace($AgentToken) -and -not [string]::IsNullOrWhiteSpace($ServerConfigPath)) {
        if (-not (Test-Path -LiteralPath $ServerConfigPath)) { throw "Server config not found: $ServerConfigPath" }
        $configText = Get-Content -LiteralPath $ServerConfigPath -Raw
        try {
            $serverConfig = $configText | ConvertFrom-Json -ErrorAction Stop
            $AgentToken = [string]$serverConfig.security.agent_token
        } catch {
            $tokenMatch = [regex]::Match($configText, '(?m)^\s*agent_token:\s*["'']?([^#\r\n"'']+)')
            if ($tokenMatch.Success) { $AgentToken = $tokenMatch.Groups[1].Value.Trim() }
        }
    }
    if ([string]::IsNullOrWhiteSpace($AgentToken)) {
        $secureToken = Read-Host "Paste security.agent_token from the production server" -AsSecureString
        $tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
        try {
            $AgentToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
        }
    }
    if ($AgentToken.Length -lt 24) { throw "AgentToken must contain at least 24 characters." }
    if (-not (Test-Path -LiteralPath $Python)) { throw "Python environment not found: $Python" }
    if (-not (Test-Path -LiteralPath "update_public.pem")) { throw "update_public.pem is missing." }

    $wrapper = "agent\WinSW-x64.exe"
    $expectedHash = "05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA"
    if ((Get-FileHash -LiteralPath $wrapper -Algorithm SHA256).Hash -ne $expectedHash) {
        throw "WinSW SHA-256 does not match the approved v2.12.0 binary."
    }

    New-Item -ItemType Directory -Path build -Force | Out-Null
    $profile = [ordered]@{
        schema = 1
        server_url = $ServerUrl.TrimEnd("/")
        agent_token = $AgentToken
        version = $Version
    }
    $profile | ConvertTo-Json | Set-Content -LiteralPath "build\bootstrap-config.json" -Encoding UTF8

    if (-not $SkipTests) {
        & $Python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "Tests failed; Agent installer build stopped." }
    }
    & $Python -m PyInstaller --noconfirm --clean HosMonitorAgentUpdater.spec
    if ($LASTEXITCODE -ne 0) { throw "Agent Updater EXE build failed." }
    & $Python -m PyInstaller --noconfirm --clean HosMonitorAgentSetup.spec
    if ($LASTEXITCODE -ne 0) { throw "Agent Setup EXE build failed." }

    $versioned = "dist\HosMonitorAgentSetup-$Version.exe"
    Copy-Item -LiteralPath "dist\HosMonitorAgentSetup.exe" -Destination $versioned -Force
    $hash = (Get-FileHash -LiteralPath $versioned -Algorithm SHA256).Hash
    Write-Host "Built one-click installer: $project\$versioned"
    Write-Host "Server: $($ServerUrl.TrimEnd('/'))"
    Write-Host "SHA-256: $hash"
    Write-Host "Double-clicking this EXE installs or upgrades the Agent; no client-side configuration is required."
} finally {
    # The generated profile contains the shared Agent token and must not remain in build output.
    if (Test-Path -LiteralPath "build\bootstrap-config.json") {
        Remove-Item -LiteralPath "build\bootstrap-config.json" -Force
    }
    Pop-Location
}

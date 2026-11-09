[CmdletBinding()]
param(
    [string]$ConfigPath = "$env:ProgramData\HosMonitor\agent-config.json",
    [switch]$Once,
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"
$script:SelfTestMode = [bool]$SelfTest
$versionPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "VERSION"
$AgentVersion = if (Test-Path -LiteralPath $versionPath) {
    (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8).Trim()
} else {
    "0.1.0"
}
$DataDirectory = Split-Path -Parent $ConfigPath
$StatePath = Join-Path $DataDirectory "agent-state.json"
$LogPath = Join-Path $DataDirectory "agent.log"

function Write-AgentLog {
    param([string]$Message, [string]$Level = "INFO")
    if ($script:SelfTestMode) { return }
    if (-not (Test-Path -LiteralPath $DataDirectory)) { New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null }
    $line = "{0} [{1}] {2}" -f (Get-Date).ToString("s"), $Level, $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 2MB) {
        Move-Item -LiteralPath $LogPath -Destination "$LogPath.1" -Force
    }
}

function ConvertTo-AgentString {
    param([object]$Value, [int]$MaxLength)
    if ($null -eq $Value) { return "" }
    $text = ([string]$Value).Trim()
    if ($MaxLength -gt 0 -and $text.Length -gt $MaxLength) {
        return $text.Substring(0, $MaxLength)
    }
    return $text
}

function Read-JsonFile {
    param([string]$Path, [object]$Default)
    if (-not (Test-Path -LiteralPath $Path)) { return $Default }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Save-AgentState {
    param([object]$State)
    $State | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $StatePath -Encoding UTF8
}

function Get-OrCreateState {
    $state = Read-JsonFile -Path $StatePath -Default $null
    if ($null -eq $state) {
        $state = [pscustomobject]@{
            machine_id = [guid]::NewGuid().ToString()
            last_inventory_at = ""
            last_daily_date = ""
            last_boot_marker = ""
        }
        Save-AgentState $state
    }
    return $state
}

function Ensure-StateProperty {
    param([object]$State, [string]$Name, [object]$Value)
    if ($null -eq $State.PSObject.Properties[$Name]) {
        $State | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Invoke-AgentApi {
    param([string]$Path, [object]$Body, [object]$Config)
    $base = $Config.server_url.TrimEnd("/")
    $headers = @{ "X-Agent-Token" = [string]$Config.agent_token }
    $json = $Body | ConvertTo-Json -Depth 12 -Compress
    try {
        return Invoke-RestMethod -Uri "$base$Path" -Method Post -Headers $headers -Body $json -ContentType "application/json; charset=utf-8" -TimeoutSec 30
    } catch {
        $status = ""
        if ($null -ne $_.Exception.Response) {
            try { $status = " HTTP $([int]$_.Exception.Response.StatusCode)" } catch { $status = "" }
        }
        $detail = ConvertTo-AgentString -Value $_.ErrorDetails.Message -MaxLength 500
        if ([string]::IsNullOrWhiteSpace($detail)) {
            $detail = ConvertTo-AgentString -Value $_.Exception.Message -MaxLength 500
        }
        throw ("Agent API {0} failed{1}: {2}" -f $Path, $status, $detail)
    }
}

function Sync-AgentUpdateStatus {
    param([object]$State)
    $statusPath = Join-Path $DataDirectory "agent-updates\status.json"
    $status = Read-JsonFile -Path $statusPath -Default $null
    if ($null -eq $status) { return }
    $releaseId = 0
    if ([int]::TryParse([string]$status.release_id, [ref]$releaseId) -and $releaseId -gt 0) {
        $State.agent_update_release_id = $releaseId
        $State.agent_update_status = [string]$status.status
        $State.agent_update_error = [string]$status.error
        Save-AgentState $State
    }
}

function Queue-AgentUpdate {
    param([object]$Directive, [object]$Config, [object]$State)
    if ($null -eq $Directive -or -not [bool]$Directive.enabled) { return }
    $releaseId = [int]$Directive.release_id
    $version = [string]$Directive.version
    $downloadUrl = [string]$Directive.download_url
    if ($releaseId -lt 1 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid Agent update directive" }
    if ($downloadUrl -notmatch '^/agent/v1/update/\d+$') { throw "Invalid Agent update URL" }
    if ($version -eq $AgentVersion) { return }
    $updateDirectory = Join-Path $DataDirectory "agent-updates"
    New-Item -ItemType Directory -Path $updateDirectory -Force | Out-Null
    $pendingPath = Join-Path $updateDirectory "pending.json"
    $existing = Read-JsonFile -Path $pendingPath -Default $null
    if ($null -ne $existing -and [int]$existing.release_id -eq $releaseId) { return }
    $bundlePath = Join-Path $updateDirectory "release-$releaseId.hmagent"
    $temporary = "$bundlePath.download"
    $headers = @{ "X-Agent-Token" = [string]$Config.agent_token }
    $uri = "$($Config.server_url.TrimEnd('/'))$downloadUrl"
    Invoke-WebRequest -Uri $uri -Headers $headers -OutFile $temporary -UseBasicParsing -TimeoutSec 120
    $download = Get-Item -LiteralPath $temporary
    if ($download.Length -lt 1 -or $download.Length -gt 50MB -or $download.Length -ne [int64]$Directive.size_bytes) {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw "Agent update download size does not match"
    }
    $actualHash = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne ([string]$Directive.sha256).ToLowerInvariant()) {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw "Agent update SHA-256 does not match"
    }
    Move-Item -LiteralPath $temporary -Destination $bundlePath -Force
    $pending = [ordered]@{ release_id=$releaseId; version=$version; bundle_path=$bundlePath; queued_at=(Get-Date).ToUniversalTime().ToString("o") }
    $pendingTemporary = "$pendingPath.tmp"
    $pending | ConvertTo-Json | Set-Content -LiteralPath $pendingTemporary -Encoding UTF8
    Move-Item -LiteralPath $pendingTemporary -Destination $pendingPath -Force
    $State.agent_update_release_id = $releaseId
    $State.agent_update_status = "pending"
    $State.agent_update_error = ""
    Save-AgentState $State
    Write-AgentLog "Agent update queued release=$releaseId version=$version"
}

function Sync-Wallpaper {
    param([object]$Directive, [object]$Config, [object]$State)
    $wallpaperDirectory = Join-Path $DataDirectory "wallpaper"
    $policyPath = Join-Path $wallpaperDirectory "wallpaper-policy.json"
    New-Item -ItemType Directory -Path $wallpaperDirectory -Force | Out-Null
    if ($null -eq $Directive -or -not [bool]$Directive.enabled) {
        $policy = [ordered]@{ enabled=$false; revision=""; image_path=""; style="fill"; locked=$false }
        $policy | ConvertTo-Json | Set-Content -LiteralPath $policyPath -Encoding UTF8
        $State.wallpaper_revision = "disabled"
        $State.wallpaper_status = "disabled"
        $State.wallpaper_error = ""
        Save-AgentState $State
        return
    }

    $revision = [string]$Directive.revision
    if ($revision -notmatch '^[a-f0-9]{64}$') { throw "Invalid wallpaper revision" }
    $extension = [string]$Directive.file_extension
    if ($extension -notin @("jpg", "png")) { throw "Invalid wallpaper extension" }
    $imagePath = Join-Path $wallpaperDirectory "wallpaper.$extension"
    if ([string]$State.wallpaper_revision -ne $revision -or -not (Test-Path -LiteralPath $imagePath)) {
        $temporary = Join-Path $wallpaperDirectory "wallpaper.download"
        $headers = @{ "X-Agent-Token" = [string]$Config.agent_token }
        $uri = "$($Config.server_url.TrimEnd('/'))$([string]$Directive.download_url)"
        Invoke-WebRequest -Uri $uri -Headers $headers -OutFile $temporary -UseBasicParsing -TimeoutSec 60
        $download = Get-Item -LiteralPath $temporary
        if ($download.Length -lt 1 -or $download.Length -gt 10MB -or $download.Length -ne [int64]$Directive.size_bytes) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            throw "Wallpaper download size does not match"
        }
        $actualHash = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne ([string]$Directive.sha256).ToLowerInvariant()) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            throw "Wallpaper SHA-256 does not match"
        }
        Get-ChildItem -LiteralPath $wallpaperDirectory -Filter "wallpaper.*" -File |
            Where-Object { $_.FullName -ne $temporary } | Remove-Item -Force -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $temporary -Destination $imagePath -Force
    }
    $policy = [ordered]@{
        enabled = $true
        revision = $revision
        image_path = $imagePath
        style = "fill"
        locked = [bool]$Directive.locked
    }
    $policy | ConvertTo-Json | Set-Content -LiteralPath $policyPath -Encoding UTF8
    $State.wallpaper_revision = $revision
    $State.wallpaper_status = "downloaded"
    $State.wallpaper_error = ""
    Save-AgentState $State
    Write-AgentLog "Wallpaper downloaded revision=$revision"
}

function Test-UsableIPv4 {
    param([string]$Address)
    $parsed = $null
    if (-not [System.Net.IPAddress]::TryParse($Address, [ref]$parsed)) { return $false }
    if ($parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { return $false }
    $octets = $parsed.GetAddressBytes()
    if ($octets[0] -eq 127) { return $false }
    if ($octets[0] -eq 169 -and $octets[1] -eq 254) { return $false }
    if ($octets[0] -eq 0 -or $octets[0] -ge 224) { return $false }
    return $true
}

function Get-NetworkInventory {
    $excluded = "(?i)(virtual|vpn|tap|tunnel|loopback|hyper-v|vmware|virtualbox|bluetooth|wi-fi direct|teredo)"
    $result = @{}
    $adapters = Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
        Where-Object { $_.Status -eq "Up" -and $_.Name -notmatch $excluded -and $_.InterfaceDescription -notmatch $excluded }
    foreach ($adapter in $adapters) {
        $ipConfig = Get-NetIPConfiguration -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue
        $hasGateway = $null -ne $ipConfig.IPv4DefaultGateway
        foreach ($address in @($ipConfig.IPv4Address)) {
            if (Test-UsableIPv4 ([string]$address.IPAddress)) {
                $item = [pscustomobject]@{
                    adapter_name = ConvertTo-AgentString -Value $adapter.Name -MaxLength 255
                    mac_address = ConvertTo-AgentString -Value $adapter.MacAddress -MaxLength 64
                    ipv4 = ConvertTo-AgentString -Value $address.IPAddress -MaxLength 45
                    is_primary = [bool]$hasGateway
                }
                if (-not [string]::IsNullOrWhiteSpace($item.adapter_name)) {
                    $result["$($item.adapter_name)|$($item.mac_address)|$($item.ipv4)"] = $item
                }
            }
        }
    }
    return @($result.Values | Sort-Object @{Expression="is_primary";Descending=$true}, adapter_name, ipv4 | Select-Object -First 128)
}

function Get-InstalledSoftware {
    $items = @{}
    $uninstallPath = "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
        $baseKey = $null
        $root = $null
        try {
            $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, $view)
            $root = $baseKey.OpenSubKey($uninstallPath)
            if ($null -eq $root) { continue }
            foreach ($subName in $root.GetSubKeyNames()) {
                $subKey = $null
                try {
                    $subKey = $root.OpenSubKey($subName)
                    $name = ConvertTo-AgentString -Value $subKey.GetValue("DisplayName", "") -MaxLength 500
                    if ([string]::IsNullOrWhiteSpace($name)) { continue }
                    if ([int]$subKey.GetValue("SystemComponent", 0) -eq 1) { continue }
                    $version = ConvertTo-AgentString -Value $subKey.GetValue("DisplayVersion", "") -MaxLength 200
                    $publisher = ConvertTo-AgentString -Value $subKey.GetValue("Publisher", "") -MaxLength 500
                    $installDate = ConvertTo-AgentString -Value $subKey.GetValue("InstallDate", "") -MaxLength 32
                    $separator = [char]31
                    $key = "$name$separator$version$separator$publisher"
                    $items[$key] = [pscustomobject]@{ name=$name; version=$version; publisher=$publisher; install_date=$installDate }
                } finally { if ($null -ne $subKey) { $subKey.Dispose() } }
            }
        } catch {
            Write-AgentLog "Registry inventory view $view failed: $($_.Exception.Message)" "WARN"
        } finally {
            if ($null -ne $root) { $root.Dispose() }
            if ($null -ne $baseKey) { $baseKey.Dispose() }
        }
    }
    return @($items.Values | Sort-Object name, version | Select-Object -First 20000)
}

function Invoke-InventoryCollector {
    param(
        [string]$Name,
        [scriptblock]$Action,
        [int]$Attempts = 3,
        [switch]$RequireResult,
        [switch]$Optional
    )
    $attemptLimit = [math]::Max(1, [math]::Min(5, $Attempts))
    $lastError = ""
    for ($attempt = 1; $attempt -le $attemptLimit; $attempt++) {
        try {
            $result = & $Action
            if ($RequireResult -and @($result).Count -eq 0) { throw "$Name returned no data" }
            return $result
        } catch {
            $lastError = ConvertTo-AgentString -Value $_.Exception.Message -MaxLength 500
            Write-AgentLog "Inventory collector $Name attempt $attempt/$attemptLimit failed: $lastError" "WARN"
            if ($attempt -lt $attemptLimit) { Start-Sleep -Seconds 1 }
        }
    }
    if ($Optional) { return $null }
    throw "Inventory collector $Name failed after $attemptLimit attempts: $lastError"
}

function Get-FullInventory {
    param([object]$Config, [object]$State, [int[]]$CampaignIds)
    $os = Invoke-InventoryCollector -Name "OperatingSystem" -RequireResult -Action {
        Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop | Select-Object -First 1
    }
    $computer = Invoke-InventoryCollector -Name "ComputerSystem" -RequireResult -Action {
        Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop | Select-Object -First 1
    }
    $cpu = Invoke-InventoryCollector -Name "Processor" -RequireResult -Action {
        Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
    }
    $bios = Invoke-InventoryCollector -Name "BIOS" -Attempts 2 -Optional -Action {
        Get-CimInstance -ClassName Win32_BIOS -ErrorAction Stop | Select-Object -First 1
    }
    $systemProduct = Invoke-InventoryCollector -Name "SystemProduct" -Attempts 2 -Optional -Action {
        Get-CimInstance -ClassName Win32_ComputerSystemProduct -ErrorAction Stop | Select-Object -First 1
    }
    $baseboard = Invoke-InventoryCollector -Name "BaseBoard" -Attempts 2 -Optional -Action {
        Get-CimInstance -ClassName Win32_BaseBoard -ErrorAction Stop | Select-Object -First 1
    }
    $network = @(Get-NetworkInventory)
    $primary = @($network | Where-Object { $_.is_primary } | Select-Object -First 1)
    if ($primary.Count -eq 0) { $primary = @($network | Select-Object -First 1) }
    $rawDisks = @(Invoke-InventoryCollector -Name "LogicalDisk" -RequireResult -Action {
        Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction Stop
    })
    $disks = @($rawDisks | ForEach-Object {
        $deviceId = ConvertTo-AgentString -Value $_.DeviceID -MaxLength 32
        if (-not [string]::IsNullOrWhiteSpace($deviceId)) {
            $total = [math]::Max([int64]0, [int64]$_.Size)
            $free = [math]::Max([int64]0, [int64]$_.FreeSpace)
            if ($total -gt 0) { $free = [math]::Min($total, $free) }
            [pscustomobject]@{
                device_id=$deviceId
                label=ConvertTo-AgentString -Value $_.VolumeName -MaxLength 200
                total_bytes=$total
                free_bytes=$free
            }
        }
    } | Sort-Object device_id -Unique | Select-Object -First 128)
    $ramTotal = [int64]$computer.TotalPhysicalMemory
    $ramFree = [int64]$os.FreePhysicalMemory * 1024
    $osName = ConvertTo-AgentString -Value $os.Caption -MaxLength 255
    $cpuName = ConvertTo-AgentString -Value $cpu.Name -MaxLength 500
    $cpuCores = [math]::Min(1024, [math]::Max(0, [int]$computer.NumberOfLogicalProcessors))
    if ([string]::IsNullOrWhiteSpace($osName) -or [string]::IsNullOrWhiteSpace($cpuName) -or
        $cpuCores -lt 1 -or $ramTotal -lt 1 -or $disks.Count -lt 1) {
        throw "Critical inventory validation failed (OS, CPU, RAM or Disk is missing)"
    }
    $software = @(Get-InstalledSoftware)
    return [pscustomobject]@{
        machine_id = ConvertTo-AgentString -Value $State.machine_id -MaxLength 128
        hostname = ConvertTo-AgentString -Value ([Environment]::MachineName) -MaxLength 255
        asset_tag = ConvertTo-AgentString -Value $Config.asset_tag -MaxLength 100
        department = ConvertTo-AgentString -Value $Config.department -MaxLength 200
        agent_version = ConvertTo-AgentString -Value $AgentVersion -MaxLength 32
        collected_at = (Get-Date).ToUniversalTime().ToString("o")
        os_name = $osName
        os_version = ConvertTo-AgentString -Value $os.Version -MaxLength 255
        cpu_name = $cpuName
        cpu_cores = $cpuCores
        ram_total_bytes = $ramTotal
        # Force the Int64 overload. With an Int32 literal (0), Windows PowerShell
        # attempts to coerce RAM values above 2 GB to Int32 before calling Max.
        ram_used_bytes = [math]::Max([int64]0, [int64]($ramTotal - $ramFree))
        primary_ipv4 = if ($primary.Count -gt 0) { ConvertTo-AgentString -Value $primary[0].ipv4 -MaxLength 45 } else { "" }
        manufacturer = ConvertTo-AgentString -Value $computer.Manufacturer -MaxLength 255
        model = ConvertTo-AgentString -Value $computer.Model -MaxLength 255
        bios_serial = if ($null -ne $bios) { ConvertTo-AgentString -Value $bios.SerialNumber -MaxLength 255 } else { "" }
        system_uuid = if ($null -ne $systemProduct) { ConvertTo-AgentString -Value $systemProduct.UUID -MaxLength 128 } else { "" }
        baseboard_manufacturer = if ($null -ne $baseboard) { ConvertTo-AgentString -Value $baseboard.Manufacturer -MaxLength 255 } else { "" }
        baseboard_product = if ($null -ne $baseboard) { ConvertTo-AgentString -Value $baseboard.Product -MaxLength 255 } else { "" }
        baseboard_serial = if ($null -ne $baseboard) { ConvertTo-AgentString -Value $baseboard.SerialNumber -MaxLength 255 } else { "" }
        disks = $disks
        network = $network
        software = $software
        completed_campaign_ids = @($CampaignIds)
        observations = @()
    }
}

function Test-FirstInventoryDue {
    param([object]$State)
    return [string]::IsNullOrWhiteSpace([string]$State.last_inventory_at)
}

function Test-BootInventoryDue {
    param(
        [object]$State,
        [object]$Policy,
        [string]$BootMarker,
        [datetime]$NowUtc = ([datetime]::UtcNow)
    )
    if ([string]$State.last_boot_marker -eq $BootMarker) { return $false }
    $bootTime = [datetime]::MinValue
    $bootParsed = [datetime]::TryParse($BootMarker, [ref]$bootTime)
    if (-not $bootParsed) { return $true }
    return ($NowUtc.ToUniversalTime() - $bootTime.ToUniversalTime()).TotalSeconds -ge [int]$Policy.boot_delay_seconds
}

function Invoke-AgentSelfTest {
    $longValue = "x" * 600
    $bounded = ConvertTo-AgentString -Value $longValue -MaxLength 500
    if ($bounded.Length -ne 500) { throw "ConvertTo-AgentString did not enforce the limit" }
    $unicodeValue = ([char]0x0E17).ToString() + ([char]0x0E14) + ([char]0x0E2A) + ([char]0x0E2D) + ([char]0x0E1A)
    if ((ConvertTo-AgentString -Value "  $unicodeValue  " -MaxLength 20) -ne $unicodeValue) { throw "ConvertTo-AgentString did not trim Unicode text" }
    if (-not (Test-FirstInventoryDue -State ([pscustomobject]@{ last_inventory_at="" }))) { throw "First inventory must be due" }
    if (Test-FirstInventoryDue -State ([pscustomobject]@{ last_inventory_at="2026-10-04T00:00:00Z" })) { throw "Completed inventory must not be first-run due" }
    $testNow = [datetime]::Parse("2026-10-04T00:10:00Z").ToUniversalTime()
    $bootState = [pscustomobject]@{ last_boot_marker="previous" }
    $bootPolicy = [pscustomobject]@{ boot_delay_seconds=600 }
    if (Test-BootInventoryDue -State $bootState -Policy $bootPolicy -BootMarker "2026-10-04T00:05:00Z" -NowUtc $testNow) { throw "Boot inventory ignored its delay" }
    if (-not (Test-BootInventoryDue -State $bootState -Policy $bootPolicy -BootMarker "2026-10-04T00:00:00Z" -NowUtc $testNow)) { throw "Boot inventory was not due after its delay" }
    $script:SelfTestCollectorAttempts = 0
    $result = Invoke-InventoryCollector -Name "SelfTest" -Attempts 3 -RequireResult -Action {
        $script:SelfTestCollectorAttempts++
        if ($script:SelfTestCollectorAttempts -lt 3) { throw "transient" }
        return "ok"
    }
    if ($result -ne "ok" -or $script:SelfTestCollectorAttempts -ne 3) { throw "Collector retry self-test failed" }
    Write-Output "HosMonitor Agent self-test passed"
}

function Get-BootMarker {
    try { return (Get-CimInstance -ClassName Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString("o") }
    catch { return "unknown" }
}

function Test-DailyDue {
    param([object]$Policy, [object]$State)
    if (-not [bool]$Policy.daily_enabled) { return $false }
    $today = (Get-Date).ToString("yyyy-MM-dd")
    if ([string]$State.last_daily_date -eq $today) { return $false }
    $scheduled = [datetime]::ParseExact("$today $($Policy.daily_time)", "yyyy-MM-dd HH:mm", $null)
    return (Get-Date) -ge $scheduled
}

function Invoke-AgentCycle {
    param([object]$Config, [object]$State)
    Sync-AgentUpdateStatus -State $State
    $heartbeat = [pscustomobject]@{
        machine_id=ConvertTo-AgentString -Value $State.machine_id -MaxLength 128
        hostname=ConvertTo-AgentString -Value ([Environment]::MachineName) -MaxLength 255
        asset_tag=ConvertTo-AgentString -Value $Config.asset_tag -MaxLength 100
        department=ConvertTo-AgentString -Value $Config.department -MaxLength 200
        agent_version=ConvertTo-AgentString -Value $AgentVersion -MaxLength 32
        wallpaper_revision=[string]$State.wallpaper_revision; wallpaper_status=[string]$State.wallpaper_status
        wallpaper_error=[string]$State.wallpaper_error
        agent_update_release_id=if ([int]$State.agent_update_release_id -gt 0) { [int]$State.agent_update_release_id } else { $null }
        agent_update_status=[string]$State.agent_update_status
        agent_update_error=[string]$State.agent_update_error
    }
    $response = Invoke-AgentApi -Path "/agent/v1/heartbeat" -Body $heartbeat -Config $Config
    try { Queue-AgentUpdate -Directive $response.agent_update -Config $Config -State $State }
    catch {
        $State.agent_update_release_id = if ($null -ne $response.agent_update) { [int]$response.agent_update.release_id } else { 0 }
        $State.agent_update_status = "failed"
        $State.agent_update_error = $_.Exception.Message.Substring(0, [math]::Min(500, $_.Exception.Message.Length))
        Save-AgentState $State
        Write-AgentLog "Agent update queue failed: $($_.Exception.Message)" "ERROR"
    }
    try { Sync-Wallpaper -Directive $response.wallpaper -Config $Config -State $State }
    catch {
        $State.wallpaper_status = "failed"
        $State.wallpaper_error = $_.Exception.Message.Substring(0, [math]::Min(500, $_.Exception.Message.Length))
        Save-AgentState $State
        Write-AgentLog "Wallpaper sync failed: $($_.Exception.Message)" "ERROR"
    }
    $policy = $response.policy
    $campaignIds = @($response.collect_requests | ForEach-Object { [int]$_ })
    $bootMarker = Get-BootMarker
    $bootDue = Test-BootInventoryDue -State $State -Policy $policy -BootMarker $bootMarker
    $firstInventoryDue = Test-FirstInventoryDue -State $State
    $dailyDue = Test-DailyDue -Policy $policy -State $State
    if ($firstInventoryDue -or $bootDue -or $dailyDue -or $campaignIds.Count -gt 0) {
        $inventory = Get-FullInventory -Config $Config -State $State -CampaignIds $campaignIds
        Invoke-AgentApi -Path "/agent/v1/inventory" -Body $inventory -Config $Config | Out-Null
        $State.last_inventory_at = $inventory.collected_at
        if ($firstInventoryDue -or $bootDue) { $State.last_boot_marker = $bootMarker }
        if ($dailyDue) { $State.last_daily_date = (Get-Date).ToString("yyyy-MM-dd") }
        Save-AgentState $State
        Write-AgentLog "Inventory sent successfully; disks=$($inventory.disks.Count) network=$($inventory.network.Count) software=$($inventory.software.Count) campaigns=$($campaignIds -join ',')"
    }
    return [math]::Max(30, [int]$policy.heartbeat_seconds)
}

if ($SelfTest) {
    Invoke-AgentSelfTest
    exit 0
}

if (-not (Test-Path -LiteralPath $ConfigPath)) { throw "Agent config not found: $ConfigPath" }
$config = Read-JsonFile -Path $ConfigPath -Default $null
if ($null -eq $config -or [string]::IsNullOrWhiteSpace([string]$config.server_url) -or [string]::IsNullOrWhiteSpace([string]$config.agent_token)) {
    throw "agent-config.json must contain server_url and agent_token"
}
$state = Get-OrCreateState
Ensure-StateProperty -State $state -Name "wallpaper_revision" -Value ""
Ensure-StateProperty -State $state -Name "wallpaper_status" -Value ""
Ensure-StateProperty -State $state -Name "wallpaper_error" -Value ""
Ensure-StateProperty -State $state -Name "agent_update_release_id" -Value 0
Ensure-StateProperty -State $state -Name "agent_update_status" -Value ""
Ensure-StateProperty -State $state -Name "agent_update_error" -Value ""
Save-AgentState $state
Write-AgentLog "Agent $AgentVersion started for machine $($state.machine_id)"
do {
    $sleepSeconds = 120
    try { $sleepSeconds = Invoke-AgentCycle -Config $config -State $state }
    catch { Write-AgentLog $_.Exception.Message "ERROR" }
    if (-not $Once) { Start-Sleep -Seconds $sleepSeconds }
} while (-not $Once)

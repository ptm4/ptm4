<#
.SYNOPSIS
  Check common Windows registry persistence locations for new or changed entries.

.DESCRIPTION
  Enumerates 20+ autorun registry keys. On first run, saves a baseline.
  On subsequent runs, diffs against baseline and highlights new/changed entries.

.PARAMETER SaveBaseline
  Force re-save the baseline (overwrites existing)

.PARAMETER ReportDir
  Directory to write report JSON

.EXAMPLE
  .\registry-persist-checker.ps1               # auto-baseline on first run, then diff
  .\registry-persist-checker.ps1 -SaveBaseline # reset baseline
#>
param(
    [switch]$SaveBaseline,
    [string]$ReportDir = ""
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ReportDir) {
    $ReportDir = Join-Path $scriptDir "..\..\security-reports"
}
$null = New-Item -ItemType Directory -Force -Path $ReportDir

$reportPath   = Join-Path $ReportDir "registry-persist-latest.json"
$baselinePath = Join-Path $scriptDir "..\data\registry-persist-baseline.json"
$null = New-Item -ItemType Directory -Force -Path (Split-Path $baselinePath)

# Registry locations to monitor
$watchKeys = @(
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunServices",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunServicesOnce",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon",
    "HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon",
    "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options",
    "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\BootExecute",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
    "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppInit_DLLs",
    "HKLM:\SYSTEM\CurrentControlSet\Control\Lsa",
    "HKCU:\SOFTWARE\Classes\mscfile\shell\open\command",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run"
)

# Values in Winlogon key that are legitimate baselines (to reduce noise)
$knownWinlogonValues = @("Userinit", "Shell", "DefaultUserName", "AutoAdminLogon")

function Get-PersistenceSnapshot {
    $entries = @()
    foreach ($keyPath in $watchKeys) {
        if (-not (Test-Path $keyPath)) { continue }
        $key = Get-Item $keyPath -ErrorAction SilentlyContinue
        if (-not $key) { continue }

        $values = $key.GetValueNames()
        foreach ($valueName in $values) {
            if (-not $valueName) { continue }
            $data = $key.GetValue($valueName) -as [string]
            $entries += [PSCustomObject]@{
                Key   = $keyPath
                Name  = $valueName
                Data  = $data
            }
        }

        # For IFEO, check for Debugger sub-keys (common hijack technique)
        if ($keyPath -like "*Image File Execution*") {
            $subKeys = Get-ChildItem $keyPath -ErrorAction SilentlyContinue
            foreach ($sub in $subKeys) {
                $debugger = $sub.GetValue("Debugger")
                if ($debugger) {
                    $entries += [PSCustomObject]@{
                        Key  = "$keyPath\$($sub.PSChildName)"
                        Name = "Debugger"
                        Data = $debugger
                    }
                }
            }
        }
    }
    return $entries
}

function Format-Entry($e) { "$($e.Key)|$($e.Name)|$($e.Data)" }

Write-Host "Scanning persistence registry keys..." -ForegroundColor Cyan
$current = Get-PersistenceSnapshot
Write-Host "  $($current.Count) values found across $($watchKeys.Count) monitored keys"

# Auto-create baseline on first run
if (-not (Test-Path $baselinePath) -or $SaveBaseline) {
    $current | ConvertTo-Json -Depth 5 | Set-Content -Path $baselinePath -Encoding UTF8
    $action = if ($SaveBaseline) { "reset" } else { "created" }
    Write-Host "Baseline $action: $baselinePath" -ForegroundColor Green
    if (-not $SaveBaseline) {
        Write-Host "Run again to detect changes." -ForegroundColor Yellow
    }

    $report = @{
        tool     = "registry-persist-checker"
        run_at   = (Get-Date -Format "o")
        status   = "ok"
        summary  = "Baseline created with $($current.Count) entries. Run again to detect changes."
        findings = @()
        snapshot = ($current | ForEach-Object { @{ key=$_.Key; name=$_.Name; data=$_.Data } })
    }
    $report | ConvertTo-Json -Depth 10 | Set-Content -Path $reportPath -Encoding UTF8
    return
}

$baseline = Get-Content $baselinePath | ConvertFrom-Json
$baselineSet  = @{}
$currentSet   = @{}

foreach ($e in $baseline) { $baselineSet[(Format-Entry $e)] = $e }
foreach ($e in $current)  { $currentSet[(Format-Entry $e)]  = $e }

$newEntries     = $current  | Where-Object { -not $baselineSet.ContainsKey((Format-Entry $_)) }
$removedEntries = $baseline | Where-Object { -not $currentSet.ContainsKey((Format-Entry $_)) }

$findings = @()

foreach ($e in $newEntries) {
    $severity = "high"
    # Lower severity for well-known Winlogon values with expected content
    if ($e.Key -like "*Winlogon*" -and $e.Name -in $knownWinlogonValues) {
        $severity = "warn"
    }
    $findings += @{
        severity = $severity
        message  = "NEW persistence entry: [$($e.Name)] in $($e.Key)"
        detail   = @{ change = "added"; key = $e.Key; name = $e.Name; data = $e.Data }
    }
    Write-Host "  [NEW] $($e.Key) | $($e.Name) = $($e.Data)" -ForegroundColor Red
}

foreach ($e in $removedEntries) {
    $findings += @{
        severity = "info"
        message  = "REMOVED persistence entry: [$($e.Name)] from $($e.Key)"
        detail   = @{ change = "removed"; key = $e.Key; name = $e.Name; data = $e.Data }
    }
    Write-Host "  [REMOVED] $($e.Key) | $($e.Name)" -ForegroundColor Gray
}

$status = if (($findings | Where-Object { $_.severity -eq "high" }).Count -gt 0) { "critical" }
          elseif ($findings.Count -gt 0) { "warn" }
          else { "ok" }

$summary = if ($findings.Count -eq 0) {
    "$($current.Count) entries checked, no changes since baseline"
} else {
    "$($newEntries.Count) NEW, $($removedEntries.Count) REMOVED persistence entries"
}

Write-Host "`n$summary" -ForegroundColor (if ($status -eq "ok") { "Green" } elseif ($status -eq "warn") { "Yellow" } else { "Red" })

$report = @{
    tool     = "registry-persist-checker"
    run_at   = (Get-Date -Format "o")
    status   = $status
    summary  = $summary
    findings = $findings
    snapshot = ($current | ForEach-Object { @{ key=$_.Key; name=$_.Name; data=$_.Data } })
}
$report | ConvertTo-Json -Depth 10 | Set-Content -Path $reportPath -Encoding UTF8
Write-Host "Report: $reportPath" -ForegroundColor Green

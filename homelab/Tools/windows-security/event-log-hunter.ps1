<#
.SYNOPSIS
  Hunt suspicious Windows Event Log entries across Security, System, and Application logs.

.DESCRIPTION
  Queries high-signal event IDs known to indicate attacks or suspicious activity.
  Groups hits by hour, highlights spikes, and writes a JSON report.

.PARAMETER Hours
  Lookback window in hours (default: 24)

.PARAMETER ReportDir
  Directory to write report JSON (default: ..\..\security-reports relative to this script)

.EXAMPLE
  .\event-log-hunter.ps1
  .\event-log-hunter.ps1 -Hours 48
#>
param(
    [int]$Hours = 24,
    [string]$ReportDir = ""
)

$ErrorActionPreference = "SilentlyContinue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ReportDir) {
    $ReportDir = Join-Path $scriptDir "..\..\security-reports"
}
$null = New-Item -ItemType Directory -Force -Path $ReportDir

$reportPath = Join-Path $ReportDir "event-log-latest.json"
$since = (Get-Date).AddHours(-$Hours)

# High-signal event IDs with descriptions
$watchIds = @{
    4625 = "Failed logon attempt"
    4648 = "Logon using explicit credentials"
    4720 = "User account created"
    4726 = "User account deleted"
    4732 = "User added to privileged group"
    4756 = "Member added to security-enabled universal group"
    4768 = "Kerberos TGT requested (failed)"
    4771 = "Kerberos pre-auth failed"
    1102 = "Audit log cleared"
    4698 = "Scheduled task created"
    4702 = "Scheduled task updated"
    7045 = "New service installed"
    7036 = "Service state changed"
    4688 = "Process created (if auditing enabled)"
}

$findings = @()
$allEvents = @()

Write-Host "Querying event logs (last ${Hours}h)..." -ForegroundColor Cyan

foreach ($logName in @("Security", "System", "Application")) {
    foreach ($id in $watchIds.Keys) {
        $events = Get-WinEvent -FilterHashtable @{
            LogName   = $logName
            Id        = $id
            StartTime = $since
        } -ErrorAction SilentlyContinue

        foreach ($ev in $events) {
            $allEvents += [PSCustomObject]@{
                Log       = $logName
                EventId   = $id
                Meaning   = $watchIds[$id]
                TimeStamp = $ev.TimeCreated.ToString("o")
                Hour      = $ev.TimeCreated.ToString("yyyy-MM-dd HH:00")
                Message   = ($ev.Message -replace "`r`n", " " -replace "`n", " ")[0..200] -join ""
                Level     = $ev.LevelDisplayName
            }
        }
    }
}

# Group by hour to detect spikes
$byHour = $allEvents | Group-Object Hour | Sort-Object Name

Write-Host "`nEvent summary by hour:" -ForegroundColor Yellow
foreach ($group in $byHour) {
    $spike = if ($group.Count -ge 10) { " *** SPIKE ***" } else { "" }
    Write-Host ("  {0,-20} {1,4} events{2}" -f $group.Name, $group.Count, $spike) -ForegroundColor (if ($spike) { "Red" } else { "Gray" })
}

# Build findings list
$eventGroups = $allEvents | Group-Object EventId | Sort-Object @{e={$_.Count}} -Descending
foreach ($group in $eventGroups) {
    $id = [int]$group.Name
    $meaning = $watchIds[$id]
    $severity = switch ($id) {
        1102    { "critical" }  # Log cleared
        { $_ -in 4720,4726,4732,4756,7045 } { "high" }
        { $_ -in 4625,4648,4768,4771,4698,4702 } { "warn" }
        default { "info" }
    }
    $findings += @{
        severity = $severity
        message  = "$($group.Count)x EventID $id — $meaning"
        detail   = @{
            event_id   = $id
            count      = $group.Count
            meaning    = $meaning
            first_seen = ($group.Group | Sort-Object TimeStamp | Select-Object -First 1).TimeStamp
            last_seen  = ($group.Group | Sort-Object TimeStamp | Select-Object -Last 1).TimeStamp
            samples    = ($group.Group | Select-Object -First 3 | ForEach-Object { $_.Message })
        }
    }
}

$criticalCount = ($findings | Where-Object { $_.severity -eq "critical" }).Count
$highCount     = ($findings | Where-Object { $_.severity -eq "high" }).Count
$warnCount     = ($findings | Where-Object { $_.severity -eq "warn" }).Count

$status = if ($criticalCount -gt 0) { "critical" }
          elseif ($highCount -gt 0)  { "warn" }
          elseif ($warnCount -gt 0)  { "warn" }
          else                       { "ok" }

$summary = if ($allEvents.Count -eq 0) {
    "No suspicious events in last ${Hours}h"
} else {
    "$($allEvents.Count) events: $criticalCount critical, $highCount high, $warnCount warn"
}

$report = @{
    tool     = "event-log-hunter"
    run_at   = (Get-Date -Format "o")
    status   = $status
    summary  = $summary
    hours    = $Hours
    findings = $findings
    by_hour  = ($byHour | ForEach-Object { @{ hour = $_.Name; count = $_.Count } })
}

$report | ConvertTo-Json -Depth 10 | Set-Content -Path $reportPath -Encoding UTF8
Write-Host "`nReport: $reportPath" -ForegroundColor Green
Write-Host "Status: $status | $summary"

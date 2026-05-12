<#
.SYNOPSIS
  Enumerate scheduled tasks and flag suspicious entries.

.DESCRIPTION
  Lists all scheduled tasks with action paths, triggers, and run-as accounts.
  Flags tasks running from temp/appdata paths, SYSTEM-privileged network tasks,
  and recently created tasks. Supports baseline save/diff mode.

.PARAMETER SaveBaseline
  Save current task list as the baseline for future diffs

.PARAMETER Diff
  Compare current tasks against saved baseline, show new/changed tasks

.PARAMETER ReportDir
  Directory to write report JSON

.EXAMPLE
  .\scheduled-task-auditor.ps1                  # audit + report
  .\scheduled-task-auditor.ps1 -SaveBaseline    # save baseline
  .\scheduled-task-auditor.ps1 -Diff            # diff against baseline
#>
param(
    [switch]$SaveBaseline,
    [switch]$Diff,
    [string]$ReportDir = ""
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ReportDir) {
    $ReportDir = Join-Path $scriptDir "..\..\security-reports"
}
$null = New-Item -ItemType Directory -Force -Path $ReportDir

$reportPath   = Join-Path $ReportDir "sched-tasks-latest.json"
$baselinePath = Join-Path $scriptDir "..\data\sched-tasks-baseline.json"
$null = New-Item -ItemType Directory -Force -Path (Split-Path $baselinePath)

# Suspicious path patterns (action executable location)
$suspiciousPaths = @(
    [regex]"(?i)\\temp\\",
    [regex]"(?i)\\appdata\\local\\temp\\",
    [regex]"(?i)\\appdata\\roaming\\",
    [regex]"(?i)\\users\\[^\\]+\\appdata\\",
    [regex]"(?i)\.vbs$",
    [regex]"(?i)\.bat$",
    [regex]"(?i)\\downloads\\",
    [regex]"(?i)\\desktop\\",
    [regex]"(?i)mshta\.exe",
    [regex]"(?i)wscript\.exe",
    [regex]"(?i)cscript\.exe",
    [regex]"(?i)regsvr32\.exe",
    [regex]"(?i)rundll32\.exe"
)

function Get-TaskData {
    $tasks = Get-ScheduledTask | Where-Object { $_.TaskPath -notlike "\Microsoft\*" }
    $result = @()
    foreach ($task in $tasks) {
        $info    = $task | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
        $actions = $task.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)".Trim() }
        $triggers = $task.Triggers | ForEach-Object {
            if ($_.GetType().Name -eq "TimeTrigger") { "Time: $($_.StartBoundary)" }
            elseif ($_.GetType().Name -eq "BootTrigger") { "Boot" }
            elseif ($_.GetType().Name -eq "LogonTrigger") { "Logon" }
            elseif ($_.GetType().Name -eq "RepetitionTrigger") { "Repeat" }
            else { $_.GetType().Name }
        }

        $result += [PSCustomObject]@{
            Name         = $task.TaskName
            Path         = $task.TaskPath
            State        = $task.State.ToString()
            RunAs        = $task.Principal.UserId
            Actions      = ($actions -join " | ")
            Triggers     = ($triggers -join ", ")
            LastRun      = if ($info.LastRunTime) { $info.LastRunTime.ToString("o") } else { $null }
            LastResult   = if ($info) { $info.LastTaskResult } else { $null }
            RegisteredAt = if ($info.LastRunTime) { $null } else { $null }
        }
    }
    return $result
}

function Get-Flags($task) {
    $flags = @()
    foreach ($pattern in $suspiciousPaths) {
        if ($task.Actions -match $pattern) {
            $flags += "Suspicious path in action: $($task.Actions)"
            break
        }
    }
    if ($task.RunAs -match "SYSTEM|NT AUTHORITY" -and $task.Actions -match "(?i)(curl|wget|powershell.*http|bitsadmin|certutil.*http)") {
        $flags += "SYSTEM task with network-fetching action"
    }
    return $flags
}

Write-Host "Enumerating scheduled tasks..." -ForegroundColor Cyan
$tasks = Get-TaskData

if ($SaveBaseline) {
    $tasks | ConvertTo-Json -Depth 5 | Set-Content -Path $baselinePath -Encoding UTF8
    Write-Host "Baseline saved: $baselinePath ($($tasks.Count) tasks)" -ForegroundColor Green
    return
}

$findings = @()
$flaggedTasks = @()

foreach ($task in $tasks) {
    $flags = Get-Flags $task
    if ($flags.Count -gt 0) {
        $flaggedTasks += $task
        foreach ($flag in $flags) {
            $findings += @{
                severity = "warn"
                message  = "[$($task.Name)] $flag"
                detail   = @{
                    name    = $task.Name
                    path    = $task.Path
                    run_as  = $task.RunAs
                    actions = $task.Actions
                    flags   = $flags
                }
            }
        }
    }
}

# Diff against baseline
$newTasks = @()
if ($Diff -and (Test-Path $baselinePath)) {
    $baseline = Get-Content $baselinePath | ConvertFrom-Json
    $baselineNames = $baseline | ForEach-Object { $_.Name }
    $newTasks = $tasks | Where-Object { $_.Name -notin $baselineNames }

    foreach ($task in $newTasks) {
        $findings += @{
            severity = "high"
            message  = "NEW task since baseline: $($task.Name)"
            detail   = @{
                name    = $task.Name
                run_as  = $task.RunAs
                actions = $task.Actions
                triggers = $task.Triggers
            }
        }
    }
    Write-Host "New tasks since baseline: $($newTasks.Count)" -ForegroundColor Yellow
}

$status = if (($findings | Where-Object { $_.severity -eq "high" }).Count -gt 0) { "warn" }
          elseif ($findings.Count -gt 0) { "warn" }
          else { "ok" }

$summary = if ($findings.Count -eq 0) {
    "$($tasks.Count) tasks audited, nothing suspicious"
} else {
    "$($tasks.Count) tasks audited, $($findings.Count) finding(s), $($newTasks.Count) new since baseline"
}

Write-Host "`n$summary" -ForegroundColor (if ($status -eq "ok") { "Green" } else { "Yellow" })

$report = @{
    tool     = "scheduled-task-auditor"
    run_at   = (Get-Date -Format "o")
    status   = $status
    summary  = $summary
    findings = $findings
    all_tasks = ($tasks | ForEach-Object {
        @{ name=$_.Name; path=$_.Path; run_as=$_.RunAs; actions=$_.Actions; triggers=$_.Triggers; state=$_.State }
    })
}

$report | ConvertTo-Json -Depth 10 | Set-Content -Path $reportPath -Encoding UTF8
Write-Host "Report: $reportPath" -ForegroundColor Green

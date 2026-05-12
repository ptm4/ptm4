<#
.SYNOPSIS
  Register all homelab security tool scheduled tasks in Windows Task Scheduler.

.DESCRIPTION
  Creates Task Scheduler entries for all Windows-side homelab security tools.
  Run once as Administrator to set up. Safe to re-run — existing tasks are updated.

  Tools registered:
    HL-ArpWatch         - ARP spoof detection (every 5 min)
    HL-RogueAP          - Rogue AP detection  (every 10 min)
    HL-EventLog         - Event log hunting   (daily 08:00)
    HL-SchedTasks       - Task auditor        (daily 08:05)
    HL-RegistryPersist  - Registry audit      (daily 08:10)
    HL-HttpHeaders      - HTTP header check   (daily 09:00)
    HL-GeoIP            - GeoIP log mapper    (daily 09:30)

.EXAMPLE
  # Run as Administrator:
  .\setup-windows-tasks.ps1

  # To remove all tasks:
  .\setup-windows-tasks.ps1 -Remove
#>
param([switch]$Remove)

#Requires -RunAsAdministrator

$toolsRoot   = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
$reportsRoot = "\\rpi.lan\ptm\security-reports"
$python      = (Get-Command python -ErrorAction SilentlyContinue)?.Source ?? "python"
$pwsh        = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source ?? "powershell"

if (-not (Test-Path $toolsRoot)) {
    Write-Error "Tools root not found: $toolsRoot"
    exit 1
}

$tasks = @(
    @{
        Name        = "HL-ArpWatch"
        Description = "Homelab: ARP spoof detection"
        Executable  = $python
        Arguments   = "`"$toolsRoot\network\arp-watch.py`" --report"
        Trigger     = "Repeat-5min"
    },
    @{
        Name        = "HL-RogueAP"
        Description = "Homelab: Rogue / evil-twin AP detection"
        Executable  = $python
        Arguments   = "`"$toolsRoot\network\rogue-ap-hunter.py`""
        Trigger     = "Repeat-10min"
    },
    @{
        Name        = "HL-EventLog"
        Description = "Homelab: Windows event log threat hunting"
        Executable  = $pwsh
        Arguments   = "-NonInteractive -File `"$toolsRoot\windows-security\event-log-hunter.ps1`""
        Trigger     = "Daily-0800"
    },
    @{
        Name        = "HL-SchedTasks"
        Description = "Homelab: Scheduled task auditor"
        Executable  = $pwsh
        Arguments   = "-NonInteractive -File `"$toolsRoot\windows-security\scheduled-task-auditor.ps1`" -Diff"
        Trigger     = "Daily-0805"
    },
    @{
        Name        = "HL-RegistryPersist"
        Description = "Homelab: Registry persistence checker"
        Executable  = $pwsh
        Arguments   = "-NonInteractive -File `"$toolsRoot\windows-security\registry-persist-checker.ps1`""
        Trigger     = "Daily-0810"
    },
    @{
        Name        = "HL-HttpHeaders"
        Description = "Homelab: HTTP security header checker"
        Executable  = $python
        Arguments   = "`"$toolsRoot\windows-security\http-security-header-checker.py`""
        Trigger     = "Daily-0900"
    },
    @{
        Name        = "HL-GeoIP"
        Description = "Homelab: GeoIP Nginx log mapper"
        Executable  = $python
        Arguments   = "`"$toolsRoot\threat-intel\geoip-log-mapper.py`""
        Trigger     = "Daily-0930"
    },
    @{
        Name        = "HL-LinkedInJobs"
        Description = "Homelab: LinkedIn job listings watcher"
        Executable  = $python
        Arguments   = "`"$toolsRoot\selenium\linkedin-job-watcher.py`""
        Trigger     = "Daily-1200"
    }
)

function Make-Trigger($type) {
    switch ($type) {
        "Repeat-5min"  {
            $t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)
            return $t
        }
        "Repeat-10min" {
            $t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration ([TimeSpan]::MaxValue)
            return $t
        }
        "Daily-0800"   { return New-ScheduledTaskTrigger -Daily -At "08:00" }
        "Daily-0805"   { return New-ScheduledTaskTrigger -Daily -At "08:05" }
        "Daily-0810"   { return New-ScheduledTaskTrigger -Daily -At "08:10" }
        "Daily-0900"   { return New-ScheduledTaskTrigger -Daily -At "09:00" }
        "Daily-0930"   { return New-ScheduledTaskTrigger -Daily -At "09:30" }
        "Daily-1200"   { return New-ScheduledTaskTrigger -Daily -At "12:00" }
    }
}

$taskFolder = "\Homelab"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

foreach ($task in $tasks) {
    if ($Remove) {
        Unregister-ScheduledTask -TaskName $task.Name -TaskPath $taskFolder -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed: $($task.Name)" -ForegroundColor Yellow
        continue
    }

    $action  = New-ScheduledTaskAction -Execute $task.Executable -Argument $task.Arguments
    $trigger = Make-Trigger $task.Trigger
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

    $params = @{
        TaskName    = $task.Name
        TaskPath    = $taskFolder
        Description = $task.Description
        Action      = $action
        Trigger     = $trigger
        Settings    = $settings
        Principal   = $principal
        Force       = $true
    }

    Register-ScheduledTask @params | Out-Null
    Write-Host "Registered: $($task.Name) [$($task.Trigger)]" -ForegroundColor Green
}

if (-not $Remove) {
    Write-Host "`nAll tasks registered under Task Scheduler > $taskFolder"
    Write-Host "Reports will be written to: $reportsRoot"
    Write-Host "`nTIP: Run baseline save for new installs:"
    Write-Host "  pwsh -File `"$toolsRoot\windows-security\scheduled-task-auditor.ps1`" -SaveBaseline"
    Write-Host "  pwsh -File `"$toolsRoot\windows-security\registry-persist-checker.ps1`" -SaveBaseline"
}

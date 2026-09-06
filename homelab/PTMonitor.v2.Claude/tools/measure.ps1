<#
.SYNOPSIS
  Measure PTMonitor 2 footprint: private bytes, CPU share of one core over N minutes,
  own-PID GPU engine use, threads, handles, child processes, and the dwm.exe CPU delta.
.EXAMPLE
  pwsh tools/measure.ps1 -Minutes 5
#>
param([string]$Name = 'ptmonitor2', [int]$Minutes = 5)

$p = Get-Process $Name -ErrorAction Stop | Select-Object -First 1
$dwm = Get-Process dwm -ErrorAction SilentlyContinue | Select-Object -First 1
$t0 = $p.TotalProcessorTime
$m0 = $p.PrivateMemorySize64
$d0 = if ($dwm) { $dwm.TotalProcessorTime } else { [timespan]::Zero }
$sw = [Diagnostics.Stopwatch]::StartNew()
Start-Sleep -Seconds ($Minutes * 60)
$p.Refresh()
if ($dwm) { $dwm.Refresh() }

$cpuOneCore = (($p.TotalProcessorTime - $t0).TotalMilliseconds / $sw.ElapsedMilliseconds) * 100
$dwmOneCore = if ($dwm) { (($dwm.TotalProcessorTime - $d0).TotalMilliseconds / $sw.ElapsedMilliseconds) * 100 } else { -1 }
$gpu = try {
  ((Get-Counter "\GPU Engine(pid_$($p.Id)_*)\Utilization Percentage" -ErrorAction Stop).CounterSamples |
    Measure-Object CookedValue -Sum).Sum
} catch { 0 }
$children = (Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" | Measure-Object).Count

[pscustomobject]@{
  Process          = $Name
  Minutes          = $Minutes
  PrivateMB_start  = [math]::Round($m0 / 1MB, 1)
  PrivateMB_end    = [math]::Round($p.PrivateMemorySize64 / 1MB, 1)
  WorkingSetMB     = [math]::Round($p.WorkingSet64 / 1MB, 1)
  CPU_pct_one_core = [math]::Round($cpuOneCore, 3)
  DWM_pct_one_core = [math]::Round($dwmOneCore, 3)
  GPU_pct_now      = [math]::Round($gpu, 2)
  Threads          = $p.Threads.Count
  Handles          = $p.HandleCount
  Children         = $children
} | Format-List

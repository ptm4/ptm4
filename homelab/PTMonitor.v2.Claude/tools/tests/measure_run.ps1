param(
  [string]$Exe,
  [string]$Out,
  [int]$Seconds = 90,
  [int]$HideAfter = 0,      # seconds; 0 = never hide
  [string]$Pos = "2600,60", # PTM2_POS (physical px)
  [int]$WarmupSeconds = 15,
  [string]$PreCmds = ""      # comma-separated menu command ids posted before measuring (e.g. "42" = game mode off)
)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class M {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowW(string cls, string name);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
[void][M]::SetProcessDPIAware()
$env:PTM2_POS = $Pos
if ($HideAfter -gt 0) { $env:PTM2_HIDE_AFTER = "$HideAfter" } else { Remove-Item Env:PTM2_HIDE_AFTER -ErrorAction SilentlyContinue }
$p = Start-Process $Exe -PassThru
Start-Sleep -Seconds $WarmupSeconds
$h = [M]::FindWindowW("PTMonitor2.Main", "PTMonitor 2")
if ($h -eq [IntPtr]::Zero) { Write-Output "window not found"; exit 1 }
if ($PreCmds -ne "") { foreach ($c in $PreCmds.Split(",")) { [void][M]::PostMessageW($h, 0x8004, [IntPtr]([int]$c.Trim()), [IntPtr]::Zero); Start-Sleep -Milliseconds 800 }; Start-Sleep -Seconds 3 }
$visible = [M]::IsWindowVisible($h)
Write-Output ("visible after warmup: {0}" -f $visible)
if ($visible) {
  $r = New-Object M+RECT; [void][M]::GetWindowRect($h, [ref]$r); $m = 16
  $bmp = New-Object System.Drawing.Bitmap(($r.R-$r.L+2*$m), ($r.B-$r.T+2*$m))
  $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($r.L-$m, $r.T-$m, 0, 0, $bmp.Size); $g.Dispose()
  $bmp.Save("$Out.png")
  $big = New-Object System.Drawing.Bitmap(($bmp.Width*2), ($bmp.Height*2)); $g2 = [System.Drawing.Graphics]::FromImage($big); $g2.InterpolationMode='NearestNeighbor'; $g2.DrawImage($bmp,0,0,$big.Width,$big.Height); $g2.Dispose(); $big.Save("$Out@2x.png")
  Write-Output ("captured {0},{1} {2}x{3}" -f $r.L, $r.T, ($r.R-$r.L), ($r.B-$r.T))
  # Reference values at capture time
  $cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples[0].CookedValue
  $os = Get-CimInstance Win32_OperatingSystem
  $ramUsedGB = ($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB
  $gpu = (& nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw --format=csv,noheader 2>$null)
  Write-Output ("reference: cpu {0:N0}%  ram used {1:N1} GB  gpu [{2}]" -f $cpu, $ramUsedGB, $gpu)
}
$p.Refresh()
$t0 = $p.TotalProcessorTime; $m0 = $p.PrivateMemorySize64; $sw = [Diagnostics.Stopwatch]::StartNew()
Start-Sleep -Seconds $Seconds
$p.Refresh()
$cpuPct = (($p.TotalProcessorTime - $t0).TotalMilliseconds / $sw.ElapsedMilliseconds) * 100
$children = (Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" | Measure-Object).Count
[pscustomobject]@{
  Mode = if ($HideAfter -gt 0) { "hidden after ${HideAfter}s" } else { "visible" }
  Seconds = $Seconds
  PrivateMB_start = [math]::Round($m0 / 1MB, 1)
  PrivateMB_end = [math]::Round($p.PrivateMemorySize64 / 1MB, 1)
  WorkingSetMB = [math]::Round($p.WorkingSet64 / 1MB, 1)
  CPU_pct_one_core = [math]::Round($cpuPct, 3)
  Threads = $p.Threads.Count
  Handles = $p.HandleCount
  Children = $children
  VisibleAtEnd = [M]::IsWindowVisible($h)
} | Format-List
[void][M]::PostMessageW($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
$p.WaitForExit(8000) | Out-Null
Write-Output ("exited: {0} code {1}" -f $p.HasExited, $p.ExitCode)

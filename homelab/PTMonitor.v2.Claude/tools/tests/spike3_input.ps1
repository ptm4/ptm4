param([string]$Exe, [string]$Out)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W3 {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowW(string cls, string name);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, int dx, int dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern long GetWindowLongPtrW(IntPtr h, int idx);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint cmd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
[void][W3]::SetProcessDPIAware()
. (Join-Path $PSScriptRoot "input.ps1")
function Rect() { $r = New-Object W3+RECT; [void][W3]::GetWindowRect($script:h, [ref]$r); $r }
function Capture([string]$suffix) {
  $r = Rect; $m = 24
  $bmp = New-Object System.Drawing.Bitmap(($r.R-$r.L+2*$m), ($r.B-$r.T+2*$m))
  $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($r.L-$m, $r.T-$m, 0, 0, $bmp.Size); $g.Dispose()
  $bmp.Save("$Out$suffix.png")
  $big = New-Object System.Drawing.Bitmap(($bmp.Width*2), ($bmp.Height*2))
  $g2 = [System.Drawing.Graphics]::FromImage($big); $g2.InterpolationMode = 'NearestNeighbor'
  $g2.DrawImage($bmp, 0, 0, $big.Width, $big.Height); $g2.Dispose(); $big.Save("$Out$suffix@2x.png")
  Write-Output ("capture{0}: {1},{2} {3}x{4}" -f $suffix, $r.L, $r.T, ($r.R-$r.L), ($r.B-$r.T))
}
function ExStyle() { $v = [W3]::GetWindowLongPtrW($script:h, -20); "exstyle=0x{0:X} topmost={1} transparent={2} noactivate={3}" -f $v, (($v -band 8) -ne 0), (($v -band 0x20) -ne 0), (($v -band 0x8000000) -ne 0) }
function Drag([int]$fromX, [int]$fromY, [int]$dx, [int]$dy) {
  [In]::MoveTo($fromX, $fromY); Start-Sleep -Milliseconds 150
  Write-Output ("  cursor at {0} (wanted {1},{2})" -f [In]::Cursor(), $fromX, $fromY)
  [In]::Down(); Start-Sleep -Milliseconds 150
  $steps = 16
  for ($i = 1; $i -le $steps; $i++) { [In]::MoveTo($fromX + [int]($dx*$i/$steps), $fromY + [int]($dy*$i/$steps)); Start-Sleep -Milliseconds 30 }
  Start-Sleep -Milliseconds 150
  [In]::Up(); Start-Sleep -Milliseconds 500
}

$fg0 = [W3]::GetForegroundWindow()
$p = Start-Process $Exe -PassThru -RedirectStandardOutput "$Out.stdout.txt" -RedirectStandardError "$Out.stderr.txt"
Start-Sleep -Seconds 7
$script:h = [W3]::FindWindowW("PTMonitor2.Main", "PTMonitor 2")
if ($h -eq [IntPtr]::Zero) { Write-Output "window not found"; Get-Content "$Out.stderr.txt"; exit 1 }
Write-Output ("widget is not foreground after show: {0}" -f ([W3]::GetForegroundWindow() -ne $h))
Capture "-start"
Write-Output (ExStyle)

# Hover the gear (DIP 207..227 x 6..26 at 100% DPI) and click it
$r = Rect
[In]::MoveTo($r.L + 217, $r.T + 16); Start-Sleep -Milliseconds 200; [In]::MoveTo($r.L + 218, $r.T + 16); Start-Sleep -Milliseconds 500
Write-Output ("  cursor at {0}" -f [In]::Cursor())
Capture "-hover"
[In]::Down(); Start-Sleep -Milliseconds 80; [In]::Up(); Start-Sleep -Milliseconds 300
Write-Output ("widget is not foreground after gear click: {0}" -f ([W3]::GetForegroundWindow() -ne $h))

# Drag by a row (HTCAPTION): expect the window to move by about (-300,-200)
$r0 = Rect
Drag ($r0.L + 120) ($r0.T + 150) (-300) (-200)
$r1 = Rect
Write-Output ("drag1: from {0},{1} to {2},{3} (delta {4},{5}); size {6}x{7}" -f $r0.L, $r0.T, $r1.L, $r1.T, ($r1.L-$r0.L), ($r1.T-$r0.T), ($r1.R-$r1.L), ($r1.B-$r1.T))
Write-Output ("widget is not foreground after drag: {0}" -f ([W3]::GetForegroundWindow() -ne $h))

# Drop against the top edge of the screen (Aero Snap would maximize a normal window)
$r1 = Rect
Drag ($r1.L + 120) ($r1.T + 150) 0 (2 - ($r1.T + 150))
$r2 = Rect
Write-Output ("drag-top: now {0},{1} size {2}x{3} (unchanged size = {4})" -f $r2.L, $r2.T, ($r2.R-$r2.L), ($r2.B-$r2.T), ((($r2.R-$r2.L) -eq ($r1.R-$r1.L)) -and (($r2.B-$r2.T) -eq ($r1.B-$r1.T))))
[In]::MoveTo(100, 700); Start-Sleep -Milliseconds 300
Capture "-moved"

# Layer cycle: Normal, Desktop, Topmost, click-through
foreach ($step in 1..4) {
  [void][W3]::PostMessageW($h, 0x0205, [IntPtr]::Zero, [IntPtr]::Zero); Start-Sleep -Milliseconds 700
  Write-Output ("step {0}: {1}" -f $step, (ExStyle))
}
Capture "-clickthrough"
[void][W3]::PostMessageW($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
$p.WaitForExit(5000) | Out-Null
Write-Output ("exited: {0} code {1}" -f $p.HasExited, $p.ExitCode)
Write-Output "--- stdout ---"; Get-Content "$Out.stdout.txt"
Write-Output "--- stderr ---"; Get-Content "$Out.stderr.txt" | Select-Object -First 8

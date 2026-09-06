param([string]$Exe, [string]$Out)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class P4 {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowW(string cls, string name);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern long GetWindowLongPtrW(IntPtr h, int idx);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
[void][P4]::SetProcessDPIAware()
$WM_APP_CMD = 0x8000 + 4
function Cmd([int]$id) { [void][P4]::PostMessageW($script:h, $WM_APP_CMD, [IntPtr]$id, [IntPtr]::Zero); Start-Sleep -Milliseconds 900 }
function Rect() { $r = New-Object P4+RECT; [void][P4]::GetWindowRect($script:h, [ref]$r); $r }
function Size() { $r = Rect; "{0}x{1} at {2},{3}" -f ($r.R-$r.L), ($r.B-$r.T), $r.L, $r.T }
function Topmost() { ([P4]::GetWindowLongPtrW($script:h, -20) -band 8) -ne 0 }
function Capture([string]$suffix) {
  $r = Rect; $m = 16
  $bmp = New-Object System.Drawing.Bitmap(($r.R-$r.L+2*$m), ($r.B-$r.T+2*$m))
  $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($r.L-$m, $r.T-$m, 0, 0, $bmp.Size); $g.Dispose()
  $bmp.Save("$Out$suffix.png")
}
$legacy = Join-Path $env:LOCALAPPDATA 'PTMonitor\settings.json'
$v2 = Join-Path $env:LOCALAPPDATA 'PTMonitor2\settings.json'
$legacyHash0 = (Get-FileHash $legacy -Algorithm SHA256).Hash
Remove-Item $v2 -ErrorAction SilentlyContinue   # force a fresh v1 import for this test
Remove-Item Env:PTM2_POS -ErrorAction SilentlyContinue
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Remove-ItemProperty -Path $runKey -Name PTMonitor2 -ErrorAction SilentlyContinue

$p = Start-Process $Exe -PassThru
Start-Sleep -Seconds 6
$script:h = [P4]::FindWindowW("PTMonitor2.Main", "PTMonitor 2")
if ($h -eq [IntPtr]::Zero) { Write-Output "window not found"; exit 1 }
Write-Output ("start: visible={0} {1} topmost={2}" -f [P4]::IsWindowVisible($h), (Size), (Topmost))
Write-Output ("v2 settings exists after import: {0}" -f (Test-Path $v2))
Capture "-start"

Cmd 1;  Write-Output ("after toggle (hide): visible={0}" -f [P4]::IsWindowVisible($h))
Cmd 1;  Write-Output ("after toggle (show): visible={0}" -f [P4]::IsWindowVisible($h))
Cmd 11; Write-Output ("layer normal: topmost={0}" -f (Topmost))
Cmd 10; Write-Output ("layer topmost: topmost={0}" -f (Topmost))
Cmd 32; Write-Output "opacity 50% set"; Capture "-opacity50"
Cmd 30; Write-Output "opacity 100% set"
Cmd 41; Write-Output ("sparklines off: {0}" -f (Size))
Cmd 41; Write-Output ("sparklines on: {0}" -f (Size))
Cmd 50; $v = (Get-ItemProperty -Path $runKey -Name PTMonitor2 -ErrorAction SilentlyContinue).PTMonitor2; Write-Output ("autostart on: Run value = [{0}]" -f $v)
Cmd 50; $v = (Get-ItemProperty -Path $runKey -Name PTMonitor2 -ErrorAction SilentlyContinue).PTMonitor2; Write-Output ("autostart off: Run value = [{0}]" -f $v)
Cmd 51; Cmd 51; Write-Output "start-hidden toggled twice"
Start-Sleep -Milliseconds 800
Write-Output "--- settings.json ---"; Get-Content $v2
Cmd 99
$p.WaitForExit(8000) | Out-Null
Write-Output ("exited: {0} code {1}" -f $p.HasExited, $p.ExitCode)
$legacyHash1 = (Get-FileHash $legacy -Algorithm SHA256).Hash
Write-Output ("legacy settings unchanged: {0}" -f ($legacyHash0 -eq $legacyHash1))

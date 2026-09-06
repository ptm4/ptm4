param([string]$Exe)
$ErrorActionPreference = 'Continue'
Add-Type @"
using System; using System.Runtime.InteropServices;
public class PF {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowW(string cls, string name);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
$WM_APP_CMD = 0x8000 + 4
function Cmd([int]$id) { [void][PF]::PostMessageW($script:h, $WM_APP_CMD, [IntPtr]$id, [IntPtr]::Zero); Start-Sleep -Milliseconds 900 }
$v2 = Join-Path $env:LOCALAPPDATA 'PTMonitor2\settings.json'

$p = Start-Process $Exe -PassThru
Start-Sleep -Seconds 4
$script:h = [PF]::FindWindowW("PTMonitor2.Main", "PTMonitor 2")
if ($h -eq [IntPtr]::Zero) { Write-Output "window not found"; exit 1 }
Cmd 42   # game mode off so the card is visible under a fullscreen app

# Position persistence: move the window as the OS drag loop would, then signal drag end.
[void][PF]::SetWindowPos($h, [IntPtr]::Zero, 2700, 300, 0, 0, 0x0001 -bor 0x0004 -bor 0x0010)  # NOSIZE|NOZORDER|NOACTIVATE
[void][PF]::PostMessageW($h, 0x0232, [IntPtr]::Zero, [IntPtr]::Zero)  # WM_EXITSIZEMOVE
Start-Sleep -Seconds 2
$cfg = Get-Content $v2 -Raw | ConvertFrom-Json
Write-Output ("saved position: {0},{1} monitor=[{2}] placed={3}" -f $cfg.window.x, $cfg.window.y, $cfg.window.monitor, $cfg.window.placed)

# Off-screen clamp on restart: write an absurd position, restart, expect it clamped on-screen.
Cmd 99; $p.WaitForExit(5000) | Out-Null
$cfg.window.x = 9000; $cfg.window.y = -3000; $cfg.window.monitor = "DISPLAY9"
$cfg | ConvertTo-Json -Depth 5 | Set-Content $v2
$p = Start-Process $Exe -PassThru
Start-Sleep -Seconds 4
$script:h = [PF]::FindWindowW("PTMonitor2.Main", "PTMonitor 2")
$r = New-Object PF+RECT; [void][PF]::GetWindowRect($h, [ref]$r)
Write-Output ("restart from 9000,-3000 on DISPLAY9 -> window at {0},{1} (on-screen = {2})" -f $r.L, $r.T, (($r.L -ge 0) -and ($r.L -lt 5120) -and ($r.T -ge 0) -and ($r.T -lt 1440)))
Cmd 42

# About dialog: opens a modal box; close it programmatically.
[void][PF]::PostMessageW($h, $WM_APP_CMD, [IntPtr]62, [IntPtr]::Zero)
Start-Sleep -Milliseconds 1500
$about = [PF]::FindWindowW("#32770", "About PTMonitor 2")
Write-Output ("about dialog found: {0}" -f ($about -ne [IntPtr]::Zero))
if ($about -ne [IntPtr]::Zero) { [void][PF]::PostMessageW($about, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero); Start-Sleep -Milliseconds 800 }
Write-Output ("widget still alive and visible after About: {0}" -f [PF]::IsWindowVisible($h))

# Restore a sane position for the user, then quit.
[void][PF]::SetWindowPos($h, [IntPtr]::Zero, 2575, 886, 0, 0, 0x0001 -bor 0x0004 -bor 0x0010)
[void][PF]::PostMessageW($h, 0x0232, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Seconds 2
Cmd 99
$p.WaitForExit(8000) | Out-Null
Write-Output ("exited: {0} code {1}" -f $p.HasExited, $p.ExitCode)
$cfg = Get-Content $v2 -Raw | ConvertFrom-Json
Write-Output ("final saved position: {0},{1} monitor=[{2}] game_mode={3}" -f $cfg.window.x, $cfg.window.y, $cfg.window.monitor, $cfg.game_mode)

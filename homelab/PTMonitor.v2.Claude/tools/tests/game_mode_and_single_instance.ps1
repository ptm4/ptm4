param([string]$Exe)
$ErrorActionPreference = 'Continue'
Add-Type @"
using System; using System.Runtime.InteropServices;
public class P5 {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowW(string cls, string name);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("shell32.dll")] public static extern int SHQueryUserNotificationState(out int state);
}
"@
$WM_APP_CMD = 0x8000 + 4
function Cmd([int]$id) { [void][P5]::PostMessageW($script:h, $WM_APP_CMD, [IntPtr]$id, [IntPtr]::Zero); Start-Sleep -Milliseconds 900 }
$state = 0; [void][P5]::SHQueryUserNotificationState([ref]$state)
Write-Output ("QUNS now: {0} (2=BUSY 3=D3D_FULLSCREEN 4=PRESENTATION 5=ACCEPTS)" -f $state)

$p = Start-Process $Exe -PassThru
Start-Sleep -Seconds 5
$script:h = [P5]::FindWindowW("PTMonitor2.Main", "PTMonitor 2")
if ($h -eq [IntPtr]::Zero) { Write-Output "window not found"; exit 1 }
Write-Output ("t+5s: visible={0} (expected hidden if a fullscreen app is in front and game mode is on)" -f [P5]::IsWindowVisible($h))
Cmd 42; Start-Sleep -Milliseconds 600
Write-Output ("game mode off: visible={0}" -f [P5]::IsWindowVisible($h))
Cmd 42; Start-Sleep -Seconds 3
Write-Output ("game mode on again (t+3s): visible={0}" -f [P5]::IsWindowVisible($h))
Cmd 42; Start-Sleep -Milliseconds 600
Write-Output ("game mode off: visible={0}" -f [P5]::IsWindowVisible($h))

# Single-instance handoff: hide, then launch a second copy -> the first should show itself.
Cmd 1; Write-Output ("hidden by command: visible={0}" -f [P5]::IsWindowVisible($h))
$p2 = Start-Process $Exe -PassThru -Wait
Start-Sleep -Milliseconds 1200
Write-Output ("second launch exited (code {0}); first instance visible={1}; instances={2}" -f $p2.ExitCode, [P5]::IsWindowVisible($h), (Get-Process ptmonitor2 -ErrorAction SilentlyContinue | Measure-Object).Count)

Cmd 99
$p.WaitForExit(8000) | Out-Null
Write-Output ("exited: {0} code {1}" -f $p.HasExited, $p.ExitCode)

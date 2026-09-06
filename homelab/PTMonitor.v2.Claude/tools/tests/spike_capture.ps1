param(
  [string]$Exe,
  [string]$Out,
  [int]$WaitMs = 1500,
  [int]$Clicks = 0,        # number of WM_RBUTTONUP to post, capturing after each
  [int]$Zoom = 2,
  [switch]$KeepOpen
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowW(string cls, string name);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
[void][W]::SetProcessDPIAware()
$p = Start-Process $Exe -PassThru -RedirectStandardOutput "$Out.stdout.txt" -RedirectStandardError "$Out.stderr.txt"
Start-Sleep -Milliseconds $WaitMs
$h = [W]::FindWindowW("PTMonitor2.Main", "PTMonitor 2")
if ($h -eq [IntPtr]::Zero) { Write-Output "window not found"; Get-Content "$Out.stdout.txt","$Out.stderr.txt" -ErrorAction SilentlyContinue; exit 1 }
function Capture([string]$suffix) {
  $r = New-Object W+RECT; [void][W]::GetWindowRect($h, [ref]$r)
  $m = 24
  $bmp = New-Object System.Drawing.Bitmap(($r.R-$r.L+2*$m), ($r.B-$r.T+2*$m))
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($r.L-$m, $r.T-$m, 0, 0, $bmp.Size)
  $g.Dispose()
  $bmp.Save("$Out$suffix.png")
  $big = New-Object System.Drawing.Bitmap(($bmp.Width*$Zoom), ($bmp.Height*$Zoom))
  $g2 = [System.Drawing.Graphics]::FromImage($big); $g2.InterpolationMode = 'NearestNeighbor'
  $g2.DrawImage($bmp, 0, 0, $big.Width, $big.Height); $g2.Dispose(); $big.Save("$Out$suffix@$($Zoom)x.png")
  Write-Output ("captured{0}: rect {1},{2} {3}x{4}" -f $suffix, $r.L, $r.T, ($r.R-$r.L), ($r.B-$r.T))
}
Capture ""
for ($i = 1; $i -le $Clicks; $i++) {
  [void][W]::PostMessageW($h, 0x0205, [IntPtr]::Zero, [IntPtr]::Zero)
  Start-Sleep -Milliseconds 900
  Capture "-$i"
}
if (-not $KeepOpen) {
  [void][W]::PostMessageW($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)  # WM_CLOSE
  $p.WaitForExit(5000) | Out-Null
  Write-Output ("exited: {0} code {1}" -f $p.HasExited, $p.ExitCode)
}
Write-Output "--- stdout ---"; Get-Content "$Out.stdout.txt" -ErrorAction SilentlyContinue
Write-Output "--- stderr ---"; Get-Content "$Out.stderr.txt" -ErrorAction SilentlyContinue | Select-Object -First 5

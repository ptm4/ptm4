<#
.SYNOPSIS
  Installs (or removes) the Asset Library server on this workstation (ptm).

.DESCRIPTION
  Pertal's Asset Library page (https://webapp.lan:8444/assets) browses E:\Assets live from
  this PC. This script:
    1. copies asset-server.py to %LOCALAPPDATA%\asset-server\, so the running server does
       not depend on which branch a repo checkout happens to be on;
    2. adds ONE Windows Firewall rule: inbound TCP 8767, from opti (192.168.1.11) only, for
       this Python's pythonw.exe only, on every network profile (this PC's Ethernet is on
       the Public profile);
    3. registers a logon task that runs the server hidden, as you (not elevated), and
       restarts it if it dies;
    4. starts it and checks /health.
  Run it from an elevated PowerShell: the firewall rule needs admin. Re-run it after
  asset-server.py changes. -Uninstall removes the task and the rule.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File E:\REPO\ptm4\homelab\hosts\ptm\asset-server\Install-AssetServer.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File E:\REPO\ptm4\homelab\hosts\ptm\asset-server\Install-AssetServer.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [string]$Root = 'E:\Assets',
  [string]$Bind = '192.168.1.3',
  [int]$Port = 8767,
  [string[]]$Allow = @('192.168.1.11'),
  [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$RuleName = 'Homelab-AssetLibrary'
$TaskPath = '\Homelab\'
$TaskName = 'Asset Library server'
$InstallDir = Join-Path $env:LOCALAPPDATA 'asset-server'
$User = "$env:USERDOMAIN\$env:USERNAME"

$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Run this from an elevated PowerShell (Run as administrator): the firewall rule needs it.'
}

function Stop-AssetServer {
  Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
  Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    ForEach-Object { Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } |
    Where-Object { $_.ProcessName -like 'python*' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
}

if ($Uninstall) {
  Stop-AssetServer
  Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Remove-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
  Write-Host "Removed the logon task and the firewall rule. $InstallDir (script copy, thumbnails, log) is left in place."
  return
}

# The python.org Python on PATH; pythonw.exe is the same interpreter without a console window.
$python = (Get-Command python -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw "pythonw.exe not found next to $python" }
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { throw "$Root is not a folder" }
& $python -c 'import PIL' 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Pillow is not installed for $python, so the page shows icons instead of thumbnails. Fix: & '$python' -m pip install pillow"
}

# 1. The server, copied out of the repo.
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'asset-server.py') -Destination $InstallDir -Force
$script = Join-Path $InstallDir 'asset-server.py'

# 2. Firewall: opti only, this program only, this port only. Created before the server
#    first listens, so Windows never pops its "allow this app?" prompt.
Remove-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
New-NetFirewallRule -Name $RuleName -DisplayName "Asset Library server (opti only, TCP $Port)" -Group 'Homelab' `
  -Description 'Read-only E:\Assets for Pertal on opti. Source: homelab/hosts/ptm/asset-server in the ptm4 repo.' `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress $Allow `
  -Program $pythonw -Profile Any | Out-Null

# 3. Logon task: runs as this user, not elevated; restarted if it exits.
Stop-AssetServer
$arguments = "`"$script`" --root `"$Root`" --bind $Bind --port $Port --allow $($Allow -join ',')"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
  -Principal $principal -Description 'Serves E:\Assets read-only to Pertal on opti (Asset Library page).' -Force | Out-Null

# 4. Start it and ask it how it is.
Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
$health = $null
foreach ($i in 1..20) {
  Start-Sleep -Seconds 1
  try { $health = Invoke-RestMethod -Uri "http://${Bind}:$Port/health" -TimeoutSec 3; break } catch { }
}
if ($health) {
  Write-Host "Asset Library server $($health.version) is serving $($health.root) on ${Bind}:$Port (clients: $($Allow -join ', ') and this PC)."
  Write-Host 'Its search index builds in the background over the next few minutes.'
  Write-Host 'https://webapp.lan:8444/assets picks it up within 30 seconds.'
} else {
  Write-Warning "No answer from http://${Bind}:$Port/health yet. See $InstallDir\asset-server.log"
}

param([string]$Executable)
$ErrorActionPreference = 'Stop'
if (-not $Executable) {
    $Executable = Join-Path (Split-Path -Parent $PSScriptRoot) 'src-tauri\binaries\PTMonitor.SensorHost-x86_64-pc-windows-msvc.exe'
}
function Start-SensorTest([string]$Arguments) {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    $startInfo.Arguments = $Arguments
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    return [System.Diagnostics.Process]::Start($startInfo)
}
function Read-Frame($Process) {
    $pending = $Process.StandardOutput.ReadLineAsync()
    if (-not $pending.Wait(20000)) { throw 'Sensor heartbeat did not arrive within 20 seconds.' }
    if (-not $pending.Result) { throw 'Sensor helper ended without a frame.' }
    return $pending.Result | ConvertFrom-Json
}
$sensorProcess = Start-SensorTest "--stdio --parent-pid $PID"
try {
    $frames = @()
    for ($index = 0; $index -lt 4; $index++) {
        $sensorProcess.StandardInput.WriteLine('ping')
        $sensorProcess.StandardInput.Flush()
        $frame = Read-Frame $sensorProcess
        if ($frame.protocolVersion -ne 1 -or $frame.status -eq 'error') { throw 'Sensor frame has an invalid protocol or reported failure.' }
        $frames += $frame
    }
    for ($index = 1; $index -lt $frames.Count; $index++) {
        $delta = $frames[$index].timestampMs - $frames[$index - 1].timestampMs
        if ($delta -lt 500 -or $delta -gt 3000) { throw "Sensor cadence is outside tolerance: $delta ms." }
    }
    if (-not $frames[-1].elevated) {
        $untrustedCpu = @($frames[-1].sensors | Where-Object { $_.hardwareType -eq 'Cpu' -and $_.sensorType -ne 'Load' })
        if ($untrustedCpu.Count -gt 0) { throw 'Unprivileged CPU register values must be unavailable.' }
    }
    $listeners = @(Get-NetTCPConnection -OwningProcess $sensorProcess.Id -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) { throw 'Sensor helper unexpectedly owns a TCP listener.' }
    $sensorProcess.StandardInput.Close()
    if (-not $sensorProcess.WaitForExit(5000)) { throw 'Sensor helper did not exit after parent IPC closed.' }
    Write-Host "PASS: four live frames, one-second cadence, permission handling, no TCP listener, clean EOF exit."
    $frames[-1].sensors | Group-Object hardware | Select-Object Name, Count
}
finally {
    if (-not $sensorProcess.HasExited) { $sensorProcess.Kill(); $sensorProcess.WaitForExit() }
    $sensorProcess.Dispose()
}
# A live parent which stops sending heartbeats must not leave an orphaned collector.
$sensorProcess = Start-SensorTest "--stdio --parent-pid $PID"
try {
    $outputDrain = $sensorProcess.StandardOutput.ReadToEndAsync()
    if (-not $sensorProcess.WaitForExit(22000)) { throw 'Sensor parent-heartbeat watchdog failed.' }
    Write-Host 'PASS: helper stops within 22 seconds after parent heartbeat loss.'
}
finally {
    if (-not $sensorProcess.HasExited) { $sensorProcess.Kill(); $sensorProcess.WaitForExit() }
    $sensorProcess.Dispose()
}

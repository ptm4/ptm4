$ErrorActionPreference='Stop'
$previewRoot=[IO.Path]::GetFullPath($PSScriptRoot)
$record=Get-Content -LiteralPath (Join-Path $previewRoot '.runtime/processes.json') -Raw | ConvertFrom-Json
$comms=[IO.Path]::GetFullPath((Join-Path $previewRoot '..\..\..\..\AgentComms.md'))
Get-Content -LiteralPath $comms -Tail 14
foreach($kind in @('frontend','backend')) {
 $ownedId=$record."${kind}Pid"
 $process=Get-CimInstance Win32_Process -Filter "ProcessId=$ownedId"
 if(!$process){continue}
 if(!$process.CommandLine.Contains($previewRoot)){throw "PID $ownedId has an unrecognized command line. Stopped no unverified process."}
 Stop-Process -Id $ownedId
}
$entry="`nAstra: $([DateTimeOffset]::Now.ToString('o')) | LOCAL STOP`nPaths: $previewRoot`nPorts/processes: Released owned $($record.frontendPort) PID $($record.frontendPid), $($record.backendPort) PID $($record.backendPid).`nProgress: Stopped only processes whose command lines matched this preview directory. Runtime files retained.`nNext: Start-Preview.ps1 to resume.`nCoordination: Legacy and Fable untouched.`n"
[IO.File]::AppendAllText($comms,$entry)
Get-Content -LiteralPath $comms -Tail 7

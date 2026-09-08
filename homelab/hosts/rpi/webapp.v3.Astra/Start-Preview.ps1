param([int]$FrontendPort=5174,[int]$BackendPort=3003)
$ErrorActionPreference='Stop'
$previewRoot=[IO.Path]::GetFullPath($PSScriptRoot)
$runtime=Join-Path $previewRoot '.runtime'
$comms=[IO.Path]::GetFullPath((Join-Path $previewRoot '..\..\..\..\AgentComms.md'))
Get-Content -LiteralPath $comms -Tail 24
if($FrontendPort -eq $BackendPort -or $FrontendPort -lt 1024 -or $BackendPort -lt 1024){throw 'Choose distinct unprivileged ports.'}
foreach($port in @($FrontendPort,$BackendPort)) {
 if(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue){throw "Port $port is occupied. No process was stopped. Read AgentComms.md and choose another unused pair with -FrontendPort / -BackendPort."}
}
$node=(Get-Command node -ErrorAction Stop).Source
if(!(Test-Path -LiteralPath (Join-Path $previewRoot 'frontend/node_modules/vite/bin/vite.js'))){throw 'Install frontend and backend dependencies first; see README.md.'}
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$entry="`nAstra: $([DateTimeOffset]::Now.ToString('o')) | LOCAL START — ports reserved`nPaths: $previewRoot`nPorts/processes: Frontend $FrontendPort; backend $BackendPort. Both listeners checked unused.`nProgress: Starting loopback-only demo preview; no collectors.`nNext: Record owned process IDs.`nCoordination: Shared log read before startup; legacy/Fable untouched.`n"
[IO.File]::AppendAllText($comms,$entry)
Get-Content -LiteralPath $comms -Tail 7
$env:ASTRA_PORT="$BackendPort"
$env:ASTRA_FRONTEND_PORT="$FrontendPort"
$env:ASTRA_MODE='demo'
$backendScript=Join-Path $previewRoot 'backend/server.js'
$frontendScript=Join-Path $previewRoot 'frontend/node_modules/vite/bin/vite.js'
$backend=Start-Process -FilePath $node -ArgumentList ('"'+$backendScript+'"') -WorkingDirectory (Join-Path $previewRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'backend.stdout.log') -RedirectStandardError (Join-Path $runtime 'backend.stderr.log') -PassThru
$frontend=Start-Process -FilePath $node -ArgumentList ('"'+$frontendScript+'"') -WorkingDirectory (Join-Path $previewRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'frontend.stdout.log') -RedirectStandardError (Join-Path $runtime 'frontend.stderr.log') -PassThru
$record=@{root=$previewRoot;backendPid=$backend.Id;frontendPid=$frontend.Id;backendPort=$BackendPort;frontendPort=$FrontendPort;startedAt=[DateTimeOffset]::Now.ToString('o')}
[IO.File]::WriteAllText((Join-Path $runtime 'processes.json'),($record|ConvertTo-Json))
$entry="`nAstra: $([DateTimeOffset]::Now.ToString('o')) | LOCAL START — processes launched`nPaths: $previewRoot; $runtime\processes.json and stdout/stderr logs.`nPorts/processes: $FrontendPort PID $($frontend.Id); $BackendPort PID $($backend.Id).`nProgress: Launched hidden Node processes; verify the URLs and logs if either server exits.`nNext: Preview http://127.0.0.1:$FrontendPort ; API http://127.0.0.1:$BackendPort/api/health`nCoordination: No other process modified.`n"
[IO.File]::AppendAllText($comms,$entry)
Get-Content -LiteralPath $comms -Tail 7
Write-Output "Preview: http://127.0.0.1:$FrontendPort"

param(
    [string]$DotnetPath,
    [switch]$TestOnly
)
$ErrorActionPreference = 'Stop'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $DotnetPath) {
    $portableSdk = Join-Path $env:LOCALAPPDATA 'PTMonitor-build\dotnet-8\dotnet.exe'
    if (Test-Path -LiteralPath $portableSdk) { $DotnetPath = $portableSdk }
    else {
        $dotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
        if (-not $dotnetCommand) { throw 'A .NET 8 SDK is required. Install an SDK or pass -DotnetPath to a portable SDK executable.' }
        $DotnetPath = $dotnetCommand.Source
    }
}
$sdkList = & $DotnetPath --list-sdks
if ($LASTEXITCODE -ne 0 -or -not ($sdkList -match '^8\.')) { throw 'A .NET 8 SDK is required; a runtime alone is insufficient.' }
$projectFile = Join-Path $PSScriptRoot 'PTMonitor.SensorHost.csproj'
$publishDirectory = Join-Path $PSScriptRoot 'bin\Release\net8.0-windows\win-x64\publish'
$binaryDirectory = Join-Path $projectRoot 'src-tauri\binaries'
if ($TestOnly) {
    & $DotnetPath run --project $projectFile -c Release --no-launch-profile -- --self-test
    if ($LASTEXITCODE -ne 0) { throw "Sensor self-tests failed with exit code $LASTEXITCODE." }
    exit 0
}
& $DotnetPath publish $projectFile -c Release -r win-x64 --self-contained true -p:RestoreLockedMode=true
if ($LASTEXITCODE -ne 0) { throw "Sensor publish failed with exit code $LASTEXITCODE." }
$publishedExecutable = Join-Path $publishDirectory 'PTMonitor.SensorHost.exe'
if (-not (Test-Path -LiteralPath $publishedExecutable)) { throw 'Sensor publish produced no executable.' }
& $publishedExecutable --self-test
if ($LASTEXITCODE -ne 0) { throw "Sensor self-tests failed with exit code $LASTEXITCODE." }
# Tauri requires the target triple on external binaries; the installed name omits it.
New-Item -Path $binaryDirectory -ItemType Directory -Force | Out-Null
Copy-Item -LiteralPath $publishedExecutable -Destination (Join-Path $binaryDirectory 'PTMonitor.SensorHost-x86_64-pc-windows-msvc.exe') -Force
Write-Host "Built and checked sensor helper: $binaryDirectory"

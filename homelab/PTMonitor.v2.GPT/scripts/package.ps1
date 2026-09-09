# Produces the portable ZIP and SHA-256 checksums alongside the NSIS installer
# that `tauri build` has already emitted (plan Section 5).
#
# Run after `npm run build`. This never publishes or signs anything.

[CmdletBinding()]
param([string]$OutDir)

$ErrorActionPreference = 'Stop'

$root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
if (-not $OutDir) { $OutDir = Join-Path $root 'dist' }

$release = Join-Path $root 'src-tauri\target\release'
$version = (Get-Content (Join-Path $root 'src-tauri\tauri.conf.json') -Raw | ConvertFrom-Json).version

# Everything the portable release must contain: the application, both helper
# processes, the surface DLL and the notices.
$payload = [ordered]@{
    'ptmonitor-v2.exe'                = Join-Path $release 'ptmonitor-v2.exe'
    'PTMonitor.SensorHost.exe'        = Join-Path $release 'PTMonitor.SensorHost.exe'
    'PTMonitor.TaskbarHost.exe'       = Join-Path $root 'taskbar-native\build\PTMonitor.TaskbarHost.exe'
    'PTMonitor.TaskbarSurface.dll'    = Join-Path $root 'taskbar-native\build\PTMonitor.TaskbarSurface.dll'
    'THIRD-PARTY-NOTICES.md'          = Join-Path $root 'sensor-host\THIRD-PARTY-NOTICES.md'
    'TASKBAR-THIRD-PARTY-NOTICES.md'  = Join-Path $root 'taskbar-native\THIRD-PARTY-NOTICES.md'
    'TASKBAR-LICENSE'                 = Join-Path $root 'taskbar-native\LICENSE'
}

$missing = @()
foreach ($name in $payload.Keys) {
    if (-not (Test-Path $payload[$name])) { $missing += "$name (expected at $($payload[$name]))" }
}
if ($missing.Count -gt 0) {
    throw "Portable payload incomplete. Run `npm run build` first. Missing:`n  " + ($missing -join "`n  ")
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$staging = Join-Path $OutDir "PTMonitor-v2-$version-portable"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

foreach ($name in $payload.Keys) {
    Copy-Item -LiteralPath $payload[$name] -Destination (Join-Path $staging $name) -Force
}

# Also carry the sensor host's bundled licences when present.
$licences = Join-Path $root 'sensor-host\licenses'
if (Test-Path $licences) {
    Copy-Item -LiteralPath $licences -Destination (Join-Path $staging 'licenses') -Recurse -Force
}

$zip = Join-Path $OutDir "PTMonitor-v2-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $staging -Recurse -Force

# Collect the installer tauri produced, if it is there.
$artifacts = @($zip)
$installer = Get-ChildItem (Join-Path $release 'bundle\nsis') -Filter '*.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($installer) {
    $copied = Join-Path $OutDir $installer.Name
    Copy-Item -LiteralPath $installer.FullName -Destination $copied -Force
    $artifacts += $copied
} else {
    Write-Warning 'No NSIS installer found; packaging the portable ZIP only.'
}

# Hash through .NET rather than Get-FileHash, which is unavailable on older
# PowerShell hosts that npm may invoke.
function Get-Sha256Hex([string]$Path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return [System.BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

$checksums = Join-Path $OutDir 'SHA256SUMS.txt'
$lines = foreach ($artifact in $artifacts) {
    "$(Get-Sha256Hex $artifact)  $(Split-Path -Leaf $artifact)"
}
Set-Content -Path $checksums -Value $lines -Encoding ASCII

Write-Host ''
Write-Host "PTMonitor v$version release artifacts in $OutDir"
foreach ($line in $lines) { Write-Host "  $line" }

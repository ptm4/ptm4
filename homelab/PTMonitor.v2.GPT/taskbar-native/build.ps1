# Builds the native taskbar host, surface DLL and native tests.
#
# Plan Section 5: locate the installed Visual Studio C++ toolchain through
# vswhere, build x64 Release, require an installed Windows SDK with C++/WinRT
# headers, never download or install a compiler or SDK, and stop on warnings,
# failed tests or missing outputs.

[CmdletBinding()]
param(
    [switch]$TestOnly,
    [string]$OutDir
)

$ErrorActionPreference = 'Stop'

$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $OutDir) { $OutDir = Join-Path $root 'build' }

function Find-VisualStudio {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) {
        throw 'vswhere.exe not found. Install the Visual Studio C++ build tools; this script never installs them for you.'
    }
    $install = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
    if (-not $install) {
        throw 'No Visual Studio installation with the x64 C++ toolchain was found.'
    }
    $vcvars = Join-Path $install 'VC\Auxiliary\Build\vcvars64.bat'
    if (-not (Test-Path $vcvars)) { throw "vcvars64.bat missing under $install." }
    return $vcvars
}

function Find-CppWinRTInclude {
    $root = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Include'
    if (-not (Test-Path $root)) { throw 'No Windows SDK found under Windows Kits\10\Include.' }
    $candidate = Get-ChildItem $root -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName 'cppwinrt\winrt\base.h') } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw 'No Windows SDK with C++/WinRT headers found. Install the SDK component that provides cppwinrt.'
    }
    return (Join-Path $candidate.FullName 'cppwinrt')
}

$vcvars = Find-VisualStudio
$cppwinrt = Find-CppWinRTInclude
Write-Host "Toolchain: $vcvars"
Write-Host "C++/WinRT: $cppwinrt"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# /WX is deliberate: the build stops on warnings.
$common = '/std:c++20 /utf-8 /EHsc /W4 /WX /O2 /MT /DUNICODE /D_UNICODE /nologo'
$src = $root

# cl rejects a /Fo prefix with several sources, so each translation unit is
# compiled on its own with an explicit object name.
$script = @"
call "$vcvars" >nul || exit /b 1
cd /d "$src"

cl $common /I "$cppwinrt" /c host\Discovery.cpp /Fo"$OutDir\Discovery.obj" || exit /b 1
cl $common /I "$cppwinrt" /c host\XamlAttach.cpp /Fo"$OutDir\XamlAttach.obj" || exit /b 1
cl $common /I "$cppwinrt" /c surface\SurfaceTap.cpp /Fo"$OutDir\SurfaceTap.obj" || exit /b 1
cl $common /I "$cppwinrt" /c surface\DllExports.cpp /Fo"$OutDir\DllExports.obj" || exit /b 1
cl $common /I "$cppwinrt" /c surface\Panel.cpp /Fo"$OutDir\Panel.obj" || exit /b 1
cl $common /I "$cppwinrt" /c host\HostMain.cpp /Fo"$OutDir\HostMain.obj" || exit /b 1
cl $common /I "$cppwinrt" /c tests\NativeTests.cpp /Fo"$OutDir\NativeTests.obj" || exit /b 1

link /nologo /DLL /DEF:surface\Surface.def /OUT:"$OutDir\PTMonitor.TaskbarSurface.dll" ^
  "$OutDir\SurfaceTap.obj" "$OutDir\DllExports.obj" "$OutDir\Panel.obj" ^
  runtimeobject.lib ole32.lib oleaut32.lib advapi32.lib || exit /b 1

link /nologo /OUT:"$OutDir\PTMonitor.TaskbarHost.exe" ^
  "$OutDir\HostMain.obj" "$OutDir\Discovery.obj" "$OutDir\XamlAttach.obj" ^
  user32.lib gdi32.lib ole32.lib oleaut32.lib runtimeobject.lib advapi32.lib shell32.lib || exit /b 1

link /nologo /OUT:"$OutDir\PTMonitor.TaskbarTests.exe" ^
  "$OutDir\NativeTests.obj" "$OutDir\Discovery.obj" ^
  user32.lib gdi32.lib ole32.lib oleaut32.lib runtimeobject.lib advapi32.lib shell32.lib || exit /b 1
"@

$batch = Join-Path $env:TEMP "ptmonitor-taskbar-build-$PID.bat"
Set-Content -Path $batch -Value $script -Encoding ASCII
try {
    & cmd.exe /c $batch
    if ($LASTEXITCODE -ne 0) { throw "Native build failed with exit code $LASTEXITCODE." }
} finally {
    Remove-Item $batch -ErrorAction SilentlyContinue
}

# Every expected output must exist.
foreach ($name in @('PTMonitor.TaskbarHost.exe', 'PTMonitor.TaskbarSurface.dll', 'PTMonitor.TaskbarTests.exe')) {
    $path = Join-Path $OutDir $name
    if (-not (Test-Path $path)) { throw "Expected build output missing: $name" }
}

& (Join-Path $OutDir 'PTMonitor.TaskbarTests.exe')
if ($LASTEXITCODE -ne 0) { throw "Native tests failed with exit code $LASTEXITCODE." }

if ($TestOnly) {
    Write-Host 'Native taskbar tests passed.'
    return
}

# Stage for packaging. Tauri requires the target triple on external binaries;
# the installed name omits it. The surface DLL ships as a bundled resource.
$projectRoot = Split-Path -Parent $root
$binaries = Join-Path $projectRoot 'src-tauri\binaries'
$resources = Join-Path $projectRoot 'src-tauri\resources'
New-Item -ItemType Directory -Force -Path $binaries, $resources | Out-Null

Copy-Item -LiteralPath (Join-Path $OutDir 'PTMonitor.TaskbarHost.exe') `
    -Destination (Join-Path $binaries 'PTMonitor.TaskbarHost-x86_64-pc-windows-msvc.exe') -Force
Copy-Item -LiteralPath (Join-Path $OutDir 'PTMonitor.TaskbarSurface.dll') `
    -Destination (Join-Path $resources 'PTMonitor.TaskbarSurface.dll') -Force

# Also place them beside the development binary so a local run picks them up.
# This is a convenience only: a host from a previous run may still be executing
# from there, which locks its own image. The packaging copies above are the
# ones that must succeed, so a busy development file is reported, not fatal.
$devDir = Join-Path $projectRoot 'src-tauri\target\release'
if (Test-Path $devDir) {
    foreach ($name in @('PTMonitor.TaskbarHost.exe', 'PTMonitor.TaskbarSurface.dll')) {
        try {
            Copy-Item -LiteralPath (Join-Path $OutDir $name) -Destination $devDir -Force -ErrorAction Stop
        } catch {
            Write-Warning "Left $name in the development directory untouched (in use). Stop PTMonitor to refresh it."
        }
    }
}

Write-Host "Native taskbar binaries built into $OutDir and staged for packaging."

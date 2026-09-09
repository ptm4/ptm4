@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
mkdir build 2>nul

set CPPWINRT_INC="C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\cppwinrt"
set COMMON=/std:c++20 /utf-8 /EHsc /W4 /nologo /Zi /MD /I %CPPWINRT_INC%

cl %COMMON% /Fo:build\ ^
  /c host\Discovery.cpp host\XamlAttach.cpp
if errorlevel 1 exit /b 1

cl %COMMON% /Fe:build\PTMonitor.TaskbarSurface.dll /LD ^
  surface\SurfaceTap.cpp surface\DllExports.cpp surface\Panel.cpp /Fo:build\ ^
  /link /DEF:surface\Surface.def runtimeobject.lib ole32.lib oleaut32.lib advapi32.lib
if errorlevel 1 exit /b 1

cl %COMMON% /Fe:build\gate.exe ^
  host\GateMain.cpp build\Discovery.obj build\XamlAttach.obj /Fo:build\ ^
  /link user32.lib gdi32.lib ole32.lib oleaut32.lib runtimeobject.lib advapi32.lib
if errorlevel 1 exit /b 1

cl %COMMON% /Fe:build\PTMonitor.TaskbarHost.exe ^
  host\HostMain.cpp build\Discovery.obj build\XamlAttach.obj /Fo:build\host_ ^
  /link user32.lib gdi32.lib ole32.lib oleaut32.lib runtimeobject.lib advapi32.lib
if errorlevel 1 exit /b 1

echo BUILD_OK

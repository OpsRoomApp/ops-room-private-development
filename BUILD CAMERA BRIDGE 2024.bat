@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Build OPS ROOM Camera Bridge 2024

echo ================================================================
echo OPS ROOM Camera Bridge 2024 - MSFS 2024 legacy external helper (restored default)
echo ================================================================
echo.

set "MSFS2024_SDK=C:\MSFS 2024 SDK"
set "VS_ROOT=C:\Program Files\Microsoft Visual Studio\2022\Community"
if defined OPSROOM_MSFS2024_SDK set "MSFS2024_SDK=%OPSROOM_MSFS2024_SDK%"
if defined OPSROOM_VS_ROOT set "VS_ROOT=%OPSROOM_VS_ROOT%"

if not exist "%MSFS2024_SDK%\SimConnect SDK\include\SimConnect.h" (
  echo ERROR: SimConnect.h not found:
  echo   %MSFS2024_SDK%\SimConnect SDK\include\SimConnect.h
  echo Set OPSROOM_MSFS2024_SDK if your SDK is elsewhere.
  goto :fail
)
if not exist "%MSFS2024_SDK%\SimConnect SDK\lib\SimConnect.lib" (
  echo ERROR: SimConnect.lib not found:
  echo   %MSFS2024_SDK%\SimConnect SDK\lib\SimConnect.lib
  goto :fail
)
if not exist "%VS_ROOT%\VC\Auxiliary\Build\vcvars64.bat" (
  echo ERROR: Visual Studio vcvars64.bat not found:
  echo   %VS_ROOT%\VC\Auxiliary\Build\vcvars64.bat
  echo Set OPSROOM_VS_ROOT if Visual Studio is elsewhere.
  goto :fail
)

call "%VS_ROOT%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 goto :fail

if not defined OPSROOM_BUILD_ROOT set "OPSROOM_BUILD_ROOT=%TEMP%\OR250"
set "BRIDGE_BUILD_DIR=%OPSROOM_BUILD_ROOT%\camera_bridge"
if exist "%BRIDGE_BUILD_DIR%" rmdir /s /q "%BRIDGE_BUILD_DIR%"
mkdir "%BRIDGE_BUILD_DIR%"
echo Using short Camera Bridge build root:
echo   %BRIDGE_BUILD_DIR%
echo.

set "BRIDGE_RES="
if exist "camera_bridge_2024\resources\camera_bridge.rc" (
  rc /nologo /fo "%BRIDGE_BUILD_DIR%\camera_bridge.res" "camera_bridge_2024\resources\camera_bridge.rc"
  if errorlevel 1 goto :fail
  set BRIDGE_RES="%BRIDGE_BUILD_DIR%\camera_bridge.res"
)
cl /nologo /std:c++17 /EHsc /O2 /W3 ^
  /I"%MSFS2024_SDK%\SimConnect SDK\include" ^
  /Fo:"%BRIDGE_BUILD_DIR%\main.obj" ^
  "camera_bridge_2024\src\main.cpp" %BRIDGE_RES% ^
  /Fe:"%BRIDGE_BUILD_DIR%\OPS ROOM Camera Bridge 2024.exe" ^
  /link /LIBPATH:"%MSFS2024_SDK%\SimConnect SDK\lib" SimConnect.lib winhttp.lib shell32.lib ole32.lib
if errorlevel 1 goto :fail

copy /y "%MSFS2024_SDK%\SimConnect SDK\lib\SimConnect.dll" "%BRIDGE_BUILD_DIR%\SimConnect.dll" >nul
if errorlevel 1 goto :fail

echo.
echo Camera Bridge build complete:
echo   %BRIDGE_BUILD_DIR%\OPS ROOM Camera Bridge 2024.exe
echo   %BRIDGE_BUILD_DIR%\SimConnect.dll
echo.
exit /b 0

:fail
echo.
echo Camera Bridge build failed. Review the first ERROR above.
pause
exit /b 1

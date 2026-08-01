@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Install OPS ROOM vPilot Bridge

echo OPS ROOM v0.20.0 vPilot Bridge
set "VPILOT_DIR=%~1"
if not defined VPILOT_DIR set "VPILOT_DIR=%LOCALAPPDATA%\vPilot"
if not exist "%VPILOT_DIR%\RossCarlson.Vatsim.Vpilot.Plugins.dll" (
  echo.
  echo The official vPilot plugin interface was not found in:
  echo   %VPILOT_DIR%
  echo.
  echo Pass a custom vPilot folder as the first argument if required.
  pause
  exit /b 1
)
set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo .NET Framework C# compiler was not found.
  pause
  exit /b 1
)
if not exist "%VPILOT_DIR%\Plugins" mkdir "%VPILOT_DIR%\Plugins"
"%CSC%" /nologo /target:library /optimize+ /platform:anycpu /out:"OpsRoom.VPilotBridge.dll" /reference:"%VPILOT_DIR%\RossCarlson.Vatsim.Vpilot.Plugins.dll" /reference:System.Net.Http.dll /reference:System.Web.Extensions.dll "OPSROOM.VPilotBridge.cs"
if errorlevel 1 goto :fail
copy /y "OpsRoom.VPilotBridge.dll" "%VPILOT_DIR%\Plugins\OpsRoom.VPilotBridge.dll" >nul
if errorlevel 1 goto :fail
echo.
echo Installed:
echo   %VPILOT_DIR%\Plugins\OpsRoom.VPilotBridge.dll
echo.
echo Restart vPilot. OPS ROOM will then receive private messages and can send replies, Mode C and IDENT commands.
pause
exit /b 0
:fail
echo.
echo Build or installation failed. Close vPilot if it is currently using an older bridge, then retry.
pause
exit /b 1

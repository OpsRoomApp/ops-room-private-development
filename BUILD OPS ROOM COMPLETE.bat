@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Build OPS ROOM 0.25.50 Public Release Complete Package

echo ================================================================
echo OPS ROOM 0.25.50 Public Release build
echo Windows app + restored external MSFS 2024 Camera Bridge EXE
echo Native Charts/Camera WASM system activation is disabled by default
echo ================================================================
echo.

if not defined OPSROOM_BUILD_ROOT set "OPSROOM_BUILD_ROOT=%TEMP%\OR250"
if defined OPSROOM_OFFLINE_VENV (
  set "VENV_PY=%OPSROOM_OFFLINE_VENV%\Scripts\python.exe"
) else (
  set "VENV_PY=%OPSROOM_BUILD_ROOT%\venv\Scripts\python.exe"
)

call "BUILD CAMERA BRIDGE 2024.bat"
if errorlevel 1 goto :fail

call "BUILD WINDOWS APP ONLY.bat"
if errorlevel 1 goto :fail

if not defined OPSROOM_DIST_DIR set "OPSROOM_DIST_DIR=%~dp0dist"
set "DIST_DIR=%OPSROOM_DIST_DIR%"

if not exist "%DIST_DIR%\OPS ROOM\camera_bridge_2024" mkdir "%DIST_DIR%\OPS ROOM\camera_bridge_2024"
copy /y "%OPSROOM_BUILD_ROOT%\camera_bridge\OPS ROOM Camera Bridge 2024.exe" "%DIST_DIR%\OPS ROOM\camera_bridge_2024\OPS ROOM Camera Bridge 2024.exe" >nul
if errorlevel 1 goto :fail
copy /y "%OPSROOM_BUILD_ROOT%\camera_bridge\SimConnect.dll" "%DIST_DIR%\OPS ROOM\camera_bridge_2024\SimConnect.dll" >nul
if errorlevel 1 goto :fail
copy /y "%OPSROOM_BUILD_ROOT%\camera_bridge\OPS ROOM Camera Bridge 2024.exe" "%DIST_DIR%\OPS ROOM\OPS ROOM Camera Bridge 2024.exe" >nul
if errorlevel 1 goto :fail
copy /y "%OPSROOM_BUILD_ROOT%\camera_bridge\SimConnect.dll" "%DIST_DIR%\OPS ROOM\SimConnect.dll" >nul
if errorlevel 1 goto :fail

if exist "%DIST_DIR%\OPS ROOM\OPS ROOM Bridge" rmdir /s /q "%DIST_DIR%\OPS ROOM\OPS ROOM Bridge"
rem The experimental native WASM Charts/Camera package is intentionally not copied in the public release.
rem Browser charts must use browser-readable sources; camera uses the legacy external bridge provider.

echo.
echo Verifying complete public package contents...
rem A missing packaging interpreter must be a HARD FAILURE, never a silent skip: the
rem verification, static-validation and update-manifest steps below are release gates and
rem MUST run. (BUILD WINDOWS APP ONLY.bat creates this venv earlier in the complete build.)
if not exist "%VENV_PY%" (
  echo ERROR: Packaging Python was not found at "%VENV_PY%".
  echo The Windows app build must create the build virtual environment before the
  echo verification, static-validation and update-manifest steps can run.
  goto :fail
)
"%VENV_PY%" tools\verify_public_package.py --root "%DIST_DIR%\OPS ROOM" || goto :fail

echo.
echo Running successor static validation gate before packaging...
"%VENV_PY%" tools\validate_v0256_public_release.py || goto :fail
"%VENV_PY%" tools\verify_public_package.py --static-root "app\static" || goto :fail

if exist "%DIST_DIR%\OPS_ROOM_v0_25_48_Public_Windows_x64.zip" del "%DIST_DIR%\OPS_ROOM_v0_25_48_Public_Windows_x64.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -LiteralPath '%DIST_DIR%\OPS ROOM' -DestinationPath '%DIST_DIR%\OPS_ROOM_v0_25_48_Public_Windows_x64.zip' -Force -ErrorAction Stop" || goto :fail

"%VENV_PY%" tools\write_update_manifest.py --version 0.25.50 --channel stable --zip "%DIST_DIR%\OPS_ROOM_v0_25_48_Public_Windows_x64.zip" --out "%DIST_DIR%\update.json" || goto :fail
"%VENV_PY%" tools\validate_v0256_public_release.py --dist "%DIST_DIR%" || goto :fail

echo.
echo COMPLETE build ready:
echo   %DIST_DIR%\OPS ROOM\OPS ROOM.exe
echo   %DIST_DIR%\OPS ROOM\OPS ROOM Camera Bridge 2024.exe
echo   %DIST_DIR%\OPS_ROOM_v0_25_48_Public_Windows_x64.zip
echo.
echo Native WASM Charts/Camera is disabled by default in this build.
echo.
echo ===================================================
echo CHECKING FOR INNO SETUP 7 (ADDITIVE INSTALLER BUILD)
echo ===================================================

set "ISCC_PATH="
if exist "C:\Program Files\Inno Setup 7\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if defined ISCC_PATH (
    echo [INFO] Found Inno Setup Compiler at: "!ISCC_PATH!"
    echo [INFO] Compiling installer package...
    "!ISCC_PATH!" installer_script.iss
    if errorlevel 1 (
        echo [ERROR] Inno Setup compilation failed with exit code !ERRORLEVEL!.
        echo [ERROR] The portable dist\OPS ROOM folder is still valid.
    ) else (
        echo [SUCCESS] Installer generated at dist_installer\OPS_ROOM_Setup_v0_25_48.exe
    )
) else (
    echo [NOTICE] ISCC.exe not found at default paths. Skipping setup EXE generation.
    echo [NOTICE] Portable dist\OPS ROOM directory remains ready for use.
)
echo.
pause
exit /b 0

:fail
echo.
echo OPS ROOM 0.25.50 Public Release complete build failed. Review the first ERROR above.
pause
exit /b 1

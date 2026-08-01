@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Build OPS ROOM 0.25.47 Public Release Windows App Only

 echo ================================================================
 echo OPS ROOM 0.25.47 Public Release - Windows app only build
 echo ================================================================
 echo.

set "PYTHON_EXE="
call :find_python
if defined PYTHON_EXE goto :python_ready

echo Python 3.11 x64 is required to create the standalone Windows package.
echo The Python launcher may be installed, but no compatible Python 3.11 runtime was found.
echo.
where winget >nul 2>&1
if errorlevel 1 goto :manual_install

choice /C YN /N /M "Install Python 3.11 x64 for the current user with Winget now? [Y/N]: "
if errorlevel 2 goto :manual_install

echo.
echo Installing Python 3.11 x64...
winget install --exact --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo.
  echo Automatic Python installation failed.
  goto :manual_install
)

set "PYTHON_EXE="
call :find_python
if not defined PYTHON_EXE (
  echo.
  echo Python was installed, but this command window could not locate it yet.
  echo Close this window, then run this build file again.
  pause
  exit /b 1
)

goto :python_ready

:manual_install
echo.
echo Install Python 3.11 x64, then run this build file again:
echo   winget install --exact --id Python.Python.3.11 --scope user
echo.
echo During a manual python.org installation, enable the Python launcher.
pause
exit /b 1

:python_ready
"%PYTHON_EXE%" -c "import struct,sys; assert sys.version_info[:2] == (3,11), sys.version; assert struct.calcsize('P') * 8 == 64, '32-bit Python is unsupported'" >nul 2>&1
if errorlevel 1 (
  echo ERROR: The detected runtime is not Python 3.11 x64:
  echo   %PYTHON_EXE%
  goto :fail
)

echo Using Python:
"%PYTHON_EXE%" --version
 echo   %PYTHON_EXE%
echo.

if not defined OPSROOM_BUILD_ROOT set "OPSROOM_BUILD_ROOT=%TEMP%\OR250"
set "BUILD_DIR=%OPSROOM_BUILD_ROOT%\build"
if not defined OPSROOM_DIST_DIR set "OPSROOM_DIST_DIR=%~dp0dist"
set "DIST_DIR=%OPSROOM_DIST_DIR%"
set "VENV_DIR=%OPSROOM_BUILD_ROOT%\venv"
echo Using short intermediate build root:
echo   %OPSROOM_BUILD_ROOT%
echo.

if defined OPSROOM_OFFLINE_VENV set "VENV_DIR=%OPSROOM_OFFLINE_VENV%"
if not defined OPSROOM_OFFLINE_VENV if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if not exist "%OPSROOM_BUILD_ROOT%" mkdir "%OPSROOM_BUILD_ROOT%"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

if defined OPSROOM_OFFLINE_VENV (
  if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Offline packaging environment was not found at "%VENV_DIR%".
    goto :fail
  )
  echo Reusing local offline packaging environment:
  echo   %VENV_DIR%
) else (
  "%PYTHON_EXE%" -m venv "%VENV_DIR%" || goto :fail
  "%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel || goto :fail
  "%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements_build.txt || goto :fail
)

echo.
echo Installing optional FSUIPC7 IPC provider...
if defined OPSROOM_OFFLINE_VENV (
  "%VENV_DIR%\Scripts\python.exe" -c "import fsuipc" >nul 2>&1
  if errorlevel 1 echo WARNING: Optional FSUIPC package is not present in the offline build environment. The build will retain SimConnect fallback.
) else (
  "%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements_fsuipc_optional.txt
  if errorlevel 1 echo WARNING: Optional FSUIPC package was unavailable. The build will retain SimConnect fallback.
)

echo.
echo.
echo Injecting optional private managed API keys for this local build...
"%VENV_DIR%\Scripts\python.exe" tools\inject_managed_keys.py || goto :fail
echo.
echo Verifying RAAS audio module before packaging...
"%VENV_DIR%\Scripts\python.exe" -c "import pathlib, importlib; assert pathlib.Path('app/raas_audio.py').is_file(), 'app/raas_audio.py missing'; m=importlib.import_module('app.raas_audio'); print('RAAS audio import OK:', m.__file__)" || goto :fail

"%VENV_DIR%\Scripts\python.exe" -m PyInstaller --clean --noconfirm --workpath "%BUILD_DIR%" --distpath "%DIST_DIR%" OPS_ROOM.spec || goto :fail

if not exist "%DIST_DIR%\OPS ROOM\OPS ROOM.exe" (
  echo ERROR: OPS ROOM.exe was not created.
  goto :fail
)
if not exist "%DIST_DIR%\OPS ROOM\OPS ROOM Updater.exe" (
  echo ERROR: OPS ROOM Updater.exe was not created.
  goto :fail
)

echo.
echo Running packaged OPS ROOM self-test...
set "OPSROOM_SELF_TEST_OUT=%DIST_DIR%\opsroom_self_test.json"
"%DIST_DIR%\OPS ROOM\OPS ROOM.exe" --self-test
if errorlevel 1 (
  echo ERROR: Packaged OPS ROOM self-test failed.
  if exist "%DIST_DIR%\opsroom_self_test.json" type "%DIST_DIR%\opsroom_self_test.json"
  goto :fail
)
if not exist "%DIST_DIR%\opsroom_self_test.json" (
  echo ERROR: Packaged OPS ROOM did not write self-test output.
  goto :fail
)
findstr /C:"raas_audio_import_ok" "%DIST_DIR%\opsroom_self_test.json" >nul
if errorlevel 1 (
  echo ERROR: RAAS audio import self-test result is missing.
  type "%DIST_DIR%\opsroom_self_test.json"
  goto :fail
)


if not exist "%DIST_DIR%\OPS ROOM\_internal\SimConnect\SimConnect.dll" (
  echo ERROR: SimConnect.dll is missing from the standalone package.
  goto :fail
)
if not exist "%DIST_DIR%\OPS ROOM\_internal\app\data\stands.csv" (
  echo ERROR: stands.csv is missing from the standalone package.
  goto :fail
)
if not exist "%DIST_DIR%\OPS ROOM\_internal\app\assets\logos\AAL.png" (
  echo ERROR: The airline logo package is missing from the standalone package.
  goto :fail
)

if not exist "Announcements\Default\BoardingMusic.ogg" (
  echo ERROR: Source Announcements\Default\BoardingMusic.ogg is missing.
  goto :fail
)

if exist "%DIST_DIR%\OPS ROOM\Announcements" rmdir /s /q "%DIST_DIR%\OPS ROOM\Announcements"
xcopy /E /I /Y "Announcements" "%DIST_DIR%\OPS ROOM\Announcements" >nul
if errorlevel 1 (
  echo ERROR: Could not copy public Announcements folder into the release package.
  goto :fail
)
if not exist "%DIST_DIR%\OPS ROOM\Announcements\Default\BoardingMusic.ogg" (
  echo ERROR: Public default BoardingMusic announcement is missing from the standalone package.
  goto :fail
)

for %%F in (
  "README.txt"
  "RELEASE_NOTES.txt"
  "BLACK_BOX_DESIGN_CREDITS.md"
  "THIRD_PARTY_NOTICES.txt"
) do if exist "%%~F" copy /y "%%~F" "%DIST_DIR%\OPS ROOM\%%~nxF" >nul

echo.
echo Verifying public package contents...
"%VENV_DIR%\Scripts\python.exe" tools\verify_public_package.py --root "%DIST_DIR%\OPS ROOM" || goto :fail

rem Public release folder cleanup: keep user-facing dist clean.
rem Developer/admin files such as build validation notes, Google Apps Script setup,
rem old release notes and helper batch files are intentionally not copied.
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -LiteralPath '%DIST_DIR%\OPS ROOM' -DestinationPath '%DIST_DIR%\OPS_ROOM_v0_25_47_Public_Windows_x64.zip' -Force -ErrorAction Stop" || goto :fail

"%VENV_DIR%\Scripts\python.exe" tools\write_update_manifest.py --version 0.25.47 --channel stable --zip "%DIST_DIR%\OPS_ROOM_v0_25_47_Public_Windows_x64.zip" --out "%DIST_DIR%\update.json" || goto :fail

echo.
echo Build complete:
echo   %DIST_DIR%\OPS ROOM\OPS ROOM.exe
echo   %DIST_DIR%\OPS_ROOM_v0_25_47_Public_Windows_x64.zip
echo   %DIST_DIR%\OPS_ROOM_v0_25_47_Public_Windows_x64.zip.sha256
echo   %DIST_DIR%\update.json
echo.
pause
exit /b 0

:find_python
for /f "usebackq delims=" %%P in (`py -3.11 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if defined PYTHON_EXE if exist "%PYTHON_EXE%" exit /b 0
set "PYTHON_EXE="

for %%P in (
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%ProgramFiles%\Python311\python.exe"
  "%ProgramFiles%\Python 3.11\python.exe"
) do (
  if not defined PYTHON_EXE if exist "%%~P" set "PYTHON_EXE=%%~P"
)
if defined PYTHON_EXE exit /b 0

for /f "delims=" %%P in ('where python 2^>nul') do (
  if not defined PYTHON_EXE (
    "%%P" -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2] == (3,11) and struct.calcsize('P') * 8 == 64 else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=%%~P"
  )
)
exit /b 0

:fail
echo.
echo Build failed. Review the first ERROR above.
pause
exit /b 1

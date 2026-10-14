@echo off
set "VENV=C:\Users\wuyijun\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PROJ=%~dp0"
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"
cd /d "%PROJ%"

if not exist "%PROJ%\prompt_manager\state" mkdir "%PROJ%\prompt_manager\state"

REM Step 1: ask any running instance to stop itself via HTTP (safe, no process kill)
"%VENV%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8899/api/shutdown', timeout=3)" >nul 2>&1
timeout /t 3 >nul 2>&1

REM Step 2: check if port is still served by an old instance
"%VENV%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8899/api/version', timeout=3)" >nul 2>&1
if %errorlevel%==0 (
  echo [info] An older instance is still running and cannot auto-stop.
  echo [info] Please CLOSE the previous black window, then double-click this bat again.
  start "" "http://127.0.0.1:8899/"
  pause
  exit /b
)

if not exist "%VENV%" (
  echo [ERROR] Python not found at: %VENV%
  echo [ERROR] Please check your WorkBuddy managed python installation.
  pause
  exit /b
)

echo Starting prompt_manager server (fresh)... close this window to stop.
echo.
"%VENV%" -m prompt_manager.server
echo.
echo [server exited] exit code=%errorlevel%
echo If there was an error above, screenshot this window and send to assistant.
pause

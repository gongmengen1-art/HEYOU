@echo off
REM ============================================================
REM  HEYOU - Windows one-click SETUP + RUN
REM  On a FRESH Windows 10, just double-click this file. It will:
REM    [1] install uv (if missing)      [2] create config.yaml (if missing)
REM    [3] install Python 3.11 + deps   [4] start the server
REM  Everything (incl. errors / tracebacks) is logged to logs\run_<ts>.log
REM  When anything breaks, send me that log file.
REM ============================================================
setlocal enableextensions
chcp 65001 >nul
cd /d "%~dp0"

REM Force UTF-8 so Chinese / arrows in output never crash on a GBK console
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

if not exist "logs" mkdir "logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "DT=%%I"
if not defined DT set "DT=run"
set "LOGFILE=logs\run_%DT%.log"

echo ============================================================ > "%LOGFILE%"
echo HEYOU setup+run  %DT% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo [env] cwd=%CD% >> "%LOGFILE%"
echo [env] codepage=UTF-8, python UTF-8 mode on >> "%LOGFILE%"

echo(
echo   ============================================
echo    HEYOU  -  Windows setup ^& run
echo    Log: %LOGFILE%
echo   ============================================
echo(

REM ---------- [1] ensure uv ----------
echo [1/4] Checking uv package manager...
echo [1/4] check uv >> "%LOGFILE%"
where uv >nul 2>&1
if not errorlevel 1 goto have_uv
echo       uv not found -- installing from astral.sh (needs internet)...
echo [step] installing uv via astral install.ps1 >> "%LOGFILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; irm https://astral.sh/uv/install.ps1 | iex" >> "%LOGFILE%" 2>&1
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>&1
if errorlevel 1 (
  echo   ERROR: uv install failed. See the log.
  echo [error] uv not found after install >> "%LOGFILE%"
  goto fail
)
:have_uv
uv --version >> "%LOGFILE%" 2>&1
for /f "delims=" %%V in ('uv --version 2^>^&1') do echo       uv OK: %%V

REM ---------- [2] ensure config.yaml ----------
echo [2/4] Checking config.yaml...
if exist "config.yaml" (
  echo       config.yaml present
  echo [env] config.yaml present >> "%LOGFILE%"
) else (
  copy /y "config.example.yaml" "config.yaml" >nul
  echo       created config.yaml from example ^(generation=mock; edit later for RunningHub key^)
  echo [init] created config.yaml from config.example.yaml >> "%LOGFILE%"
)

REM ---------- [3] python + dependencies ----------
echo [3/4] Installing Python 3.11 + dependencies...
echo       first run downloads several hundred MB; please wait, this can take a few minutes
echo [step] uv python install 3.11 >> "%LOGFILE%"
uv python install 3.11 >> "%LOGFILE%" 2>&1
echo [step] uv sync >> "%LOGFILE%"
uv sync >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo   ERROR: dependency install failed [uv sync]. Last 40 log lines:
  powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGFILE%' -Tail 40"
  echo [error] uv sync failed >> "%LOGFILE%"
  goto fail
)
echo       dependencies installed.

REM ---------- [4] run ----------
echo [4/4] Starting server...  open http://127.0.0.1:8000
echo       * window stays here quietly = server RUNNING (good). Ctrl+C to stop.
echo       * window returns to a prompt = startup FAILED; the error is in the log.
echo ------------------------------------------------------------ >> "%LOGFILE%"
echo [step] starting server >> "%LOGFILE%"
uv run python scripts\run_server.py >> "%LOGFILE%" 2>&1
set "CODE=%ERRORLEVEL%"
echo [exit] server exit code %CODE% >> "%LOGFILE%"

echo(
echo   Server stopped ^(exit %CODE%^). Full log:
echo     %LOGFILE%
echo   -^> send me that file to debug.
echo(
pause
exit /b %CODE%

:fail
echo(
echo   Setup failed. Send me this log to debug:
echo     %LOGFILE%
echo(
pause
exit /b 1

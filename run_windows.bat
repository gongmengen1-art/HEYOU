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
REM Open the console to the LAN: bind 0.0.0.0 so other devices can reach it by this PC's IP.
set "HEYOU_HOST=0.0.0.0"

REM Best-effort: detect this PC's LAN IPv4 (the adapter that has a default gateway and is Up)
set "LANIP="
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-NetIPConfiguration ^| Where-Object {$_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up'} ^| ForEach-Object { $_.IPv4Address.IPAddress } ^| Select-Object -First 1)"`) do set "LANIP=%%A"
if not defined LANIP set "LANIP=<this-PC-LAN-IP>"

REM Allow inbound TCP 8000 through Windows Firewall so LAN clients can connect
netsh advfirewall firewall show rule name="HEYOU console 8000" >nul 2>&1
if errorlevel 1 (
  echo [step] add firewall rule TCP 8000 inbound >> "%LOGFILE%"
  netsh advfirewall firewall add rule name="HEYOU console 8000" dir=in action=allow protocol=TCP localport=8000 >> "%LOGFILE%" 2>&1
  if errorlevel 1 (
    echo       NOTE: firewall rule NOT added -- run this .bat as Administrator ONCE to allow LAN access.
    echo [warn] firewall rule add failed ^(needs admin^) >> "%LOGFILE%"
  ) else (
    echo       firewall opened: TCP 8000 inbound allowed.
  )
) else (
  echo       firewall rule already present ^(TCP 8000^).
)

echo [4/4] Starting server...
echo(
echo   ============================================
echo    Console URLs:
echo      this PC : http://127.0.0.1:8000
echo      LAN     : http://%LANIP%:8000
echo    Open the LAN URL from any device on the same network.
echo    ^(No login yet -- only expose this on a trusted network.^)
echo   ============================================
echo(
echo       * live server logs print in THIS window (same as run_server.py). Ctrl+C to stop.
echo       * window keeps printing logs = server RUNNING (good).
echo       * window returns to a prompt = startup FAILED; the error is above and in the log.
echo ------------------------------------------------------------ >> "%LOGFILE%"
echo [step] starting server (HEYOU_HOST=%HEYOU_HOST%) -- runtime logs -^> data\logs\heyou.log >> "%LOGFILE%"

REM Run the server with NO redirect so its output streams live in this window, exactly like
REM `uv run python scripts\run_server.py`. The app also writes the full runtime log (clean
REM UTF-8, self-rotating) to data\logs\heyou.log, and startup crashes are captured there too.
uv run python scripts\run_server.py
set "CODE=%ERRORLEVEL%"
echo [exit] server exit code %CODE% >> "%LOGFILE%"

echo(
echo   Server stopped ^(exit %CODE%^).
echo   Setup log:   %LOGFILE%
echo   Runtime log: data\logs\heyou.log
echo   -^> send me those to debug.
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

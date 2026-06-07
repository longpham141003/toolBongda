@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul || (
  echo Khong tim thay Python launcher.
  pause
  exit /b 1
)

start "Visual CapCut API" /min py -3.13 -m app.web_server

for /l %%i in (1,1,30) do (
  powershell -NoProfile -Command "try { if ((Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/api/health -TimeoutSec 1).StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
  if not errorlevel 1 goto ready
  timeout /t 1 /nobreak >nul
)

echo API khong khoi dong duoc.
pause
exit /b 1

:ready
start "" http://127.0.0.1:8765
endlocal

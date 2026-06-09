@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul || (
  echo Khong tim thay Python launcher.
  pause
  exit /b 1
)

if not exist "settings.json" (
  copy /Y "settings.example.json" "settings.json" >nul
)

py -3.13 -m pip show fastapi >nul 2>nul || (
  echo Dang cai dependency backend...
  py -3.13 -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Cai dependency backend that bai.
    pause
    exit /b 1
  )
)

set "PW_OK="
for /d %%D in ("%LOCALAPPDATA%\ms-playwright\chromium-*") do set "PW_OK=1"
if not defined PW_OK (
  echo Dang cai Chromium cho Playwright tim anh...
  py -3.13 -m playwright install chromium
  if errorlevel 1 (
    echo Cai Chromium cho Playwright that bai.
    pause
    exit /b 1
  )
)

if not exist "kokoro-tts-local\app.py" (
  echo Thieu thu muc kokoro-tts-local. Hay pull lai day du repo.
  pause
  exit /b 1
)

if not exist "kokoro-tts-local\.venv\Scripts\python.exe" (
  echo Lan dau chay: dang cai Kokoro local...
  powershell -NoProfile -ExecutionPolicy Bypass -File "kokoro-tts-local\setup.ps1"
  if errorlevel 1 (
    echo Cai Kokoro that bai.
    pause
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$owners = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($owner in $owners) { try { Stop-Process -Id $owner -Force -ErrorAction Stop } catch {} }"
timeout /t 1 /nobreak >nul

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

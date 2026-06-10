@echo off
setlocal
cd /d "%~dp0"
title Visual CapCut Studio

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_visual_capcut.ps1"
if errorlevel 1 (
  echo.
  echo Khoi dong tool that bai. Hay chup man hinh loi nay gui cho nguoi phu trach.
  pause
  exit /b 1
)

endlocal

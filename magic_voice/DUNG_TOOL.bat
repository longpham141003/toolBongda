@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Tat Chatterbox TTS
echo Dang tat Chatterbox TTS (tat ca tien trinh)...

rem 1) Diet moi python.exe chay tu thu muc tool hien tai
set "TOOL_DIR=%~dp0"
powershell -NoProfile -Command "$root = '%TOOL_DIR:\=\\%'; $p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like ('*' + $root + '*') }; $n = ($p | Measure-Object).Count; $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Write-Host (\"Da tat \" + $n + \" tien trinh.\")"

rem 2) Diet not bat ky tien trinh nao con giu cong 7860/7861
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7860 :7861" ^| findstr "LISTENING"') do taskkill /f /pid %%a >nul 2>&1

echo Da tat xong hoan toan.
timeout /t 3 >nul

@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Sua loi Chatterbox Tool

echo ====================================================
echo    SUA LOI TU DONG (can mang internet)
echo ====================================================
echo.
echo [1/2] Cai thu vien Whisper con thieu...
"venv\Scripts\python.exe" -m pip install faster-whisper
if errorlevel 1 (
    echo LOI khi cai faster-whisper. Kiem tra mang roi chay lai file nay.
    pause
    exit /b 1
)
echo.
echo [2/2] Kiem tra lai toan bo...
"venv\Scripts\python.exe" kiemtra.py > loi_log.txt 2>&1
type loi_log.txt
echo.
echo Neu o tren co dong "UNG DUNG NAP THANH CONG" thi anh chay  2_CHAY_TOOL.bat  duoc roi.
echo Neu van bao loi, gui file loi_log.txt cho Claude.
pause

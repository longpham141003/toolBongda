@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Chatterbox TTS - Dang chay

if not exist "venv\Scripts\python.exe" (
    echo Tool chua duoc cai dat. Anh hay chay file  1_CAI_DAT.bat  truoc nhe.
    pause
    exit /b 1
)

echo ====================================================
echo    CHATTERBOX TTS dang khoi dong...
echo.
echo  - LAN DAU chay: tool se tu tai model AI (~4GB),
echo    co the mat 10-30 phut tuy mang. Cu de yen.
echo  - Khi san sang, trinh duyet se TU MO giao dien.
echo  - DUNG TAT cua so den nay trong luc dang dung tool.
echo  - Muon tat tool: dong cua so nay la xong.
echo ====================================================
echo.

rem Tu mo giao dien dang APP (cua so rieng, khong phai tab trinh duyet) sau 20 giay
start "" /min cmd /c "timeout /t 20 /nobreak >nul & (start msedge --app=http://127.0.0.1:7860 || start chrome --app=http://127.0.0.1:7860 || start http://127.0.0.1:7860)"

"venv\Scripts\python.exe" app.py

echo.
echo Tool da dong. Bam phim bat ky de thoat.
pause

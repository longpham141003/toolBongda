@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Kiem tra loi Chatterbox Tool

if not exist "venv\Scripts\python.exe" (
    echo KHONG TIM THAY moi truong venv - tuc la buoc cai dat CHUA xong.
    echo Anh hay chay lai  1_CAI_DAT.bat  va cho den khi thay "CAI DAT HOAN TAT".
    echo Neu cai dat bao loi, chup man hinh loi gui cho Claude.
    pause
    exit /b 1
)

echo Dang kiem tra, cho khoang 1-2 phut...
"venv\Scripts\python.exe" kiemtra.py > loi_log.txt 2>&1
type loi_log.txt
echo.
echo Ket qua da luu vao file  loi_log.txt  (cung thu muc nay).
echo Anh chup man hinh nay HOAC gui file loi_log.txt cho Claude xem nhe.
pause

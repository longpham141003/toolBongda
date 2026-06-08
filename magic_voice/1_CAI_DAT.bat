@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Cai dat Chatterbox TTS

echo ====================================================
echo    CAI DAT CHATTERBOX TTS  (chi can chay 1 lan)
echo    Qua trinh mat khoang 10-20 phut, can co mang.
echo ====================================================
echo.

rem ---------- Buoc 1: Tim Python 3.11 / 3.10 ----------
echo [Buoc 1/4] Kiem tra Python...
set "PYCMD="
py -3.11 --version >nul 2>&1 && set "PYCMD=py -3.11"
if not defined PYCMD py -3.10 --version >nul 2>&1 && set "PYCMD=py -3.10"

if not defined PYCMD (
    echo   Python chua co tren may. Dang tu dong cai Python 3.11...
    winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
    py -3.11 --version >nul 2>&1 && set "PYCMD=py -3.11"
)

if not defined PYCMD (
    echo.
    echo   KHONG THE TU CAI PYTHON.
    echo   Anh hay vao trang web vua mo, bam "Download", cai dat
    echo   ^(nho tich o "Add python.exe to PATH"^), roi chay lai file nay.
    start https://www.python.org/downloads/release/python-31110/
    pause
    exit /b 1
)
echo   Da tim thay Python: %PYCMD%
echo.

rem ---------- Buoc 2: Tao moi truong rieng ----------
echo [Buoc 2/4] Tao moi truong Python rieng cho tool...
if not exist "venv\Scripts\python.exe" %PYCMD% -m venv venv
if not exist "venv\Scripts\python.exe" (
    echo   LOI: khong tao duoc moi truong venv.
    pause
    exit /b 1
)
set "VPY=venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet
echo   Xong.
echo.

rem ---------- Buoc 3: Kiem tra card do hoa ----------
echo [Buoc 3/4] Kiem tra card do hoa NVIDIA...
set "TORCH_URL=https://download.pytorch.org/whl/cpu"
set "GPUMODE=CPU (KHONG co card NVIDIA - tao giong se CHAM)"
nvidia-smi -L >nul 2>&1 && set "TORCH_URL=https://download.pytorch.org/whl/cu118" && set "GPUMODE=GPU NVIDIA (tao giong NHANH)"
echo   Che do: %GPUMODE%
echo.

rem ---------- Buoc 4: Cai thu vien ----------
echo [Buoc 4/4] Dang tai va cai thu vien AI (phan nay lau nhat, ~2-5GB)...
"%VPY%" -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url %TORCH_URL%
if errorlevel 1 (
    echo   LOI khi cai PyTorch. Kiem tra mang roi chay lai file nay.
    pause
    exit /b 1
)
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo   LOI khi cai thu vien. Kiem tra mang roi chay lai file nay.
    pause
    exit /b 1
)
echo.

"%VPY%" -c "import torch; print('Kiem tra: PyTorch OK - Dung GPU:', torch.cuda.is_available())"
echo.
echo ====================================================
echo    CAI DAT HOAN TAT!
echo    Tu nay ve sau: chi can mo file  2_CHAY_TOOL.bat
echo ====================================================
pause

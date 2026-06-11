@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title MagicVoice TTS Studio - Cai Dat Tu Dong
cd /d "%~dp0"

echo.
echo  ==========================================
echo  MagicVoice TTS Studio - Cai Dat Tu Dong
echo  ==========================================
echo.

:: =============================================
:: BUOC 1: Tim Python 3.11
:: =============================================
echo  [1/6] Kiem tra Python 3.11...
set PY311=

py -3.11 --version >nul 2>&1 && set "PY311=py -3.11" && goto :py_found

for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "C:\Python311\python.exe"
    "C:\Program Files\Python311\python.exe"
    "%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe"
    "D:\Python311\python.exe"
) do (
    if exist %%p (
        %%p --version >nul 2>&1
        if !errorlevel!==0 set "PY311=%%p" & goto :py_found
    )
)

echo  Chua co Python 3.11 - Dang tai...
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "PY_SETUP=%TEMP%\python311_setup.exe"
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%PY_URL%','%PY_SETUP%')}" >nul 2>&1
if exist "%PY_SETUP%" (
    echo  Dang cai Python 3.11...
    "%PY_SETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
    del "%PY_SETUP%" >nul 2>&1
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
    py -3.11 --version >nul 2>&1 && set "PY311=py -3.11" && goto :py_found
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY311=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto :py_found
)
echo  KHONG CAI DUOC PYTHON!
pause & exit /b 1

:py_found
for /f "tokens=*" %%v in ('%PY311% --version 2^>^&1') do echo  %%v - OK

:: =============================================
:: BUOC 2: pip
:: =============================================
echo.
echo  [2/6] Nang cap pip...
%PY311% -m pip install --upgrade pip --progress-bar on --no-cache-dir 2>nul

:: =============================================
:: BUOC 3: PyTorch - Tu dong chon dung CUDA
:: =============================================
echo.
echo  [3/6] Cai PyTorch dung GPU...

:: Phat hien GPU NVIDIA va lay driver version
set GPU_GEN=none
nvidia-smi >nul 2>&1
if %errorlevel%==0 (
    :: Co GPU NVIDIA - phat hien generation
    for /f "tokens=*" %%g in ('nvidia-smi --query-gpu=name --format=csv^,noheader 2^>nul') do (
        set GPU_NAME=%%g
        echo  GPU phat hien: %%g
    )
    :: RTX 5000 series can cu128
    echo !GPU_NAME! | findstr /i "5090 5080 5070 5060 5050" >nul 2>&1
    if !errorlevel!==0 set GPU_GEN=5xxx
    :: RTX 4000 series
    echo !GPU_NAME! | findstr /i "4090 4080 4070 4060 4050" >nul 2>&1
    if !errorlevel!==0 set GPU_GEN=4xxx
    :: RTX 3000 series
    echo !GPU_NAME! | findstr /i "3090 3080 3070 3060 3050" >nul 2>&1
    if !errorlevel!==0 set GPU_GEN=3xxx
    :: RTX 2000 hoac cu hon
    echo !GPU_NAME! | findstr /i "2080 2070 2060 1080 1070 1060" >nul 2>&1
    if !errorlevel!==0 set GPU_GEN=2xxx
)

:: Xoa torch cu neu co (de cai lai dung version)
%PY311% -c "import torch; assert torch.cuda.is_available()" >nul 2>&1
if !errorlevel!==0 (
    echo  PyTorch CUDA da co va hoat dong - giu nguyen!
    goto :step4
)

:: Cai PyTorch dung theo GPU generation
if "!GPU_GEN!"=="5xxx" (
    echo  RTX 5000 series - Cai PyTorch CUDA 12.8 Nightly...
    %PY311% -m pip uninstall torch torchvision torchaudio -y --progress-bar on --no-cache-dir >nul 2>&1
    %PY311% -m pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128 --progress-bar on --no-cache-dir
    %PY311% -c "import torch; assert torch.cuda.is_available()" >nul 2>&1
    if !errorlevel!==0 ( echo  RTX 5000 CUDA 12.8: OK! & goto :step4 )
)

if "!GPU_GEN!"=="4xxx" (
    echo  RTX 4000 series - Cai PyTorch CUDA 12.1...
    %PY311% -m pip uninstall torch torchvision torchaudio -y --progress-bar on --no-cache-dir >nul 2>&1
    %PY311% -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121 --progress-bar on --no-cache-dir
    %PY311% -c "import torch; assert torch.cuda.is_available()" >nul 2>&1
    if !errorlevel!==0 ( echo  RTX 4000 CUDA 12.1: OK! & goto :step4 )
    :: Fallback cu124
    %PY311% -m pip uninstall torch torchvision torchaudio -y --progress-bar on --no-cache-dir >nul 2>&1
    %PY311% -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 --progress-bar on --no-cache-dir
    %PY311% -c "import torch; assert torch.cuda.is_available()" >nul 2>&1
    if !errorlevel!==0 ( echo  RTX 4000 CUDA 12.4: OK! & goto :step4 )
)

if "!GPU_GEN!"=="3xxx" (
    echo  RTX 3000 series - Cai PyTorch CUDA 12.1...
    %PY311% -m pip uninstall torch torchvision torchaudio -y --progress-bar on --no-cache-dir >nul 2>&1
    %PY311% -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121 --progress-bar on --no-cache-dir
    %PY311% -c "import torch; assert torch.cuda.is_available()" >nul 2>&1
    if !errorlevel!==0 ( echo  RTX 3000 CUDA 12.1: OK! & goto :step4 )
)

if "!GPU_GEN!"=="2xxx" (
    echo  RTX 2000/GTX series - Cai PyTorch CUDA 11.8...
    %PY311% -m pip uninstall torch torchvision torchaudio -y --progress-bar on --no-cache-dir >nul 2>&1
    %PY311% -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu118 --progress-bar on --no-cache-dir
    %PY311% -c "import torch; assert torch.cuda.is_available()" >nul 2>&1
    if !errorlevel!==0 ( echo  RTX 2000 CUDA 11.8: OK! & goto :step4 )
)

:: Fallback: thu toan bo CUDA versions
if not "!GPU_GEN!"=="none" (
    echo  Thu CUDA 12.4 tong quat...
    %PY311% -m pip uninstall torch torchvision torchaudio -y --progress-bar on --no-cache-dir >nul 2>&1
    %PY311% -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 --progress-bar on --no-cache-dir
    %PY311% -c "import torch; assert torch.cuda.is_available()" >nul 2>&1
    if !errorlevel!==0 ( echo  CUDA 12.4: OK! & goto :step4 )
    echo  Thu CUDA 12.6...
    %PY311% -m pip uninstall torch torchvision torchaudio -y --progress-bar on --no-cache-dir >nul 2>&1
    %PY311% -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126 --progress-bar on --no-cache-dir
    %PY311% -c "import torch; assert torch.cuda.is_available()" >nul 2>&1
    if !errorlevel!==0 ( echo  CUDA 12.6: OK! & goto :step4 )
)

:: CPU fallback
echo  Khong co GPU hoac CUDA - Cai CPU version...
%PY311% -m pip uninstall torch torchvision torchaudio -y --progress-bar on --no-cache-dir >nul 2>&1
%PY311% -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --progress-bar on --no-cache-dir
echo  PyTorch CPU: OK

:step4
:: =============================================
:: BUOC 4: Thu vien
:: =============================================
echo.
echo  [4/6] Cai thu vien...

%PY311% -c "import omnivoice" >nul 2>&1
if !errorlevel!==0 (
    echo  Cai MagicVoice Engine lan 1...
    %PY311% -m pip install omnivoice --no-cache-dir --progress-bar on --no-cache-dir
    %PY311% -c "import omnivoice" >nul 2>&1
    if !errorlevel!==0 (
        echo  Cai MagicVoice Engine lan 2...
        %PY311% -m pip install omnivoice --no-cache-dir --upgrade --progress-bar on --no-cache-dir
        %PY311% -c "import omnivoice" >nul 2>&1
        if !errorlevel!==0 (
            echo  Cai MagicVoice Engine lan 3...
            pip install omnivoice --no-cache-dir --progress-bar on --no-cache-dir
        ) else echo  MagicVoice Engine: OK
    ) else echo  MagicVoice Engine: OK
) else echo  MagicVoice Engine: Da co - OK

%PY311% -c "import firebase_admin" >nul 2>&1
if !errorlevel!==0 (
    echo  Cai firebase-admin lan 1...
    %PY311% -m pip install firebase-admin --no-cache-dir --progress-bar on --no-cache-dir
    %PY311% -c "import firebase_admin" >nul 2>&1
    if !errorlevel!==0 (
        echo  Cai firebase-admin lan 2...
        %PY311% -m pip install firebase-admin --upgrade --no-cache-dir --progress-bar on --no-cache-dir
        %PY311% -c "import firebase_admin" >nul 2>&1
        if !errorlevel!==0 (
            echo  Cai firebase-admin lan 3...
            pip install firebase-admin --no-cache-dir --progress-bar on --no-cache-dir
        ) else echo  firebase-admin: OK
    ) else echo  firebase-admin: OK
) else echo  firebase-admin: Da co - OK

for %%m in (edge_tts soundfile sounddevice pyaudiowpatch scipy pydub psutil requests numpy) do (
    %PY311% -c "import %%m" >nul 2>&1
    if !errorlevel!==0 ( echo  Cai %%m... & %PY311% -m pip install %%m --progress-bar on --no-cache-dir ) else echo  %%m: OK
)

%PY311% -c "from PIL import Image" >nul 2>&1
if !errorlevel!==0 ( %PY311% -m pip install Pillow --progress-bar on --no-cache-dir )

%PY311% -c "import imageio_ffmpeg" >nul 2>&1
if !errorlevel!==0 ( echo  Cai imageio-ffmpeg... & %PY311% -m pip install imageio-ffmpeg --progress-bar on --no-cache-dir ) else echo  imageio-ffmpeg: OK

:: =============================================
:: BUOC 5: ffmpeg
:: =============================================
echo.
echo  [5/6] Kiem tra ffmpeg...

if exist "%~dp0ffmpeg_portable\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe" (
    echo  ffmpeg portable: OK
    goto :ffmpeg_done
)

%PY311% -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())" >nul 2>&1
if !errorlevel!==0 (
    echo  imageio-ffmpeg: OK
    goto :ffmpeg_done
)

echo  Thu tai ffmpeg portable...
mkdir "%~dp0ffmpeg_portable" 2>nul
set "FFZIP=%TEMP%\ffmpeg.zip"
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip','%FFZIP%')}" >nul 2>&1
if exist "%FFZIP%" (
    powershell -Command "Expand-Archive -Path '%FFZIP%' -DestinationPath '%~dp0ffmpeg_portable' -Force" >nul 2>&1
    del "%FFZIP%" >nul 2>&1
    echo  ffmpeg portable: OK
) else echo  [!] ffmpeg chua cai duoc - ghi am se luu WAV

:ffmpeg_done

:: =============================================
:: BUOC 6: Shortcut Desktop
:: =============================================
echo.
echo  [6/6] Tao shortcut Desktop...
powershell -NoProfile -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\MagicVoice TTS Studio.lnk');$s.TargetPath='%~dp0Chay_MagicVoice.bat';$s.WorkingDirectory='%~dp0';$s.IconLocation='%~dp0MagicVoice.ico';$s.Save()" >nul 2>&1
echo  Shortcut: OK

:: =============================================
:: KIEM TRA KET QUA
:: =============================================
echo.
echo  ==========================================
echo  Ket qua cai dat:
echo  ==========================================
%PY311% -c "import torch; cuda=torch.cuda.is_available(); gpu=torch.cuda.get_device_name(0) if cuda else 'CPU'; print(f'  PyTorch: {torch.__version__} | GPU: {gpu}')" 2>nul
%PY311% -c "import omnivoice; print('  MagicVoice Engine : OK')" 2>nul
%PY311% -c "import firebase_admin; print('  firebase-admin    : OK')" 2>nul
%PY311% -c "import edge_tts; print('  edge-tts          : OK')" 2>nul
%PY311% -c "import soundfile; print('  soundfile         : OK')" 2>nul
%PY311% -c "import pyaudiowpatch; print('  pyaudiowpatch     : OK')" 2>nul
%PY311% -c "import sounddevice; print('  sounddevice       : OK')" 2>nul
%PY311% -c "import scipy; print('  scipy             : OK')" 2>nul
%PY311% -c "import imageio_ffmpeg; print('  imageio-ffmpeg    : OK')" 2>nul
echo  ==========================================
echo.
echo  Dang mo MagicVoice TTS Studio...
timeout /t 3 /nobreak >nul

if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" (
    start "" "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" "%~dp0magicvoice_gui.py"
    goto :end
)
if exist "C:\Python311\pythonw.exe" (
    start "" "C:\Python311\pythonw.exe" "%~dp0magicvoice_gui.py"
    goto :end
)
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python311\pythonw.exe" (
    start "" "%USERPROFILE%\AppData\Local\Programs\Python\Python311\pythonw.exe" "%~dp0magicvoice_gui.py"
    goto :end
)
start "" "%~dp0Chay_MagicVoice.bat"

:end
timeout /t 3 /nobreak >nul
exit

@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion

set PYW=
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
    "C:\Python311\pythonw.exe"
    "C:\Program Files\Python311\pythonw.exe"
    "%USERPROFILE%\AppData\Local\Programs\Python\Python311\pythonw.exe"
) do (
    if exist %%~p (
        set "PYW=%%~p"
        goto :found
    )
)
py -3.11 --version >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%p in ('py -3.11 -c "import sys;print(sys.executable)"') do (
        set "PYEXE=%%p"
        set "PYW=!PYEXE:python.exe=pythonw.exe!"
        if not exist "!PYW!" set "PYW=!PYEXE!"
    )
    goto :found
)
echo Python 3.11 chua duoc cai! Chay CaiDat_MagicVoice.bat truoc.
pause
exit /b 1

:found
start "" "!PYW!" "%~dp0magicvoice_gui.py"
exit

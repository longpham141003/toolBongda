@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Tao shortcut Desktop

echo Dang tao 2 shortcut tren Desktop...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut(\"$d\Chatterbox TTS.lnk\"); $s.TargetPath = '%~dp0CHAY_NGAM.vbs'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%SystemRoot%\System32\SndVol.exe,0'; $s.Description = 'Mo Chatterbox TTS (chay ngam, khong cua so den)'; $s.Save(); $t = $ws.CreateShortcut(\"$d\Tat Chatterbox.lnk\"); $t.TargetPath = '%~dp0DUNG_TOOL.bat'; $t.WorkingDirectory = '%~dp0'; $t.IconLocation = '%SystemRoot%\System32\shell32.dll,27'; $t.Description = 'Tat han Chatterbox TTS'; $t.Save()"

if errorlevel 1 (
    echo LOI: Khong tao duoc shortcut. Anh chup man hinh gui Claude.
) else (
    echo XONG! Desktop co 2 bieu tuong:
    echo   - "Chatterbox TTS"  : mo tool ^(khong con cua so den^)
    echo   - "Tat Chatterbox"  : tat han tool khi dung xong
)
pause

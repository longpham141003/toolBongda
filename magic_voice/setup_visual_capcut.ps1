$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Find-PythonVoice {
    $candidates = @(
        @("py", "-3.11"),
        @("py", "-3.10"),
        @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", ""),
        @("C:\Python311\python.exe", ""),
        @("C:\Program Files\Python311\python.exe", ""),
        @("$env:USERPROFILE\AppData\Local\Programs\Python\Python311\python.exe", ""),
        @("$env:LOCALAPPDATA\Programs\Python\Python310\python.exe", ""),
        @("C:\Python310\python.exe", ""),
        @("C:\Program Files\Python310\python.exe", ""),
        @("$env:USERPROFILE\AppData\Local\Programs\Python\Python310\python.exe", "")
    )
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $arg = $candidate[1]
        try {
            if ($arg) {
                & $exe $arg -c "import sys; raise SystemExit(0 if sys.version_info[:2] in [(3, 11), (3, 10)] else 1)" *> $null
            } else {
                if (-not (Test-Path -LiteralPath $exe)) { continue }
                & $exe -c "import sys; raise SystemExit(0 if sys.version_info[:2] in [(3, 11), (3, 10)] else 1)" *> $null
            }
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {}
    }
    return $null
}

$py = Find-PythonVoice
if (-not $py) {
    Write-Host "Chua co Python 3.11/3.10, dang tai va cai Python 3.11..."
    try {
        winget install --id Python.Python.3.11 -e --scope user --silent --accept-package-agreements --accept-source-agreements
    } catch {
        Write-Host "winget khong cai duoc Python 3.11, thu download installer..."
    }
    $env:PATH = "$env:LOCALAPPDATA\Programs\Python\Python311;$env:LOCALAPPDATA\Programs\Python\Python311\Scripts;$env:PATH"
    $py = Find-PythonVoice
    if (-not $py) {
        $url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
        $installer = Join-Path $env:TEMP "python311_setup.exe"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
        if (-not (Test-Path -LiteralPath $installer) -or (Get-Item -LiteralPath $installer).Length -lt 1000000) {
            throw "Tai Python installer that bai: $installer"
        }
        $proc = Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1" -Wait -PassThru -WindowStyle Hidden
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        if ($proc.ExitCode -ne 0) {
            throw "Python installer loi ExitCode=$($proc.ExitCode)"
        }
        $env:PATH = "$env:LOCALAPPDATA\Programs\Python\Python311;$env:LOCALAPPDATA\Programs\Python\Python311\Scripts;$env:PATH"
        $py = Find-PythonVoice
    }
}
if (-not $py) { throw "Khong cai/tim duoc Python 3.11 hoac 3.10." }

if ($py[1]) {
    $python = @($py[0], $py[1])
} else {
    $python = @($py[0])
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    if ($python.Length -gt 1) {
        & $python[0] $python[1] @Args
    } else {
        & $python[0] @Args
    }
}

Invoke-Python -m pip install --upgrade pip wheel setuptools

try {
    Invoke-Python -c "import torch, torchaudio, omnivoice, soundfile" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "MagicVoice dependencies OK"
        exit 0
    }
} catch {}

Write-Host "Dang cai Torch va MagicVoice dependencies..."
Invoke-Python -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --progress-bar on --no-cache-dir
Invoke-Python -m pip install omnivoice soundfile scipy pydub psutil requests numpy imageio-ffmpeg --progress-bar on --no-cache-dir

Invoke-Python -c "import torch, torchaudio, omnivoice, soundfile; print('MagicVoice import OK')"

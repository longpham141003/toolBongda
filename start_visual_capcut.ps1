$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "startup.log"

function Write-Step {
    param([string]$Message)
    $line = "[Visual CapCut] $Message"
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
}

function Write-Detail {
    param([string]$Message)
    Write-Host "  - $Message" -ForegroundColor Gray
    Add-Content -Path $LogPath -Value "  - $Message" -Encoding UTF8
}

function Stop-WithHelp {
    param([string]$Message)
    Write-Host ""
    Write-Host "[LOI] $Message" -ForegroundColor Red
    Add-Content -Path $LogPath -Value "[LOI] $Message" -Encoding UTF8
    Write-Host ""
    Write-Host "Hay gui file log nay cho nguoi phu trach neu can ho tro:" -ForegroundColor Yellow
    Write-Host $LogPath -ForegroundColor Yellow
    exit 1
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-BasePythonCommand {
    if (-not (Test-Command "py")) {
        if (Test-Command "winget") {
            Write-Step "May chua co Python. Dang thu cai Python 3.13 bang winget..."
            winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        }
        if (-not (Test-Command "py")) {
            Stop-WithHelp "May chua co Python Launcher. Hay cai Python 3.10 tro len, tick 'Add python.exe to PATH', roi mo lai tool."
        }
    }

    foreach ($version in @("3.13", "3.12", "3.11", "3.10")) {
        & py "-$version" --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return @("py", "-$version")
        }
    }

    Stop-WithHelp "Khong tim thay Python 3.10 tro len. Hay cai Python 3.10/3.11/3.12/3.13 roi mo lai tool."
}

function Invoke-Checked {
    param(
        [string[]]$Command,
        [string]$ErrorMessage,
        [string]$WorkingDirectory = $Root
    )
    Write-Detail ($Command -join " ")
    $process = Start-Process -FilePath $Command[0] -ArgumentList $Command[1..($Command.Count - 1)] -WorkingDirectory $WorkingDirectory -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        Stop-WithHelp $ErrorMessage
    }
}

Write-Host "============================================================" -ForegroundColor DarkGray
Write-Host " Visual CapCut Studio - Tu dong chuan bi moi truong" -ForegroundColor Green
Write-Host " Lan dau co the mat 5-15 phut tuy mang/may." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor DarkGray
Set-Content -Path $LogPath -Value "[Visual CapCut] Startup $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8

Write-Step "Kiem tra Python..."
$BasePython = Get-BasePythonCommand
Write-Detail "Dung Python: $($BasePython -join ' ')"

if (-not (Test-Path (Join-Path $Root "settings.json"))) {
    Write-Step "Tao file cau hinh rieng cho may nay..."
    Copy-Item -LiteralPath (Join-Path $Root "settings.example.json") -Destination (Join-Path $Root "settings.json") -Force
}

$BackendVenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $BackendVenvPython)) {
    Write-Step "Lan dau chay: dang tao moi truong backend..."
    Invoke-Checked -Command @($BasePython[0], $BasePython[1], "-m", "venv", ".venv") -ErrorMessage "Khong tao duoc moi truong backend Python."
}

Write-Step "Kiem tra va cai thu vien can thiet cho tool..."
& $BackendVenvPython -c "import fastapi,uvicorn,playwright,requests,PIL,imagehash,multipart" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Detail "Dang cai thu vien backend. Vui long cho..."
    Invoke-Checked -Command @($BackendVenvPython, "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check") -ErrorMessage "Khong nang cap duoc pip."
    Invoke-Checked -Command @($BackendVenvPython, "-m", "pip", "install", "-r", "requirements.txt", "--disable-pip-version-check") -ErrorMessage "Khong cai duoc thu vien backend. Kiem tra internet roi thu lai."
}

Write-Step "Kiem tra trinh duyet tu dong de tim anh..."
$PlaywrightOk = $false
if (Test-Path $env:LOCALAPPDATA) {
    $PlaywrightOk = [bool](Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "ms-playwright") -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue)
}
if (-not $PlaywrightOk) {
    Write-Detail "Dang cai Chromium cho Playwright. Vui long cho..."
    Invoke-Checked -Command @($BackendVenvPython, "-m", "playwright", "install", "chromium") -ErrorMessage "Khong cai duoc Chromium Playwright. Kiem tra internet roi thu lai."
}

if (-not (Test-Path (Join-Path $Root "kokoro-tts-local\app.py"))) {
    Stop-WithHelp "Thieu thu muc kokoro-tts-local. Repo chua duoc clone/pull day du."
}

$KokoroPython = Join-Path $Root "kokoro-tts-local\.venv\Scripts\python.exe"
if (-not (Test-Path $KokoroPython)) {
    Write-Step "Lan dau chay: dang cai Kokoro voice local..."
    Write-Detail "Buoc nay co the lau vi phai tai thu vien tao giong."
    Invoke-Checked -Command @("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "setup.ps1") -WorkingDirectory (Join-Path $Root "kokoro-tts-local") -ErrorMessage "Khong cai duoc Kokoro local. Kiem tra internet/Python roi thu lai."
}

Write-Step "Khoi dong API local..."
$owners = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($owner in $owners) {
    try { Stop-Process -Id $owner -Force -ErrorAction Stop } catch {}
}
Start-Sleep -Seconds 1

$ApiLog = Join-Path $LogDir "api.log"
$ApiErrLog = Join-Path $LogDir "api.err.log"
$process = Start-Process -FilePath $BackendVenvPython -ArgumentList @("-m", "app.web_server") -WorkingDirectory $Root -WindowStyle Minimized -PassThru -RedirectStandardOutput $ApiLog -RedirectStandardError $ApiErrLog

Write-Step "Doi tool san sang..."
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8765/api/health" -TimeoutSec 1
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    }
    catch {}
    Start-Sleep -Seconds 1
}

if (-not $ready) {
    Stop-WithHelp "API khong khoi dong duoc. Xem log: $ApiErrLog"
}

Write-Step "Mo giao dien tool..."
Start-Process "http://127.0.0.1:8765"
Write-Host ""
Write-Host "Tool da san sang. Neu lan dau dung AI, hay vao Cai dat de dien Gemini API key." -ForegroundColor Green
Start-Sleep -Seconds 2

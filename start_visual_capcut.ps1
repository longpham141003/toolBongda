$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "startup.log"
$StartupPagePath = Join-Path $LogDir "startup_status.html"
$script:StartupPercent = 3
$script:StartupPageOpened = $false
$script:StartupStatus = "Đang chuẩn bị"
$script:StartupMessage = "Tool đang kiểm tra môi trường trên máy này."

function ConvertTo-HtmlText {
    param([string]$Value)
    return [System.Net.WebUtility]::HtmlEncode($Value)
}

function Write-StartupPage {
    param(
        [string]$Status = $script:StartupStatus,
        [string]$Message = $script:StartupMessage,
        [int]$Percent = $script:StartupPercent,
        [string]$Mode = "running",
        [string]$RedirectUrl = ""
    )
    $script:StartupStatus = $Status
    $script:StartupMessage = $Message
    $script:StartupPercent = [Math]::Max(0, [Math]::Min(100, $Percent))
    $refresh = if ($Mode -eq "ready" -and $RedirectUrl) {
        "<meta http-equiv=""refresh"" content=""1; url=$RedirectUrl"">"
    } elseif ($Mode -eq "running") {
        "<meta http-equiv=""refresh"" content=""2"">"
    } else {
        ""
    }
    $logLines = @()
    if (Test-Path $LogPath) {
        $logLines = Get-Content -LiteralPath $LogPath -Tail 6 -ErrorAction SilentlyContinue
    }
    $logHtml = ($logLines | ForEach-Object { "<li>$(ConvertTo-HtmlText $_)</li>" }) -join "`n"
    $statusText = ConvertTo-HtmlText $Status
    $messageText = ConvertTo-HtmlText $Message
    $percentText = [string]$script:StartupPercent
    $html = @"
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  $refresh
  <title>Visual CapCut Studio - Đang khởi động</title>
  <style>
    :root{color-scheme:dark;font-family:Inter,Segoe UI,Arial,sans-serif}
    *{box-sizing:border-box} body{margin:0;min-height:100vh;display:grid;place-items:center;overflow:hidden;background:#101014;color:#f8fafc}
    body:before{content:"";position:fixed;inset:-20%;background:radial-gradient(circle at 18% 20%,rgba(139,92,246,.30),transparent 26%),radial-gradient(circle at 84% 84%,rgba(78,222,163,.18),transparent 28%),linear-gradient(145deg,#15121d,#0b0c0f 56%,#071810);animation:float 9s ease-in-out infinite alternate}
    .particles{position:fixed;inset:0;background-image:radial-gradient(rgba(255,255,255,.18) 1px,transparent 1px);background-size:72px 72px;opacity:.35;animation:fall 18s linear infinite}
    .card{position:relative;width:min(760px,calc(100vw - 40px));border:1px solid rgba(208,188,255,.22);border-radius:34px;background:linear-gradient(145deg,rgba(255,255,255,.10),rgba(255,255,255,.035));box-shadow:0 34px 130px rgba(0,0,0,.55),0 0 80px rgba(139,92,246,.14);padding:34px;backdrop-filter:blur(28px)}
    .brand{display:flex;align-items:center;gap:14px;margin-bottom:28px}.logo{display:grid;width:54px;height:54px;place-items:center;border-radius:18px;background:linear-gradient(135deg,#8b5cf6,#4edea3);box-shadow:0 0 34px rgba(139,92,246,.35);font-size:26px}.brand b{font-size:22px}.brand span{display:block;margin-top:3px;color:#94a3b8;font-size:12px;letter-spacing:.18em;text-transform:uppercase}
    h1{margin:0 0 10px;font-size:34px;line-height:1.12;letter-spacing:-.035em}.lead{margin:0 0 26px;color:#b8c1d4;font-size:16px;line-height:1.6}.status{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px}.status b{font-size:18px}.status span{color:#d0bcff;font-weight:900}
    .bar{height:12px;overflow:hidden;border-radius:999px;background:rgba(255,255,255,.10)}.bar i{display:block;height:100%;width:$percentText%;border-radius:inherit;background:linear-gradient(90deg,#8b5cf6,#d946ef,#4edea3);box-shadow:0 0 28px rgba(78,222,163,.25);transition:width .35s ease}
    .message{margin:16px 0 22px;border:1px solid rgba(78,222,163,.14);border-radius:18px;background:rgba(78,222,163,.06);padding:14px 16px;color:#d1fae5;line-height:1.5}
    .log{margin:0;padding:0;list-style:none;display:grid;gap:7px}.log li{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:1px solid rgba(255,255,255,.07);border-radius:12px;background:rgba(0,0,0,.18);padding:9px 11px;color:#94a3b8;font-size:12px}
    .hint{margin-top:22px;color:#94a3b8;font-size:13px}.spinner{display:inline-block;width:16px;height:16px;margin-right:8px;border:2px solid rgba(255,255,255,.22);border-top-color:#d0bcff;border-radius:999px;vertical-align:-3px;animation:spin .85s linear infinite}
    @keyframes spin{to{transform:rotate(360deg)}}@keyframes fall{to{background-position:0 144px}}@keyframes float{to{transform:translate3d(1.5%,-1%,0) scale(1.02)}}
  </style>
</head>
<body>
  <div class="particles"></div>
  <main class="card">
    <div class="brand"><div class="logo">✦</div><div><b>Visual CapCut <span style="display:inline;color:#4edea3;letter-spacing:0;text-transform:none;font-size:22px">Studio</span></b><span>AI VIDEO PRODUCTION</span></div></div>
    <h1><span class="spinner"></span>$statusText</h1>
    <p class="lead">Lần đầu mở tool có thể mất vài phút vì máy cần chuẩn bị thư viện tạo giọng, trình duyệt tìm ảnh và môi trường chạy local.</p>
    <div class="status"><b>$messageText</b><span>$percentText%</span></div>
    <div class="bar"><i></i></div>
    <div class="message">Bạn cứ để màn hình này mở. Khi tool sẵn sàng, trang sẽ tự chuyển sang giao diện chính.</div>
    <ul class="log">$logHtml</ul>
    <div class="hint">Nếu bị lỗi, gửi file <b>logs/startup.log</b> cho người phụ trách.</div>
  </main>
</body>
</html>
"@
    Set-Content -Path $StartupPagePath -Value $html -Encoding UTF8
}

function Open-StartupPage {
    if ($script:StartupPageOpened) { return }
    $script:StartupPageOpened = $true
    Start-Process $StartupPagePath
}

function Write-Step {
    param([string]$Message)
    $line = "[Visual CapCut] $Message"
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
    $script:StartupPercent = [Math]::Min(96, $script:StartupPercent + 8)
    Write-StartupPage -Status "Đang chuẩn bị Visual CapCut Studio" -Message $Message -Percent $script:StartupPercent
}

function Write-Detail {
    param([string]$Message)
    Write-Host "  - $Message" -ForegroundColor Gray
    Add-Content -Path $LogPath -Value "  - $Message" -Encoding UTF8
    Write-StartupPage -Status $script:StartupStatus -Message $Message -Percent $script:StartupPercent
}

function Stop-WithHelp {
    param([string]$Message)
    Write-StartupPage -Status "Không khởi động được tool" -Message $Message -Percent $script:StartupPercent -Mode "error"
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

function Test-PythonVersion {
    param([string]$Version)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & py "-$Version" --version *> $null
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    return $exitCode -eq 0
}

function Get-BasePythonCommand {
    if (-not (Test-Command "py")) {
        if (Test-Command "winget") {
            Write-Step "May chua co Python. Dang thu cai Python 3.12 bang winget..."
            winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        }
        if (-not (Test-Command "py")) {
            Stop-WithHelp "May chua co Python Launcher. Hay cai Python 3.10 tro len, tick 'Add python.exe to PATH', roi mo lai tool."
        }
    }

    foreach ($version in @("3.12", "3.11", "3.10", "3.13")) {
        if (Test-PythonVersion $version) {
            return @("py", "-$version")
        }
    }

    Stop-WithHelp "Khong tim thay Python 3.10 tro len. Khuyen nghi Python 3.12 de Kokoro voice chay on dinh."
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
Write-StartupPage -Status "Đang mở Visual CapCut Studio" -Message "Đang kiểm tra các thành phần cần thiết..." -Percent 3
Open-StartupPage

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
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $BackendVenvPython -c "import fastapi,uvicorn,playwright,requests,PIL,imagehash,multipart,soundfile" *> $null
$dependencyCheckExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($dependencyCheckExitCode -ne 0) {
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
Write-StartupPage -Status "Tool đã sẵn sàng" -Message "Đang chuyển sang giao diện chính..." -Percent 100 -Mode "ready" -RedirectUrl "http://127.0.0.1:8765"
Start-Process "http://127.0.0.1:8765"
Write-Host ""
Write-Host "Tool da san sang. Neu lan dau dung AI, hay vao Cai dat de dien Gemini API key." -ForegroundColor Green
Start-Sleep -Seconds 2
exit 0

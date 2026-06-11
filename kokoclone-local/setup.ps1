$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

function Find-Python {
    $candidates = @(
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("py", "-3.10"),
        @("python", "")
    )
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $arg = $candidate[1]
        try {
            if ($arg) {
                & $exe $arg -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" *> $null
            } else {
                & $exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" *> $null
            }
            if ($LASTEXITCODE -eq 0) {
                return @($exe, $arg)
            }
        } catch {}
    }
    throw "Không tìm thấy Python 3.10+ để cài KokoClone."
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    $py = Find-Python
    if ($py[1]) {
        & $py[0] $py[1] -m venv .venv
    } else {
        & $py[0] -m venv .venv
    }
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip wheel setuptools

# CPU torch trước để tránh pip kéo bản CUDA quá nặng trên máy không có GPU.
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -c "from core.cloner import KokoClone; print('KokoClone import OK')"

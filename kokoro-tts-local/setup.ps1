$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Get-WorkingPython {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host "Python launcher was not found. Installing Python 3.12 with winget..."
            winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        }
    }

    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python launcher 'py' was not found. Install Python 3.10, 3.11, or 3.12 and try again."
    }

    foreach ($Version in @("3.12", "3.11", "3.10")) {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        py -$Version --version *> $null
        $versionExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($versionExitCode -eq 0) {
            return @("py", "-$Version")
        }
    }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Kokoro does not support Python 3.13 yet. Installing Python 3.12 with winget..."
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        py -3.12 --version *> $null
        $versionExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($versionExitCode -eq 0) {
            return @("py", "-3.12")
        }
    }

    throw "No compatible Python was found for Kokoro. Install Python 3.10, 3.11, or 3.12. Python 3.13 is not supported by Kokoro 0.9.4."
}

$PythonCommand = Get-WorkingPython

if (-not (Test-Path ".venv")) {
    if ($PythonCommand.Count -gt 1) {
        & $PythonCommand[0] $PythonCommand[1..($PythonCommand.Count - 1)] -m venv .venv
    }
    else {
        & $PythonCommand[0] -m venv .venv
    }
}

function Invoke-Checked {
    param([string[]]$Command, [string]$ErrorMessage)
    Write-Host ($Command -join " ")
    $process = Start-Process -FilePath $Command[0] -ArgumentList $Command[1..($Command.Count - 1)] -WorkingDirectory $Root -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw $ErrorMessage
    }
}

Invoke-Checked -Command @(".\.venv\Scripts\python.exe", "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check") -ErrorMessage "Failed to upgrade pip."
Invoke-Checked -Command @(".\.venv\Scripts\python.exe", "-m", "pip", "install", "-r", "requirements.txt", "--disable-pip-version-check") -ErrorMessage "Failed to install Kokoro requirements."

.\.venv\Scripts\python.exe -c "import kokoro, soundfile, numpy" *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Kokoro setup finished but required Python packages are still missing."
}

if (-not (Get-Command espeak-ng -ErrorAction SilentlyContinue)) {
    Write-Warning "espeak-ng was not found in PATH. English may still work, but install espeak-ng if Kokoro reports pronunciation/G2P errors."
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Try:"
Write-Host ".\.venv\Scripts\python.exe .\tts.py --text `"Hello, this is Kokoro.`" --out outputs\hello.wav"

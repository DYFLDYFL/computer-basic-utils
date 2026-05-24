$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$requirementsPath = Join-Path $projectRoot "requirements.txt"

if (-not (Test-Path $pythonPath)) {
    Write-Host "Creating virtual environment..."
    python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment."
    }
}

& $pythonPath -m pip install -q -r $requirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install requirements."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
& $pythonPath -m file_organizer

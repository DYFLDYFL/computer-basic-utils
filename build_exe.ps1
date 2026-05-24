$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$distRoot = Join-Path $projectRoot "dist"
$distPath = Join-Path $distRoot "FolderOrganizer"
$stagingRoot = Join-Path $distRoot ".build_staging"
$stagingPath = Join-Path $stagingRoot "FolderOrganizer"

function Stop-FolderOrganizerProcess {
    $runningApp = Get-Process -Name "FolderOrganizer" -ErrorAction SilentlyContinue
    if (-not $runningApp) {
        return
    }

    Write-Host "Closing FolderOrganizer.exe..."
    $runningApp | Stop-Process -Force
    Start-Sleep -Seconds 2
}

function Remove-BuildOutput {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            Stop-FolderOrganizerProcess
            Start-Sleep -Seconds 2
        }
    }

    throw "Cannot remove $Path"
}

function Publish-BuildOutput {
    param(
        [string]$SourcePath,
        [string]$TargetPath
    )

    if (-not (Test-Path $SourcePath)) {
        throw "Build output not found: $SourcePath"
    }

    New-Item -ItemType Directory -Force -Path $TargetPath | Out-Null

    Get-ChildItem -LiteralPath $SourcePath -Force | ForEach-Object {
        $destination = Join-Path $TargetPath $_.Name
        if ($_.PSIsContainer) {
            if (Test-Path $destination) {
                Remove-BuildOutput -Path $destination
            }
            Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
        } else {
            Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
        }
    }
}

Stop-FolderOrganizerProcess

if (-not (Test-Path $pythonPath)) {
    python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment."
    }
}

& $pythonPath -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}

& $pythonPath -m pip install -r (Join-Path $projectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install requirements."
}

$managedPath = Join-Path $distPath "myfile"
$myfileBackup = Join-Path $projectRoot ".myfile_build_backup"
if (Test-Path $managedPath) {
    if (Test-Path $myfileBackup) {
        Remove-Item -Recurse -Force $myfileBackup
    }
    Copy-Item -Path $managedPath -Destination $myfileBackup -Recurse -Force
}

Stop-FolderOrganizerProcess
Remove-BuildOutput -Path $stagingRoot

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $stagingRoot `
    (Join-Path $projectRoot "FolderOrganizer.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$newManagedPath = Join-Path $stagingPath "myfile"
if (Test-Path $myfileBackup) {
    Copy-Item -Path $myfileBackup -Destination $newManagedPath -Recurse -Force
    Remove-Item -Recurse -Force $myfileBackup
} else {
    New-Item -ItemType Directory -Force -Path $newManagedPath | Out-Null
}

try {
    Remove-BuildOutput -Path $distPath
    Move-Item -LiteralPath $stagingPath -Destination $distPath
} catch {
    Write-Host "dist\FolderOrganizer is in use; copying build output in place..."
    Publish-BuildOutput -SourcePath $stagingPath -TargetPath $distPath
    Remove-BuildOutput -Path $stagingRoot
}

Write-Host "Build complete: dist\FolderOrganizer\FolderOrganizer.exe"
Write-Host "Managed folder: dist\FolderOrganizer\myfile"

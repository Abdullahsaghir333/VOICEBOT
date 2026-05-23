# One-time setup: install packages into project venv
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating venv in .\venv ..."
    python -m venv venv
}

Write-Host "Installing requirements into venv ..."
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt

Write-Host ""
Write-Host "Setup complete."
Write-Host "  Activate:  .\venv\Scripts\Activate.ps1"
Write-Host "  API:       .\run_api.bat"
Write-Host "  UI:        .\run_ui.bat"

# MineIntel AI — start FastAPI backend (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\backend

if (-not (Test-Path .\.venv\Scripts\Activate.ps1)) {
  Write-Host "Creating virtualenv..."
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

. .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path

Write-Host "Starting MineIntel backend on http://127.0.0.1:8000 ..."
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

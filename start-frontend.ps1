# MineIntel AI — start Vite frontend (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\frontend

if (-not (Test-Path .\node_modules)) {
  Write-Host "Installing frontend dependencies..."
  npm install
}

Write-Host "Starting MineIntel frontend on http://127.0.0.1:5173 ..."
npm run dev -- --host 127.0.0.1 --port 5173

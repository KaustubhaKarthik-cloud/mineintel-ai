# MineIntel AI — start Vite frontend (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\frontend

$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
  Write-Host "ERROR: Node.js not found. Install Node 20.19+ or 22.12+ from https://nodejs.org/" -ForegroundColor Red
  exit 1
}

$nodeVer = (& node -v).TrimStart("v")
$parts = $nodeVer.Split(".")
$major = [int]$parts[0]
$minor = [int]$parts[1]
$nodeOk = ($major -eq 20 -and $minor -ge 19) -or ($major -eq 21) -or ($major -ge 22)
# Vite 8: ^20.19.0 || >=22.12.0 — allow 22.x broadly; warn if 22.<12
if ($major -eq 22 -and $minor -lt 12) {
  Write-Host "WARNING: Node $nodeVer detected. Vite 8 prefers >=22.12.0 (or 20.19+)." -ForegroundColor Yellow
}
if (-not $nodeOk -and $major -lt 20) {
  Write-Host "ERROR: Node.js $nodeVer is too old for Vite 8." -ForegroundColor Red
  Write-Host "Install Node 20.19+ or 22.12+ from https://nodejs.org/"
  exit 1
}
Write-Host "Using Node $nodeVer"

if (-not (Test-Path .\node_modules)) {
  Write-Host "Installing frontend dependencies..."
  npm install
}

Write-Host "Starting MineIntel frontend on http://127.0.0.1:5173 ..."
npm run dev -- --host 127.0.0.1 --port 5173

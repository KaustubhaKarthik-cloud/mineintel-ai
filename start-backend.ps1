# MineIntel AI - start FastAPI backend (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\backend

function Get-MineIntelPython {
  # Prefer an explicit supported interpreter (3.10-3.12; 3.11 recommended).
  $candidates = @()
  foreach ($ver in @("3.11", "3.12", "3.10")) {
    try {
      $p = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $p) { $candidates += $p.Trim() }
    } catch { }
  }
  if ($candidates.Count -gt 0) { return $candidates[0] }

  foreach ($cmd in @("python3.11", "python3.12", "python3.10", "python3", "python")) {
    $exe = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($exe) { return $exe.Source }
  }
  return $null
}

function Assert-SupportedPython([string]$PythonExe) {
  $info = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); print(sys.version_info.major*100+sys.version_info.minor)"
  $lines = $info -split "`n"
  $version = $lines[0].Trim()
  $code = [int]$lines[1].Trim()
  Write-Host "Using Python $version ($PythonExe)"
  if ($code -lt 310 -or $code -ge 314) {
    Write-Host ""
    Write-Host "ERROR: MineIntel requires Python 3.10, 3.11, or 3.12 (recommended: 3.11)." -ForegroundColor Red
    Write-Host "Detected: Python $version"
    Write-Host ""
    Write-Host "Why: packages such as numpy==2.2.x require Python >= 3.10."
    Write-Host "Install from: https://www.python.org/downloads/release/python-3119/"
    Write-Host "On Windows, tick 'Add python.exe to PATH', then reopen the terminal."
    Write-Host "Then run:  py -3.11 -m venv .venv"
    exit 1
  }
}

$python = Get-MineIntelPython
if (-not $python) {
  Write-Host "ERROR: Python not found. Install Python 3.11 from python.org and retry." -ForegroundColor Red
  exit 1
}
Assert-SupportedPython $python

if (-not (Test-Path .\.venv\Scripts\Activate.ps1)) {
  Write-Host "Creating virtualenv with $python ..."
  & $python -m venv .venv
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed. Confirm Python is 3.10-3.12 and retry." -ForegroundColor Red
    exit $LASTEXITCODE
  }
} else {
  # Re-check the venv interpreter in case it was created with an unsupported Python
  Assert-SupportedPython (Resolve-Path .\.venv\Scripts\python.exe)
}

. .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path

Write-Host "Starting MineIntel backend on http://127.0.0.1:8000 ..."
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

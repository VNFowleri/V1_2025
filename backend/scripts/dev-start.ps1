param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $BackendDir
if (-not (Test-Path ".\.venv")) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not (Test-Path ".\.env")) { Copy-Item .\.env.example .\.env }
uvicorn app.main:app --host 0.0.0.0 --port $Port --reload

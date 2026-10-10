$ErrorActionPreference = "Stop"
Write-Host "Starting PCIA..." -ForegroundColor Green
if (!(Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe app.py

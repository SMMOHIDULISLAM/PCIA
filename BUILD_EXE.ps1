$ErrorActionPreference = "Stop"
Write-Host "Building PCIA.exe..." -ForegroundColor Green
if (!(Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\pip.exe install pyinstaller
.\.venv\Scripts\pyinstaller.exe --onefile --name PCIA --add-data "templates;templates" --add-data "static;static" app.py
Write-Host "Done. Check dist\PCIA.exe" -ForegroundColor Green

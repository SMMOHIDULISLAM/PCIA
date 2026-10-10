$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Install dependencies first."
}
$pidFile = Join-Path $PSScriptRoot "pcia_server.pid"
if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
        Write-Host "PCIA is already running at http://127.0.0.1:5050"
        exit 0
    }
}
$process = Start-Process -FilePath $python -ArgumentList "app.py" -WorkingDirectory $PSScriptRoot -PassThru
$process.Id | Set-Content $pidFile
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:5050"
Write-Host "PCIA started. PID: $($process.Id)"

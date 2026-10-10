$pidFile = Join-Path $PSScriptRoot "pcia_server.pid"
if (-not (Test-Path $pidFile)) {
    Write-Host "PCIA PID file not found."
    exit 0
}
$serverPid = Get-Content $pidFile -ErrorAction SilentlyContinue
if ($serverPid) {
    Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
}
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "PCIA stopped."

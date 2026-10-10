@echo off
setlocal
cd /d "%~dp0"
set "PIDFILE=data\pcia.pid"
if not exist "%PIDFILE%" (
  echo PCIA is not running, or the PID file was not found.
  pause
  exit /b 0
)
set /p PID=<"%PIDFILE%"
if "%PID%"=="" (
  del /q "%PIDFILE%" >nul 2>nul
  echo PCIA PID was empty.
  pause
  exit /b 0
)
taskkill /PID %PID% /T /F >nul 2>nul
if errorlevel 1 (
  echo PCIA process %PID% was not running.
) else (
  echo PCIA stopped successfully.
)
del /q "%PIDFILE%" >nul 2>nul
pause

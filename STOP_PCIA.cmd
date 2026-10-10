@echo off
setlocal
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5050 .*LISTENING"') do taskkill /F /PID %%P >nul 2>&1
endlocal

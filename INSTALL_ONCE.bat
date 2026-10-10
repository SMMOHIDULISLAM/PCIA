@echo off
setlocal
cd /d "%~dp0"
echo =============================================
echo PCIA Proposal Processor - One-time Setup
echo =============================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher 'py' was not found.
  echo Install Python 3.11 and select Add Python to PATH.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python 3.11 virtual environment...
  py -3.11 -m venv .venv
  if errorlevel 1 goto :fail
)
echo Installing required packages into .venv...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo.
echo SETUP COMPLETED SUCCESSFULLY.
pause
exit /b 0
:fail
echo.
echo SETUP FAILED. Copy the full error and send it for correction.
pause
exit /b 1

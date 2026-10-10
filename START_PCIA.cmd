@echo off
setlocal
cd /d "%~dp0"
title PCIA Server - KEEP THIS WINDOW OPEN
color 0A

echo ============================================================
echo      PCIA - Enterprise Credit Processing Platform
echo ============================================================
echo.

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo ERROR: Python 3 is not installed or not available in PATH.
  echo Install Python 3.11, tick "Add Python to PATH", then run again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating PCIA environment...
  %PYEXE% -m venv .venv
  if errorlevel 1 goto :failed
)

set "VENV_PY=.venv\Scripts\python.exe"
echo Checking required packages...
"%VENV_PY%" -c "import flask,waitress,lxml,fitz,openpyxl,docx,PIL,pytesseract" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages. This is needed only once...
  "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :failed
)

echo Checking PCIA application...
"%VENV_PY%" -m py_compile app.py pcia_engine.py
if errorlevel 1 goto :failed

echo.
echo PCIA is starting at http://127.0.0.1:5050
echo Keep this window open while using PCIA.
echo To stop, double-click STOP_PCIA.cmd or close this window.
echo.
"%VENV_PY%" app.py
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo ============================================================
echo PCIA COULD NOT START. The exact error is shown above.
echo ============================================================
pause
exit /b 1

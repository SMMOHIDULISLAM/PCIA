@echo off
setlocal
cd /d D:\PCIA
if not exist app.py (
  echo ERROR: D:\PCIA\app.py not found.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: Could not create Python environment.
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo ERROR: Required Python packages could not be installed.
  pause
  exit /b 1
)
start "PCIA Server" cmd /k "cd /d D:\PCIA && .venv\Scripts\python.exe app.py"
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:5050"
endlocal

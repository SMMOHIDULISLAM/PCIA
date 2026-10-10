@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run START_PCIA.cmd once before running the demo.
  pause
  exit /b 1
)
set PYTHONPATH=%CD%
".venv\Scripts\python.exe" demo_generate.py
pause

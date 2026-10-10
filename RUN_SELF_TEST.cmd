@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run START_PCIA.cmd once before running the self-test.
  pause
  exit /b 1
)
set PYTHONPATH=%CD%
".venv\Scripts\python.exe" tests\self_test.py
pause

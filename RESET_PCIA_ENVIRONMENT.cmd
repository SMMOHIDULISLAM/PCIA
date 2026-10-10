@echo off
setlocal
cd /d "%~dp0"
echo This removes only the Python environment. Templates and cases remain safe.
if exist ".venv" rmdir /s /q ".venv"
echo Environment reset complete. Run START_PCIA.cmd again.
pause

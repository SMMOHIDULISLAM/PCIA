@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CREATE_DESKTOP_SHORTCUTS.ps1"
pause

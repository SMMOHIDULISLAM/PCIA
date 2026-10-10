@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo PCIA is not installed yet.
  echo Double-click INSTALL_ONCE.bat first.
  pause
  exit /b 1
)
set "PROPOSAL="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.OpenFileDialog; $d.Title='Select customer proposal ZIP'; $d.Filter='ZIP proposal files (*.zip)|*.zip'; $d.Multiselect=$false; if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){$d.FileName}"`) do set "PROPOSAL=%%I"
if not defined PROPOSAL (
  echo No ZIP was selected.
  exit /b 0
)
if not exist "D:\PCIA_CASES" mkdir "D:\PCIA_CASES"
echo.
echo Processing: %PROPOSAL%
echo.
".venv\Scripts\python.exe" -m pcia.cli --proposal "%PROPOSAL%" --work-root "D:\PCIA_CASES"
if errorlevel 1 (
  echo.
  echo PROCESSING FAILED. Copy the complete error and send it for correction.
  pause
  exit /b 1
)
set "LATEST="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=Get-ChildItem 'D:\PCIA_CASES' -Directory ^| Sort-Object LastWriteTime -Descending ^| Select-Object -First 1; if($d){$d.FullName}"`) do set "LATEST=%%D"
if defined LATEST explorer "%LATEST%"
echo.
echo PROCESSING COMPLETED.
echo Results: %LATEST%
pause

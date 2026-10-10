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
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.OpenFileDialog; $d.Title='Select customer proposal ZIP'; $d.Filter='ZIP proposal files (*.zip)|*.zip'; if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){$d.FileName}"`) do set "PROPOSAL=%%I"
if not defined PROPOSAL exit /b 0
set "DECISIONS="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.OpenFileDialog; $d.Title='Select operator decisions JSON'; $d.Filter='JSON files (*.json)|*.json'; if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){$d.FileName}"`) do set "DECISIONS=%%I"
if not defined DECISIONS exit /b 0
if not exist "D:\PCIA_CASES" mkdir "D:\PCIA_CASES"
".venv\Scripts\python.exe" -m pcia.cli --proposal "%PROPOSAL%" --work-root "D:\PCIA_CASES" --operator-decisions "%DECISIONS%"
if errorlevel 1 (
  echo PROCESSING FAILED.
  pause
  exit /b 1
)
set "LATEST="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=Get-ChildItem 'D:\PCIA_CASES' -Directory ^| Sort-Object LastWriteTime -Descending ^| Select-Object -First 1; if($d){$d.FullName}"`) do set "LATEST=%%D"
if defined LATEST explorer "%LATEST%"
echo PROCESSING COMPLETED: %LATEST%
pause

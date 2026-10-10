$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell

$start = $shell.CreateShortcut((Join-Path $desktop 'START PCIA.lnk'))
$start.TargetPath = (Join-Path $root 'START_PCIA.cmd')
$start.WorkingDirectory = $root
$start.Description = 'Start PCIA Enterprise Credit Processing Platform'
$start.Save()

$stop = $shell.CreateShortcut((Join-Path $desktop 'STOP PCIA.lnk'))
$stop.TargetPath = (Join-Path $root 'STOP_PCIA.cmd')
$stop.WorkingDirectory = $root
$stop.Description = 'Stop PCIA Enterprise Credit Processing Platform'
$stop.Save()

Write-Host 'Desktop shortcuts created: START PCIA and STOP PCIA.'

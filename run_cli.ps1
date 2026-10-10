param(
    [Parameter(Mandatory=$true)][string]$ProposalZip,
    [string]$WorkRoot = "D:\PCIA_CASES",
    [switch]$OCR
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Run installation commands from README.md first."
}

$argsList = @("-m", "pcia.cli", "--proposal", $ProposalZip, "--work-root", $WorkRoot)
if ($OCR) { $argsList += "--ocr" }
& $python @argsList

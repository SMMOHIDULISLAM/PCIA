# Fast Start — PCIA v1.2

## First installation

Double-click:

`INSTALL_ONCE.bat`

## Process a proposal

Double-click:

`PROCESS_PROPOSAL.bat`

Select the customer ZIP. Results open automatically under:

`D:\PCIA_CASES`

## Process after confirming disputed information

1. Copy `config\operator_decisions.example.json` and enter confirmed field values.
2. Double-click `PROCESS_PROPOSAL_WITH_DECISIONS.bat`.
3. Select the proposal ZIP and then the decision JSON.

A Bandhan Agro example is included at:

`config\operator_decisions.bandhan_agro.json`

## Scanned package

Use:

`PROCESS_PROPOSAL_WITH_OCR.bat`

OCR requires Tesseract to be installed on Windows. Native PDF/DOCX/ODT/Excel text is read without OCR.

# PCIA Proposal Processor v1

A deterministic, local-first Python engine for processing a new banking credit proposal package. It inventories every file, reads supported formats, classifies document pages, extracts evidence, resolves values using source priority, detects conflicts, asks operator questions, and optionally generates controlled DOCX/ODT drafts from master templates.

## Important boundary

This is a working baseline, not a claim that every unseen bank form can be understood perfectly without configuration. New document layouts are supported by adding patterns to `config/field_rules.json` and source-priority rules to `config/source_priority.json`. Final credit judgment remains with the authorized bank officer.

## Processing flow

```text
Proposal ZIP
  -> safe extraction, including nested ZIPs
  -> complete file manifest
  -> format-specific reading
  -> page/document classification
  -> field candidates with file/page evidence
  -> validation and rejection of form labels
  -> source-priority resolution
  -> conflict and anomaly detection
  -> operator questions
  -> controlled Notesheet/Sanction generation
  -> placeholder and old-model leakage quality gates
```

## Supported inputs

- PDF: native text; optional OCR for unreadable pages
- DOCX: body, tables, headers, and footers
- ODT: XML text
- XLSX/XLSM: every non-empty sheet and cell
- TXT, CSV, JSON
- PNG/JPG/TIFF/BMP with optional OCR
- Old DOC/XLS when LibreOffice is installed and available as `soffice`
- ZIP and nested ZIP packages

## Installation on Windows 10 / Python 3.11

Open PowerShell in this folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For scanned Bangla/English files, install Tesseract separately and ensure `tesseract.exe` is on PATH. The engine invokes OCR only when `--ocr` is supplied and a page has little or no native text.

## First pass: evidence and questions only

```powershell
python -m pcia.cli `
  --proposal "D:\Cases\Customer Proposal.zip" `
  --work-root "D:\PCIA_CASES" `
  --ocr
```

The command prints a `case_id` and result ZIP path. The result includes:

- `package_manifest.json`
- `evidence_ledger.json` and `.csv`
- `resolved_case.json`
- `conflicts_and_anomalies.json`
- `operator_questions.json`
- `missing_fields.json`
- `missing_documents.json`
- `Anomaly_and_Shortcoming_Letter_Draft.docx`
- `SUMMARY.md`

## Confirm operator decisions

Copy `config/operator_decisions.example.json`, edit only confirmed fields, and rerun:

```powershell
python -m pcia.cli `
  --proposal "D:\Cases\Customer Proposal.zip" `
  --work-root "D:\PCIA_CASES" `
  --operator-decisions ".\config\operator_decisions.customer.json" `
  --ocr
```

Decision format:

```json
{
  "decisions": {
    "branch": {
      "value": "Jagannathpur Branch, Sunamgonj",
      "note": "Confirmed by operator"
    },
    "interest_rate": {
      "value": 12.0,
      "note": "Approved product rate"
    }
  }
}
```

## Prepare master templates

### Recommended method: placeholders

Insert placeholders only where variable data belongs:

```text
{{borrower_name}}
{{branch}}
{{loan_product}}
{{loan_amount}}
{{purpose}}
{{tenure_months}}
{{moratorium_months}}
{{interest_rate}}
{{guarantor_name}}
{{property_ownership}}
```

The engine leaves all other text, tables, logos, headers, footers, margins, signatures, and clauses untouched.

### Existing-value replacement method

When the master already contains an old sample borrower, configure `template_map.json`:

```json
{
  "exact_text_to_field": {
    "Mr. Md Ali Ahmed": "borrower_name",
    "Jalalpur Branch": "branch",
    "Tk.40,00,000/-": "loan_amount"
  }
}
```

Exact-value mode is less reliable than placeholders when text is split across complex ODT spans. Convert each variable location to a placeholder once for the strongest preservation.

## Generate controlled Notesheet and Sanction Letter

```powershell
python -m pcia.cli `
  --proposal "D:\Cases\Customer Proposal.zip" `
  --work-root "D:\PCIA_CASES" `
  --operator-decisions ".\config\operator_decisions.customer.json" `
  --notesheet-template "D:\PCIA\Templates\Master Notesheet Pubali Abashon.odt" `
  --sanction-template "D:\PCIA\Templates\Master Sanction Letter Pubali Abashon.odt" `
  --template-map ".\config\template_map.customer.json" `
  --leakage-term "Ali Ahmed" `
  --leakage-term "Jalalpur Branch" `
  --ocr
```

Conflicting or missing values become `PENDING VERIFICATION` in controlled drafts. Do not use `--final` until every critical value is authoritative.

## Final generation

```powershell
python -m pcia.cli `
  --proposal "D:\Cases\Customer Proposal.zip" `
  --work-root "D:\PCIA_CASES" `
  --operator-decisions ".\config\operator_decisions.customer.json" `
  --notesheet-template "D:\PCIA\Templates\Master Notesheet Pubali Abashon.odt" `
  --sanction-template "D:\PCIA\Templates\Master Sanction Letter Pubali Abashon.odt" `
  --template-map ".\config\template_map.customer.json" `
  --leakage-term "Ali Ahmed" `
  --leakage-term "Jalalpur Branch" `
  --final
```

Before issuing any final document, open:

- `notesheet_quality_gate.json`
- `sanction_quality_gate.json`

Both must show:

```json
{
  "remaining_placeholders": [],
  "leakage_hits": [],
  "passed": true
}
```

## Run as a local Flask service

```powershell
python app.py
```

Open `http://127.0.0.1:5050`. The API accepts multipart uploads at `POST /process` and returns a case download URL.

## Add a new proposal/document type

1. Run the proposal once.
2. Inspect `evidence_ledger.csv` and rejected candidates.
3. Add precise label-value patterns to `config/field_rules.json`.
4. Add the most reliable source order to `config/source_priority.json`.
5. Add required fields/documents for the borrower class in `pcia/config.py`.
6. Add the old model values to the leakage-term list or template map.
7. Run regression tests before using the new rule.

Never add a broad “first name/first amount in the document” rule. Every extracted value must remain traceable to file, page, document type, pattern, and confidence.

## Tests

```powershell
python -m unittest discover -s tests -v
```

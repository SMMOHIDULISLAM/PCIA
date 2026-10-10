PCIA FINAL - FIRST USE
======================

1. Extract this ZIP so that the files are directly inside:

   D:\PCIA

   Correct: D:\PCIA\START_PCIA.cmd
   Wrong:   D:\PCIA\PCIA_FINAL\START_PCIA.cmd

2. Double-click START_PCIA.cmd.

3. On first use, wait while the required Python packages are installed.
   The black window must remain open while PCIA is being used.

4. PCIA opens automatically at:

   http://127.0.0.1:5050

5. To stop PCIA, double-click STOP_PCIA.cmd.

6. Optional: double-click CREATE_DESKTOP_SHORTCUTS.cmd once to create
   START PCIA and STOP PCIA icons on the Desktop.

CORE WORKFLOW
=============

A. Template Library
   Upload an editable ODT or DOCX master Notesheet, Sanction Letter,
   Forwarding Letter, or other master proforma. Replace/delete/download
   templates as needed. Replaced templates are backed up for 30 days.

B. New Case
   Select one master template. Upload a ZIP or multiple borrower/branch
   documents. PCIA reads the model first, extracts evidence from the new
   case documents, maps required information and prepares a preview.

C. Preview
   Review found, missing and conflicting values. Only missing/conflicting
   values require operator correction. Ordinary fields are not manually
   entered one by one.

D. Generate
   PCIA copies the master and replaces variable values in the body,
   tables, headers, footers and supported text containers. The master is
   never overwritten. A separate audit JSON is produced with the output.

IMPORTANT RULES
===============

- Model structure, layout, fonts, tables, fixed wording, logos, headers,
  footers and signature blocks are preserved.
- New borrower/case values replace model borrower values.
- Missing data is written as N/F. Old model borrower data is never used
  as a fallback.
- If an old mapped model identity remains, generation is blocked.
- The included model-learning checklist and JSON rules are authoritative.

SUPPORTED INPUTS
================

Templates: ODT, DOCX, DOC (DOC requires LibreOffice conversion).
Evidence: ZIP, PDF, DOCX, DOC, ODT, XLSX, XLS, ODS, CSV, TXT, RTF,
          JSON, XML, HTML and common image formats.

OCR
===

For scanned images/PDFs, install Tesseract OCR on Windows for automatic
OCR. Without Tesseract, readable text-based files still work; values that
cannot be read are marked N/F rather than guessed.

TROUBLESHOOTING
===============

- If the browser says 127.0.0.1 refused to connect, read the black PCIA
  window. It shows the exact startup error.
- If the Python environment is damaged, run RESET_PCIA_ENVIRONMENT.cmd,
  then START_PCIA.cmd.
- Do not close the black window while working.

PCIA v1.1.3 IMPORTANT UPGRADE
-----------------------------
- Files are no longer trusted or classified by filename alone.
- Every PDF page and every internal document section is classified by content.
- The branch forwarding is the primary source for borrower, product, profession, purpose, amount and tenure.
- A service holder is processed through service/employment/salary data, not businessman-only fields.
- When the selected master and branch-forwarding product differ, an operator-decision panel appears before generation.
- The Preview screen now shows anomalies, source classifications and a Regional Office anomaly-letter download.
- N/F is used only after all uploaded documents have been searched.

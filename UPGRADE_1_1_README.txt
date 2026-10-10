PCIA v1.1.3 UPGRADE
===================

1. Every uploaded file is read. A multi-page PDF is treated as a packet containing several internal documents.
2. Pages/sections are classified by content: branch forwarding, repayment assessment, liability certificate,
   physical verification, valuation/property schedule, legal-document verification and others.
3. The strongest source is selected by field:
   - Branch forwarding: product, purpose, amount, tenure, borrower and account.
   - Repayment assessment: salary, income, expenses, installment, DBR and CIB.
   - Liability certificate: borrower/guarantor liability.
   - Valuation/property schedule: security, land, flat and value.
4. Service holders use employment/service/salary fields. Business-only requirements can become N/A.
5. When model product and branch product differ, the operator must choose:
   - use branch product with selected structure;
   - keep model product; or
   - stop and change the model.
6. The case preview shows anomalies and internal document classifications.
7. Download "Anomaly & Shortcoming Letter" to issue a Regional Office correction letter to the branch.
8. N/F is used only after all uploaded evidence has been searched.

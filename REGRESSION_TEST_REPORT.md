# Regression Test Report — v1.2.0

## Automated tests

`python -m unittest discover -s tests -v`

Result: **10/10 passed**.

Covered rules:

- Reject form labels as people.
- Process ZIP and resolve core fields.
- Preserve template leakage gate.
- Extract Pubali facility and financial tables.
- Compare account formatting semantically while preserving display.
- Treat segmented full account and direct 13-digit account as equivalent.
- Separate typed short accounts from full accounts.
- Separate firm and individual names.
- Treat Mia/Miah as an acceptable spelling variation.
- Retain both Smart and old NID formats.
- Separate general and branch-recommended interest rates.

## Live Bandhan Agro test

- Source: uploaded Bandhan Agro proposal ZIP.
- Files: 14.
- Pages/sections: 47.
- Missing fields: 0.
- Missing document categories: 0.
- Confirmed father name: **Md. Todoris Mia**, supplied through an operator-decision JSON rather than hardcoded into the universal engine.
- General/default rate: **13%**.
- Branch-recommended rate: **12%**.
- NID: both 10-digit and 17-digit values retained.
- Firm: **Bandhan Agro & Poultry Farm**.
- Proprietor: **Md. Afu Mia/Miah**, treated as an acceptable spelling variation.
- Remaining true issue: differing full account numbers require operator confirmation.

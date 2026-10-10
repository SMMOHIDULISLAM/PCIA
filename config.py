from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PACKAGE_ROOT / "config"

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".odt", ".xlsx", ".xlsm", ".txt", ".csv", ".json",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".doc", ".xls", ".ods",
}

CORE_REQUIRED_FIELDS = [
    "borrower_name",
    "branch",
    "loan_product",
    "loan_amount",
    "purpose",
    "tenure_months",
]

BORROWER_TYPE_REQUIRED_FIELDS = {
    "government_service": ["designation", "employer", "monthly_income", "nid", "date_of_birth"],
    "salaried": ["designation", "employer", "monthly_income", "nid", "date_of_birth"],
    "expatriate": ["passport_number", "visa_status", "foreign_employer", "monthly_income", "remittance_evidence"],
    "business": ["business_name", "business_nature", "trade_license", "sales", "net_profit", "bank_turnover"],
    "professional": ["profession", "monthly_income", "nid", "tax_id"],
    "unknown": [],
}

DOCUMENT_REQUIREMENTS = {
    "government_service": ["nid", "loan_application", "forwarding", "cib", "income_proof"],
    "salaried": ["nid", "loan_application", "forwarding", "cib", "income_proof"],
    "expatriate": ["nid", "loan_application", "forwarding", "cib", "passport", "income_proof", "remittance_proof"],
    "business": ["nid", "loan_application", "forwarding", "cib", "trade_license", "financial_statement", "bank_statement"],
    "professional": ["nid", "loan_application", "forwarding", "cib", "income_proof"],
    "unknown": ["nid", "loan_application", "forwarding", "cib"],
}

CRITICAL_FIELDS = {
    "borrower_name", "branch", "loan_product", "loan_amount", "purpose", "tenure_months",
    "interest_rate", "property_ownership", "project_cost", "monthly_income",
}

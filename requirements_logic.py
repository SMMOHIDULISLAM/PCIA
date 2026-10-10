from __future__ import annotations

from .config import BORROWER_TYPE_REQUIRED_FIELDS, CORE_REQUIRED_FIELDS, DOCUMENT_REQUIREMENTS
from .models import DocumentPage, FieldResolution


DOCUMENT_EQUIVALENTS: dict[str, set[str]] = {
    "loan_application": {"loan_application", "credit_appraisal"},
    "cib": {"cib", "credit_appraisal"},
    "bank_statement": {"bank_statement", "limit_utilization", "credit_appraisal"},
    "financial_statement": {"financial_statement", "credit_appraisal", "loan_application"},
    "trade_license": {"trade_license", "loan_application"},
}


def missing_fields_for_type(
    borrower_type: str,
    resolutions: dict[str, FieldResolution],
) -> list[str]:
    required = CORE_REQUIRED_FIELDS + BORROWER_TYPE_REQUIRED_FIELDS.get(borrower_type, [])
    missing: list[str] = []
    for field_name in required:
        resolution = resolutions.get(field_name)
        if resolution is None or resolution.selected_value in {None, ""}:
            missing.append(field_name)
    return sorted(set(missing))


def missing_documents_for_type(borrower_type: str, pages: list[DocumentPage]) -> list[str]:
    present = {page.document_type for page in pages if page.readable}
    required = DOCUMENT_REQUIREMENTS.get(borrower_type, DOCUMENT_REQUIREMENTS["unknown"])
    missing: list[str] = []
    for required_type in required:
        acceptable = DOCUMENT_EQUIVALENTS.get(required_type, {required_type})
        if not (present & acceptable):
            missing.append(required_type)
    return sorted(missing)

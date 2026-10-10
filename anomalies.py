from __future__ import annotations

from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta

from .models import DocumentPage, FieldResolution
from .validate import parse_date


def detect_anomalies(
    pages: list[DocumentPage],
    resolutions: dict[str, FieldResolution],
    borrower_type: str,
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []

    component_fields = {
        "account_number_full", "account_number_cd", "account_number_sb", "account_number_std",
        "account_number_snd", "account_number_cc", "account_number_od", "account_number_fdr",
        "account_number_dps", "nid_10_digit", "nid_13_digit", "nid_17_digit",
        "general_interest_rate", "branch_recommended_rate", "approved_interest_rate",
    }
    for field_name, resolution in sorted(resolutions.items()):
        if field_name in component_fields:
            continue
        if resolution.status == "conflict":
            anomalies.append(
                {
                    "severity": "High" if field_name in {"borrower_name", "branch", "loan_product", "loan_amount", "project_cost", "property_ownership"} else "Medium",
                    "category": "conflicting_information",
                    "field": field_name,
                    "issue": f"Conflicting values found for {field_name.replace('_', ' ')}.",
                    "selected": resolution.selected_value,
                    "alternatives": resolution.alternatives,
                    "action": "Operator confirmation required before final generation.",
                }
            )

    age = _value(resolutions, "age")
    dob = _value(resolutions, "date_of_birth")
    application_date = _value(resolutions, "application_date") or date.today().isoformat()
    if age is not None and dob:
        dob_date = parse_date(str(dob))
        app_date = parse_date(str(application_date))
        if dob_date and app_date:
            calculated = relativedelta(app_date, dob_date).years
            if abs(int(age) - calculated) >= 1:
                anomalies.append(
                    {
                        "severity": "High",
                        "category": "age_mismatch",
                        "issue": f"Stated age {age} does not agree with DOB-derived age {calculated} on {app_date.isoformat()}.",
                        "action": "Use verified NID/DOB and correct the application form.",
                    }
                )

    if borrower_type == "expatriate":
        present_types = {page.document_type for page in pages if page.readable}
        missing = [x for x in ["passport", "income_proof", "remittance_proof"] if x not in present_types]
        if missing:
            anomalies.append(
                {
                    "severity": "High",
                    "category": "unsupported_expatriate_income",
                    "issue": "Expatriate status or overseas income is mentioned, but supporting documents are incomplete.",
                    "missing_document_types": missing,
                    "action": "Obtain passport/visa, foreign employment, salary and remittance evidence before relying on income.",
                }
            )

    for field_name in ["valuation_date", "cib_date", "application_date", "forwarding_date", "account_opening_date"]:
        resolution = resolutions.get(field_name)
        if resolution and resolution.status == "missing":
            continue
        if resolution and resolution.selected_value and parse_date(str(resolution.selected_value)) is None:
            anomalies.append(
                {
                    "severity": "Critical",
                    "category": "invalid_date",
                    "field": field_name,
                    "issue": f"Invalid or impossible date found for {field_name.replace('_', ' ')}.",
                    "action": "Obtain a corrected signed document.",
                }
            )

    return anomalies


def _value(resolutions: dict[str, FieldResolution], field_name: str):
    resolution = resolutions.get(field_name)
    return None if resolution is None else resolution.selected_value

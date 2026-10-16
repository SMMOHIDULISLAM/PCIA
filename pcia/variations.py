from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import EvidenceCandidate, FieldResolution
from .semantics import canonical_account_number, canonical_person_name, classify_entity_name


def build_variation_explanations(
    candidates: list[EvidenceCandidate],
    resolutions: dict[str, FieldResolution],
) -> list[dict[str, Any]]:
    explanations: list[dict[str, Any]] = []
    valid = [c for c in candidates if c.valid]

    # Account formatting styles: preserve originals, compare digits only.
    accounts: dict[str, list[EvidenceCandidate]] = defaultdict(list)
    for c in valid:
        if c.field_name == "account_number":
            canonical = canonical_account_number(str(c.value))
            if canonical:
                accounts[canonical].append(c)
    for canonical, items in sorted(accounts.items()):
        displays = sorted({str(x.value) for x in items})
        if len(displays) > 1:
            explanations.append({
                "category": "account_formatting_variation",
                "classification": "Formatting variation — not an anomaly",
                "canonical_account_key": canonical,
                "written_forms": displays,
                "rule": "Spaces, hyphens and slashes are normalized for comparison. A CD/SB/STD prefix is retained when it identifies a separate short account style; original display is preserved.",
            })

    full_styles = sorted({str(c.value) for c in valid if c.field_name == "account_number" and ":" not in canonical_account_number(str(c.value))})
    typed_styles = sorted({str(c.value) for c in valid if c.field_name == "account_number" and ":" in canonical_account_number(str(c.value))})
    if full_styles and typed_styles:
        explanations.append({
            "category": "account_style_variation",
            "classification": "Different account writing styles — retained separately, not automatically an anomaly",
            "full_or_segmented_forms": full_styles,
            "typed_short_forms": typed_styles,
            "rule": "Direct/segmented full account numbers and CD/SB/STD short account numbers are separate representations. Conflicts are checked only within the same representation style.",
        })

    # Mia/Miah and equivalent canonical comparisons.
    for field in ["borrower_name", "proprietor_name", "father_name", "mother_name", "spouse_name", "guarantor_name"]:
        groups: dict[str, set[str]] = defaultdict(set)
        for c in valid:
            if c.field_name == field:
                groups[canonical_person_name(str(c.value))].add(str(c.value))
        for canonical, forms in sorted(groups.items()):
            if len(forms) > 1 and any("miah" in x.lower() for x in forms) and any("mia" in x.lower() for x in forms):
                explanations.append({
                    "category": "acceptable_spelling_variation",
                    "field": field,
                    "classification": "Mia/Miah variation — not an anomaly",
                    "canonical_comparison": canonical,
                    "written_forms": sorted(forms),
                    "rule": "The highest-priority official source controls output spelling; all source spellings remain in the evidence ledger.",
                })

    # Both old and smart NID formats are retained.
    nid10 = resolutions.get("nid_10_digit")
    nid17 = resolutions.get("nid_17_digit")
    nid13 = resolutions.get("nid_13_digit")
    found = {}
    if nid10 and nid10.selected_value:
        found["10_digit_smart_nid"] = nid10.selected_value
    if nid13 and nid13.selected_value:
        found["13_digit_legacy_nid"] = nid13.selected_value
    if nid17 and nid17.selected_value:
        found["17_digit_old_nid"] = nid17.selected_value
    if len(found) > 1:
        explanations.append({
            "category": "nid_format_variation",
            "classification": "Multiple valid NID formats — not automatically an anomaly",
            "values": found,
            "rule": "Keep every valid length separately. Flag only two different numbers of the same NID length or evidence that numbers belong to different people.",
        })

    # General, branch-recommended and approved rates are different semantic fields.
    rate_values = {}
    for key, label in [
        ("general_interest_rate", "general/default rate"),
        ("branch_recommended_rate", "branch-recommended rate"),
        ("approved_interest_rate", "final approved rate"),
    ]:
        r = resolutions.get(key)
        if r and r.selected_value is not None:
            rate_values[label] = r.selected_value
    if len(set(rate_values.values())) > 1:
        explanations.append({
            "category": "interest_rate_context",
            "classification": "Different rate roles — not automatically an anomaly",
            "values": rate_values,
            "controlling_rule": "Final approval > branch recommendation > general/default product rate.",
        })

    # Firm / individual separation.
    business = resolutions.get("business_name")
    proprietor = resolutions.get("proprietor_name") or resolutions.get("borrower_name")
    if business and business.selected_value:
        entity_class = classify_entity_name(str(business.selected_value))
        explanations.append({
            "category": "entity_classification",
            "classification": entity_class,
            "business_or_firm": business.selected_value,
            "individual_borrower_or_proprietor": proprietor.selected_value if proprietor else None,
            "rule": "Firm and individual names are stored separately. M/s and business-ending terms support firm classification; otherwise the case is marked NOT CLEAR for operator review.",
        })

    return explanations

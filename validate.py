from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from dateutil import parser as date_parser

from .utils import digits_only, normalize_spaces, normalize_text
from .semantics import canonical_account_number, classify_entity_name


DEFAULT_REJECT_VALUES = {
    "no. and", "no and", "maintained", "person contacted", "company structure",
    "year in present business", "name", "address", "branch", "account no",
    "applicant", "borrower", "guarantor", "n/a", "na", "nil", "not applicable",
    "yes", "no", "submitted", "not found", "available", "review required",
    "your branch", "our branch", "concerned branch", "the branch",
}

NAME_STOPWORDS = {
    "branch", "bank", "manager", "head", "company", "structure", "contacted",
    "business", "year", "present", "application", "form", "borrower", "guarantor", "account", "no",
}


def parse_date(value: str) -> date | None:
    value = normalize_spaces(value)
    if not value:
        return None
    try:
        parsed = date_parser.parse(value, dayfirst=True, fuzzy=False)
        if parsed.year < 1900 or parsed.year > 2100:
            return None
        return parsed.date()
    except (ValueError, OverflowError, TypeError):
        return None


def validate_candidate(field_name: str, value: Any) -> tuple[bool, str, Any, str]:
    raw = normalize_spaces(str(value or ""))
    norm = normalize_text(raw)
    if not raw:
        return False, "empty", value, norm
    if norm in DEFAULT_REJECT_VALUES:
        return False, "known label or placeholder", value, norm

    if field_name in {"borrower_name", "proprietor_name", "father_name", "mother_name", "spouse_name", "guarantor_name"}:
        cleaned = re.sub(r"\b(mr|mrs|ms|miss|md|mohammad|mst)\.?\s+", lambda m: m.group(0), raw, flags=re.I)
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", cleaned)
        if len(words) < 2 or len(words) > 8:
            return False, "name must contain 2-8 alphabetic words", value, norm
        if any(word.casefold() in NAME_STOPWORDS for word in words):
            return False, "form label mistaken for a name", value, norm
        if re.search(r"\d", raw):
            return False, "name contains digits", value, norm
        return True, "", normalize_spaces(raw), normalize_text(raw)

    if field_name == "business_name":
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", raw)
        bad_fragments = [
            "name of bank", "account no", "monthly loan installments", "copy to be attached",
            "short term loan", "type of facility", "purpose of facility", "recommendation of branch",
            "dbr =", "comments", "limit/amount",
        ]
        if len(words) < 2 or len(words) > 14:
            return False, "business name must contain 2-14 words", value, norm
        if any(fragment in norm for fragment in bad_fragments) or raw.lstrip().startswith("("):
            return False, "form text mistaken for business name", value, norm
        entity_class = classify_entity_name(raw)
        if entity_class == "individual":
            return False, "individual name supplied where a firm name was expected", value, norm
        return True, "" if entity_class == "firm" else "entity type not clear", normalize_spaces(raw), norm

    if field_name == "loan_product":
        bad_products = {"comments", "recommended", "limit", "purpose of facility", "loan amount / limit", "name of the borrower", "purposed limit/amount"}
        if norm in bad_products or len(raw) > 120:
            return False, "form label mistaken for loan product", value, norm
        return True, "", normalize_spaces(raw), norm

    if field_name == "purpose":
        bad_purposes = {"limit/amount", "purpose of facility", "pubali krishi uddokta"}
        if norm in bad_purposes or "mode of repayment" in norm or len(raw) > 500:
            return False, "form label mistaken for purpose", value, norm
        return True, "", normalize_spaces(raw), norm

    if field_name == "age":
        numbers = re.findall(r"\d{1,3}", raw)
        if not numbers:
            return False, "age is not numeric", value, norm
        age = int(numbers[0])
        if not 18 <= age <= 100:
            return False, "implausible adult age", value, str(age)
        return True, "", age, str(age)

    if field_name in {"nid", "nid_10_digit", "nid_13_digit", "nid_17_digit", "spouse_nid", "guarantor_nid"}:
        digits = digits_only(raw)
        if len(digits) not in {10, 13, 17}:
            return False, "NID must have 10, 13, or 17 digits", value, digits
        return True, "", digits, digits

    if field_name in {"mobile", "spouse_mobile", "guarantor_mobile"}:
        digits = digits_only(raw)
        if len(digits) == 13 and digits.startswith("880"):
            digits = "0" + digits[3:]
        if not re.fullmatch(r"01\d{9}", digits):
            return False, "invalid Bangladesh mobile number", value, digits
        return True, "", digits, digits

    if field_name in {"loan_amount", "project_cost", "monthly_income", "market_value", "forced_sale_value", "net_worth", "bank_turnover", "sales", "net_profit", "stock_value", "daily_sales", "monthly_net_profit"}:
        numeric_match = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", raw)
        if not numeric_match:
            return False, "amount is not numeric", value, norm
        amount = float(numeric_match.group().replace(",", ""))
        if re.search(r"\b(?:crore|cr\.?)\b", norm, flags=re.I):
            amount *= 10_000_000
        elif re.search(r"\b(?:lac|lakh)\b", norm, flags=re.I):
            amount *= 100_000
        if amount <= 0:
            return False, "amount must be positive", value, norm
        return True, "", amount, f"{amount:.2f}"

    if field_name in {"interest_rate", "general_interest_rate", "branch_recommended_rate", "approved_interest_rate"}:
        m = re.search(r"\d+(?:\.\d+)?", raw)
        if not m:
            return False, "rate is not numeric", value, norm
        rate = float(m.group())
        if not 0 < rate < 100:
            return False, "rate outside valid range", value, str(rate)
        return True, "", rate, f"{rate:.4f}"

    if field_name in {"tenure_months", "moratorium_months"}:
        m = re.search(r"\d+", raw)
        if not m:
            return False, "tenure is not numeric", value, norm
        count = int(m.group())
        if "year" in norm:
            count *= 12
        if not 0 <= count <= 360:
            return False, "tenure outside supported range", value, str(count)
        return True, "", count, str(count)

    if field_name in {"date_of_birth", "application_date", "forwarding_date", "account_opening_date", "cib_date", "valuation_date"}:
        parsed = parse_date(raw)
        if parsed is None:
            return False, "invalid or impossible date", value, norm
        return True, "", parsed.isoformat(), parsed.isoformat()

    if field_name == "branch":
        if "branch" not in norm:
            return False, "branch value does not contain 'Branch'", value, norm
        bad_phrases = {
            "our branch", "your branch", "of our branch", "of your branch",
            "recommendation of the branch", "head of branch", "branch manager",
            "concerned branch", "the branch", "site verification yes recommendation of the branch",
        }
        reject_fragments = [
            "our branch", "your branch", "recommendation of", "recommended branch", "name of the branch",
            "head of branch", "counter signed", "years at", "bank name branch", "concerned branch", "pubali bank limited",
        ]
        if norm in bad_phrases or any(fragment in norm for fragment in reject_fragments):
            return False, "form phrase mistaken for branch name", value, norm
        if len(re.findall(r"[A-Za-z]+", raw)) > 8:
            return False, "branch value is too long", value, norm
        return True, "", normalize_spaces(raw), norm

    if field_name == "account_number":
        digits = digits_only(raw)
        if not 5 <= len(digits) <= 20:
            return False, "invalid account number length", value, digits
        canonical = canonical_account_number(raw)
        # Keep the exact written form for output; use semantic canonical form for comparison.
        return True, "", normalize_spaces(raw), canonical

    if len(raw) > 1000:
        return False, "value too long", value, norm
    return True, "", raw, norm

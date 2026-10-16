from __future__ import annotations

import re
from typing import Literal

from .utils import normalize_spaces, normalize_text


FIRM_INDICATORS = {
    "m/s", "ms", "limited", "ltd", "enterprise", "enterprises", "trader", "traders",
    "trading", "firm", "company", "co", "industries", "industry", "agro", "poultry",
    "farm", "rice mill", "auto rice mill", "pharmacy", "store", "motors", "construction",
    "library", "timber", "sawmill", "agency", "corporation", "sanitary", "medical",
    "fashion", "bostraloy", "feed", "restaurant", "hotel", "bakery", "transport",
    "engineering", "electronics", "telecom", "computer", "printing", "fisheries",
}

PERSON_TITLES = {"mr", "mrs", "ms", "miss", "md", "mohammad", "mst", "mosammat", "dr"}
COMMON_PERSON_SUFFIXES = {"mia", "miah", "ahmed", "uddin", "islam", "hossain", "hosain", "akter", "akther", "begum", "sarker", "das", "ali", "rahman", "khan"}


def canonical_person_name(value: str) -> str:
    """Canonical form used only for comparison, never for output replacement."""
    text = normalize_text(value)
    text = re.sub(r"\bmiah\b", "mia", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return normalize_spaces(text)


def classify_entity_name(value: str) -> Literal["firm", "individual", "not_clear"]:
    raw = normalize_spaces(value)
    norm = normalize_text(raw)
    if not raw:
        return "not_clear"

    if re.match(r"^m\s*/?\s*s\b", norm):
        return "firm"
    for indicator in FIRM_INDICATORS:
        if re.search(rf"\b{re.escape(indicator)}\b", norm):
            return "firm"

    words = re.findall(r"[a-z]+", norm)
    meaningful = [w for w in words if w not in PERSON_TITLES]
    if 2 <= len(meaningful) <= 5 and (
        meaningful[-1] in COMMON_PERSON_SUFFIXES
        or any(w in PERSON_TITLES for w in words)
    ):
        return "individual"

    return "not_clear"


def account_digits(value: str) -> str:
    return "".join(re.findall(r"\d", value or ""))


def canonical_account_number(value: str) -> str:
    """Normalize recognized bank writing styles without losing the original display value.

    Examples:
    - 3043901007337 -> 3043901007337
    - 3043-901-7337 -> 3043901007337 (last component padded to six digits)
    - CD-24040 -> CD:24040
    """
    raw = normalize_spaces(value)
    typed = re.fullmatch(r"(?i)(CD|SB|STD|SND|CC|OD|FDR|DPS)\s*[/\- ]*\s*(\d{4,20})", raw)
    if typed:
        return f"{typed.group(1).upper()}:{typed.group(2)}"

    segmented = re.fullmatch(r"\s*(\d{4})\s*[-/]\s*(\d{3})\s*[-/]\s*(\d{1,6})\s*", raw)
    if segmented:
        branch, product, serial = segmented.groups()
        return branch + product + serial.zfill(6)

    return account_digits(raw)


def account_type(value: str) -> str | None:
    match = re.search(r"\b(CD|SB|STD|SND|CC|OD|FDR|DPS)\b", value or "", flags=re.I)
    return match.group(1).upper() if match else None


def account_display(value: str) -> str:
    return normalize_spaces(value)

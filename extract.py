from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import DocumentPage, EvidenceCandidate
from .utils import load_json, normalize_spaces, normalize_text
from .validate import validate_candidate


BORROWER_PERSON_FIELDS = {
    "father_name", "mother_name", "spouse_name", "nid", "mobile", "date_of_birth",
    "age", "tax_id", "account_number",
}


class EvidenceExtractor:
    def __init__(self, field_rules_path: Path, source_priority_path: Path) -> None:
        self.rules: dict[str, list[dict[str, Any]]] = load_json(field_rules_path)
        self.source_priorities: dict[str, dict[str, int]] = load_json(source_priority_path)

    def extract(self, pages: list[DocumentPage]) -> list[EvidenceCandidate]:
        candidates: list[EvidenceCandidate] = []
        for page in pages:
            role = page.metadata.get("entity_role", "unknown")
            pibs_person_page = role == "borrower" and "02. Name" in page.text and "03. Father" in page.text
            for field_name, rules in self.rules.items():
                # Avoid mapping guarantor or multi-person information into borrower fields.
                if role in {"guarantor", "guarantor_group", "multi_entity"} and field_name in BORROWER_PERSON_FIELDS:
                    continue
                # PIBS personal pages are column-oriented; use the structured parser below.
                if pibs_person_page and field_name in BORROWER_PERSON_FIELDS:
                    continue
                if field_name == "property_ownership" and page.document_type not in {"legal_opinion", "title_deed", "valuation", "declaration"}:
                    continue
                for rule in rules:
                    pattern = re.compile(rule["pattern"], re.IGNORECASE | re.MULTILINE)
                    for match in pattern.finditer(page.text):
                        group_name = rule.get("group", "value")
                        raw_value = match.groupdict().get(group_name) if match.groupdict() else None
                        if raw_value is None and match.groupdict():
                            raw_value = next((v for v in match.groupdict().values() if v is not None), None)
                        if raw_value is None:
                            raw_value = next((g for g in match.groups() if g is not None), match.group(0)) if match.groups() else match.group(0)
                        candidates.append(
                            self._candidate(
                                page,
                                field_name,
                                raw_value,
                                float(rule.get("confidence", 0.70)),
                                rule.get("id", pattern.pattern[:40]),
                                match.group(0)[:500],
                            )
                        )
            candidates.extend(self._extract_structured(page))
        return self._deduplicate(candidates)

    def _candidate(
        self,
        page: DocumentPage,
        field_name: str,
        raw_value: Any,
        confidence: float,
        pattern_id: str,
        raw_match: str = "",
        source_priority_override: int | None = None,
    ) -> EvidenceCandidate:
        raw_text = normalize_spaces(str(raw_value or ""))
        valid, reason, cleaned_value, normalized = validate_candidate(field_name, raw_text)
        if not valid:
            confidence = 0.0
        return EvidenceCandidate(
            field_name=field_name,
            value=cleaned_value,
            normalized_value=normalized,
            relative_path=page.relative_path,
            page_number=page.page_number,
            document_type=page.document_type,
            confidence=confidence,
            source_priority=source_priority_override if source_priority_override is not None else self._priority(field_name, page.document_type),
            pattern_id=pattern_id,
            raw_match=raw_match[:500] if raw_match else raw_text[:500],
            valid=valid,
            rejection_reason=reason,
        )

    def _extract_structured(self, page: DocumentPage) -> list[EvidenceCandidate]:
        output: list[EvidenceCandidate] = []
        tables = page.metadata.get("tables") or []
        text_norm = normalize_text(page.text)

        # Strong case-level patterns common in Pubali FL-59/FL-60 and forwarding forms.
        strong_text_patterns = [
            ("borrower_name", r"\bName of the A/C\s*:\s*(?P<v>[^\n|]{3,120})", 0.995, "structured_name_of_ac"),
            ("business_name", r"\bName of the A/C\s*:\s*(?P<v>[^\n|]{3,120})", 0.995, "structured_business_name_of_ac"),
            ("borrower_name", r"\bBorrower(?:'|’)?s Name\s*&\s*address\s*:\s*(?P<v>[^,\n|]{3,120})", 0.995, "structured_borrower_address"),
            ("business_name", r"\bBorrower(?:'|’)?s Name\s*&\s*address\s*:\s*(?P<v>[^,\n|]{3,120})", 0.995, "structured_business_address"),
            ("proprietor_name", r"\bName of the Proprietor\s*:\s*(?P<v>[A-Za-z][A-Za-z .'-]{2,80})", 0.995, "structured_proprietor"),
            ("purpose", r"\bPurpose of the loan\s*:\s*(?P<v>[^\n|]{5,350})", 0.995, "structured_purpose"),
            ("loan_amount", r"\bLoan Amount Wanted\s*:\s*(?P<v>(?:Tk\.?|BDT)?\s*[0-9,]+(?:\.\d+)?)", 0.995, "structured_amount_wanted"),
            ("tenure_months", r"\bperiod of\s+(?P<v>\d{1,3}\s*(?:years?|months?))", 0.985, "structured_period"),
            ("general_interest_rate", r"\breduced rate of\s+(?P<v>\d{1,2}(?:\.\d+)?\s*%)", 0.985, "structured_reduced_rate"),
            ("account_number", r"\b(?:(?:A/C|Account)\s*No\.?\s*:\s*(?P<v1>[0-9][0-9/\- ]{4,24})|(?P<v2>(?:CD|SB|STD|SND|CC|OD|FDR|DPS)\s*[/\- ]*\s*[0-9]{4,20}))", 0.97, "structured_account"),
        ]
        for field, pattern, confidence, pid in strong_text_patterns:
            for m in re.finditer(pattern, page.text, flags=re.I | re.M):
                output.append(self._candidate(page, field, m.groupdict().get("v") or m.groupdict().get("v1") or m.groupdict().get("v2"), confidence, pid, m.group(0)))

        output.extend(self._extract_pibs_borrower_person(page))
        output.extend(self._extract_first_biodata(page))

        for table in tables:
            rows = [[normalize_spaces(str(cell or "")) for cell in row] for row in table if any(normalize_spaces(str(cell or "")) for cell in row)]
            if not rows:
                continue
            output.extend(self._extract_facility_table(page, rows))
            output.extend(self._extract_financial_table(page, rows, text_norm))
            output.extend(self._extract_account_performance_table(page, rows, text_norm))
            output.extend(self._extract_guarantor_table(page, rows))

        return output

    def _extract_pibs_borrower_person(self, page: DocumentPage) -> list[EvidenceCandidate]:
        if page.metadata.get("entity_role") != "borrower":
            return []
        text = page.text
        output: list[EvidenceCandidate] = []
        block = re.search(
            r"02\. Name\s*\n03\. Father(?:'|’)s Name\s*\n(?P<name>[^\n]+)\n(?P<father>[^\n]+)\n"
            r"04\. Mother(?:'|’)s Name\s*\n05\. Nationality\s*\n(?P<mother>[^\n]+)\n(?P<nationality>[^\n]+)",
            text,
            flags=re.I,
        )
        if block:
            output.append(self._candidate(page, "proprietor_name", block.group("name"), 0.999, "pibs_person_name", block.group(0), 100))
            output.append(self._candidate(page, "father_name", block.group("father"), 0.999, "pibs_father_name", block.group(0), 100))
            output.append(self._candidate(page, "mother_name", block.group("mother"), 0.999, "pibs_mother_name", block.group(0), 100))
        patterns = [
            ("date_of_birth", r"06\. Date of Birth\s*\n(?P<v>\d{1,2}[./-]\d{1,2}[./-]\d{4})"),
            ("nid", r"10\. National ID No\.\s*\n(?P<v>[0-9][0-9\- ]{8,20})"),
            ("spouse_name", r"14\. If Married, Spouse Name\s*\n(?P<v>[A-Za-z][A-Za-z .'-]{2,80})"),
            ("mobile", r"iii\) Mobile\s*\n(?P<v>(?:\+?880|0)?1[3-9][0-9\- ]{8,12})"),
        ]
        for field, pattern in patterns:
            m = re.search(pattern, text, flags=re.I)
            if m:
                output.append(self._candidate(page, field, m.group("v"), 0.995, f"pibs_{field}", m.group(0), 100))
        return output

    def _extract_first_biodata(self, page: DocumentPage) -> list[EvidenceCandidate]:
        if page.metadata.get("entity_role") != "multi_entity":
            return []
        parts = re.split(r"\bBio-\s*Data\b", page.text, flags=re.I)
        if len(parts) < 2:
            return []
        block = parts[1]
        output: list[EvidenceCandidate] = []
        patterns = [
            ("proprietor_name", r"1\. Name\s*:\s*(?P<v>[^\n]+)"),
            ("father_name", r"2\. Father(?:'|’)s Name\s*:\s*(?P<v>[^\n]+)"),
            ("mother_name", r"3\. Mother(?:'|’)s Name\s*:\s*(?P<v>[^\n]+)"),
            ("date_of_birth", r"7\. Date of birth\s*:\s*(?P<v>\d{1,2}[./-]\d{1,2}[./-]\d{4})"),
            ("nid", r"8\. NID No\.\s*:\s*(?P<v>[0-9][0-9\- ]{8,20})"),
            ("mobile", r"14\. Mobile Number\s*:\s*(?P<v>(?:\+?880|0)?1[3-9][0-9\- ]{8,12})"),
        ]
        for field, pattern in patterns:
            m = re.search(pattern, block, flags=re.I)
            if m:
                output.append(self._candidate(page, field, m.group("v"), 0.98, f"biodata_{field}", m.group(0), 92))
        return output

    def _extract_facility_table(self, page: DocumentPage, rows: list[list[str]]) -> list[EvidenceCandidate]:
        output: list[EvidenceCandidate] = []
        for i, row in enumerate(rows):
            header = [normalize_text(c) for c in row]
            joined = " | ".join(header)
            if not ("type of facility" in joined or "type of credit facilities" in joined):
                continue
            col = {name: idx for idx, name in enumerate(header) if name}
            type_idx = next((idx for idx, val in enumerate(header) if "type of facility" in val or "type of credit facilities" in val), None)
            purpose_idx = next((idx for idx, val in enumerate(header) if "purpose" in val), None)
            amount_idx = next((idx for idx, val in enumerate(header) if "amount" in val or "limit" in val), None)
            pricing_idx = next((idx for idx, val in enumerate(header) if "pricing" in val or "interest" in val), None)
            for data_row in rows[i + 1:i + 5]:
                if type_idx is None or type_idx >= len(data_row):
                    continue
                product = normalize_spaces(data_row[type_idx])
                if not product or "type of" in normalize_text(product):
                    continue
                output.append(self._candidate(page, "loan_product", product, 0.995, "table_facility_product", " | ".join(data_row), 98))
                if purpose_idx is not None and purpose_idx < len(data_row) and data_row[purpose_idx]:
                    output.append(self._candidate(page, "purpose", data_row[purpose_idx], 0.86, "table_facility_purpose", " | ".join(data_row), 75))
                if amount_idx is not None and amount_idx < len(data_row) and data_row[amount_idx]:
                    output.append(self._candidate(page, "loan_amount", data_row[amount_idx], 0.995, "table_facility_amount", " | ".join(data_row), 98))
                if pricing_idx is not None and pricing_idx < len(data_row) and data_row[pricing_idx]:
                    output.append(self._candidate(page, "branch_recommended_rate", data_row[pricing_idx], 0.98, "table_facility_pricing_proposed", " | ".join(data_row), 100))
                break

        # Some appraisal forms put product and purpose in a separate two-column table.
        for row in rows:
            if len(row) >= 2 and "krishi uddokta" in normalize_text(row[0]) and row[1]:
                output.append(self._candidate(page, "loan_product", row[0], 0.995, "table_product_two_col", " | ".join(row), 98))
                if "credit" in normalize_text(row[1]) or "working capital" in normalize_text(row[1]):
                    output.append(self._candidate(page, "purpose", row[1], 0.84, "table_purpose_two_col", " | ".join(row), 75))
        return output

    def _extract_financial_table(self, page: DocumentPage, rows: list[list[str]], text_norm: str) -> list[EvidenceCandidate]:
        output: list[EvidenceCandidate] = []
        header_idx = None
        current_col = None
        for i, row in enumerate(rows):
            normalized = [normalize_text(c) for c in row]
            for j, cell in enumerate(normalized):
                if "current year" in cell:
                    header_idx, current_col = i, j
                    break
            if header_idx is not None:
                break
        if header_idx is None or current_col is None:
            return output

        lac_context = "figure in lac taka" in text_norm
        for row in rows[header_idx + 1:]:
            if not row or current_col >= len(row):
                continue
            label = normalize_text(row[0] if row[0] else (row[1] if len(row) > 1 else ""))
            value = row[current_col]
            if not value:
                continue
            raw_value = self._amount_with_context(value, lac_context)
            if "total sale" in label:
                output.append(self._candidate(page, "sales", raw_value, 0.995, "table_current_year_sales", " | ".join(row), 100))
            elif "net profit" in label and "after tax" in label:
                output.append(self._candidate(page, "net_profit", raw_value, 0.995, "table_current_year_net_profit", " | ".join(row), 100))
        return output

    def _extract_account_performance_table(self, page: DocumentPage, rows: list[list[str]], text_norm: str) -> list[EvidenceCandidate]:
        output: list[EvidenceCandidate] = []
        flattened = " ".join(" ".join(row) for row in rows)
        flat_norm = normalize_text(flattened)
        if "credit summation" not in flat_norm and "credit sum" not in flat_norm:
            return output
        lac_context = "figure in lac taka" in text_norm or "amount in lac" in text_norm

        # Standard Limit Utilization Form: direct header and account row.
        header_idx = None
        credit_idx = None
        for i, row in enumerate(rows):
            normalized = [normalize_text(c) for c in row]
            for j, cell in enumerate(normalized):
                if "credit summation" in cell or cell == "credit sum":
                    header_idx, credit_idx = i, j
                    break
            if header_idx is not None:
                break
        if header_idx is not None and credit_idx is not None:
            for row in rows[header_idx + 1:header_idx + 8]:
                if credit_idx < len(row) and row[credit_idx] and any(term in normalize_text(" ".join(row)) for term in ["current account", "cash credit", "2026", "2025", "2024"]):
                    raw = self._amount_with_context(row[credit_idx], lac_context)
                    output.append(self._candidate(page, "bank_turnover", raw, 0.98, "table_credit_summation", " | ".join(row), 100))
                    break

        # FL-60 rows may split the header across rows. Locate the year cell and
        # read the third numeric cell after it: transaction count, debit, credit.
        if not output:
            for row in rows:
                year_index = next((idx for idx, cell in enumerate(row) if re.fullmatch(r"20\d{2}", normalize_spaces(cell))), None)
                if year_index is None:
                    continue
                numeric_cells: list[str] = []
                for cell in row[year_index + 1:]:
                    compact = re.sub(r"\s+", "", cell).replace("..", ".")
                    compact = re.sub(r"(?<=\d)\.(?=\d)", ".", compact)
                    if re.fullmatch(r"\d+(?:\.\d+)?", compact):
                        numeric_cells.append(compact)
                if len(numeric_cells) >= 3:
                    raw = self._amount_with_context(numeric_cells[2], True)
                    output.append(self._candidate(page, "bank_turnover", raw, 0.78, "table_fl60_credit_summation", " | ".join(row), 72))
                    break
        return output

    def _extract_guarantor_table(self, page: DocumentPage, rows: list[list[str]]) -> list[EvidenceCandidate]:
        output: list[EvidenceCandidate] = []
        header_idx = None
        name_idx = None
        header_candidates: list[tuple[int, int, int]] = []
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                norm = normalize_text(cell)
                if "guarantor name" in norm:
                    header_candidates.append((len(norm), i, j))
        if header_candidates:
            _, header_idx, name_idx = min(header_candidates)
        if header_idx is None or name_idx is None:
            return output
        names: list[str] = []
        for row in rows[header_idx + 1:]:
            if name_idx >= len(row):
                continue
            name = normalize_spaces(row[name_idx])
            valid, *_ = validate_candidate("guarantor_name", name)
            if valid:
                names.append(name)
        if names:
            output.append(self._candidate(page, "guarantor_names", "; ".join(names), 0.98, "table_guarantor_names", "; ".join(names), 100))
        return output

    @staticmethod
    def _amount_with_context(value: str, lac_context: bool) -> str:
        cleaned = normalize_spaces(value)
        number_match = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", cleaned.replace(" ", ""))
        if not number_match:
            return cleaned
        number_text = number_match.group()
        try:
            numeric = float(number_text.replace(",", ""))
        except ValueError:
            return cleaned
        if lac_context and numeric < 1000 and "lac" not in normalize_text(cleaned):
            return f"{number_text} Lac"
        return cleaned

    def _priority(self, field_name: str, document_type: str) -> int:
        by_field = self.source_priorities.get(field_name, {})
        return int(by_field.get(document_type, by_field.get("default", 30)))

    @staticmethod
    def _deduplicate(candidates: list[EvidenceCandidate]) -> list[EvidenceCandidate]:
        seen: set[tuple[str, str, str, int]] = set()
        output: list[EvidenceCandidate] = []
        for candidate in sorted(candidates, key=lambda c: (c.field_name, c.relative_path.casefold(), c.page_number, c.normalized_value)):
            key = (candidate.field_name, candidate.normalized_value, candidate.relative_path, candidate.page_number)
            if key not in seen:
                seen.add(key)
                output.append(candidate)
        return output

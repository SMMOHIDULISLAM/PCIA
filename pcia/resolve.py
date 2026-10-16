from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

from .config import CRITICAL_FIELDS
from .models import EvidenceCandidate, FieldResolution
from .semantics import account_type, canonical_account_number, canonical_person_name, classify_entity_name
from .utils import digits_only, normalize_text


PERSON_NAME_FIELDS = {
    "borrower_name", "proprietor_name", "father_name", "mother_name",
    "spouse_name", "guarantor_name",
}
NID_LENGTH_FIELDS = {10: "nid_10_digit", 13: "nid_13_digit", 17: "nid_17_digit"}
ACCOUNT_TYPE_FIELDS = {"CD", "SB", "STD", "SND", "CC", "OD", "FDR", "DPS"}
RATE_FIELDS = ["approved_interest_rate", "branch_recommended_rate", "general_interest_rate"]


class EvidenceResolver:
    def __init__(self, conflict_score_gap: int = 15) -> None:
        self.conflict_score_gap = conflict_score_gap

    @staticmethod
    def _base_score(candidate: EvidenceCandidate) -> float:
        return candidate.source_priority + candidate.confidence * 100.0

    @staticmethod
    def _canonical_value(field_name: str, normalized_value: str) -> str:
        value = normalize_text(normalized_value)
        if field_name == "branch":
            match = __import__("re").search(r"([a-z][a-z .'-]{1,50}\s+branch)\b", value)
            if match:
                return normalize_text(match.group(1))
        if field_name == "cib_status" and "nil" in value:
            return "nil"
        if field_name in PERSON_NAME_FIELDS:
            return canonical_person_name(value)
        return value

    @staticmethod
    def _prepare_candidates(candidates: list[EvidenceCandidate]) -> list[EvidenceCandidate]:
        """Split NID formats into separate evidence fields while retaining source traceability."""
        prepared: list[EvidenceCandidate] = []
        for candidate in candidates:
            if candidate.field_name == "nid" and candidate.valid:
                digits = digits_only(str(candidate.value))
                mapped = NID_LENGTH_FIELDS.get(len(digits))
                if mapped:
                    prepared.append(replace(candidate, field_name=mapped, value=digits, normalized_value=digits))
                    continue
            if candidate.field_name == "account_number" and candidate.valid:
                kind = account_type(str(candidate.value))
                mapped = f"account_number_{kind.lower()}" if kind in ACCOUNT_TYPE_FIELDS else "account_number_full"
                prepared.append(replace(candidate, field_name=mapped, normalized_value=canonical_account_number(str(candidate.value))))
                continue
            prepared.append(candidate)
        return prepared

    def resolve(
        self,
        candidates: list[EvidenceCandidate],
        operator_decisions: dict[str, Any] | None = None,
    ) -> dict[str, FieldResolution]:
        operator_decisions = operator_decisions or {}
        prepared = self._prepare_candidates(candidates)
        grouped: dict[str, list[EvidenceCandidate]] = defaultdict(list)
        for candidate in prepared:
            if candidate.valid:
                grouped[candidate.field_name].append(candidate)

        # interest_rate, nid and account_number are synthesized after semantic components resolve.
        direct_decisions = {k: v for k, v in operator_decisions.items() if k not in {"interest_rate", "nid", "account_number"}}
        fields = sorted(set(grouped) | set(direct_decisions))
        resolutions: dict[str, FieldResolution] = {}
        for field_name in fields:
            if field_name in direct_decisions:
                decision = direct_decisions[field_name]
                resolutions[field_name] = FieldResolution(
                    field_name=field_name,
                    selected_value=decision.get("value"),
                    normalized_value=normalize_text(decision.get("value")),
                    status="operator_confirmed",
                    confidence=1.0,
                    selected_source={"document_type": "operator_decision", "note": decision.get("note", "")},
                )
                continue

            by_value: dict[str, list[EvidenceCandidate]] = defaultdict(list)
            for candidate in grouped.get(field_name, []):
                canonical = self._canonical_value(field_name, candidate.normalized_value)
                by_value[canonical].append(candidate)

            value_groups: list[tuple[float, str, EvidenceCandidate, list[EvidenceCandidate]]] = []
            for normalized_value, items in by_value.items():
                items_sorted = sorted(
                    items,
                    key=lambda c: (-self._base_score(c), c.relative_path.casefold(), c.page_number, c.pattern_id),
                )
                best = items_sorted[0]
                distinct_files = len({x.relative_path for x in items_sorted})
                distinct_doc_types = len({x.document_type for x in items_sorted})
                corroboration = min(24.0, max(0, distinct_files - 1) * 6.0 + max(0, distinct_doc_types - 1) * 3.0)
                aggregate_score = self._base_score(best) + corroboration
                value_groups.append((aggregate_score, normalized_value, best, items_sorted))

            value_groups.sort(key=lambda x: (-x[0], x[2].relative_path.casefold(), x[2].page_number, x[1]))
            if not value_groups:
                resolutions[field_name] = FieldResolution(
                    field_name=field_name,
                    selected_value=None,
                    normalized_value=None,
                    status="missing",
                    confidence=0.0,
                    selected_source=None,
                )
                continue

            selected_score, selected_norm, selected, selected_items = value_groups[0]
            alternatives: list[dict[str, Any]] = []
            conflict = False
            for score, norm, alternative, items in value_groups[1:]:
                alternatives.append({
                    "value": alternative.value,
                    "normalized_value": norm,
                    "relative_path": alternative.relative_path,
                    "page_number": alternative.page_number,
                    "document_type": alternative.document_type,
                    "confidence": alternative.confidence,
                    "source_priority": alternative.source_priority,
                    "score": score,
                    "corroborating_sources": len({x.relative_path for x in items}),
                })
                if selected_score - score <= self.conflict_score_gap:
                    conflict = True

            status = "conflict" if conflict else "resolved"
            question = ""
            if conflict:
                question = f"Confirm the correct value for {field_name.replace('_', ' ')}."
            elif field_name == "business_name" and classify_entity_name(str(selected.value)) == "not_clear":
                status = "review_required"
                question = "Confirm whether the selected name is a firm/business entity or an individual name."
            elif field_name in CRITICAL_FIELDS and selected.confidence < 0.75:
                status = "review_required"
                question = f"Verify the selected {field_name.replace('_', ' ')} before generation."

            resolutions[field_name] = FieldResolution(
                field_name=field_name,
                selected_value=selected.value,
                normalized_value=selected.normalized_value,
                status=status,
                confidence=selected.confidence,
                selected_source={
                    "relative_path": selected.relative_path,
                    "page_number": selected.page_number,
                    "document_type": selected.document_type,
                    "source_priority": selected.source_priority,
                    "pattern_id": selected.pattern_id,
                    "score": selected_score,
                    "corroborating_sources": len({x.relative_path for x in selected_items}),
                },
                alternatives=alternatives,
                conflict=conflict,
                operator_question=question,
            )

        self._synthesize_nid(resolutions, operator_decisions)
        self._synthesize_account_number(resolutions, operator_decisions)
        self._synthesize_interest_rate(resolutions, operator_decisions)
        return resolutions

    @staticmethod
    def _synthesize_nid(resolutions: dict[str, FieldResolution], operator_decisions: dict[str, Any]) -> None:
        if "nid" in operator_decisions:
            decision = operator_decisions["nid"]
            value = decision.get("value")
            resolutions["nid"] = FieldResolution(
                field_name="nid", selected_value=value, normalized_value=normalize_text(value),
                status="operator_confirmed", confidence=1.0,
                selected_source={"document_type": "operator_decision", "note": decision.get("note", "")},
            )
            return

        found: list[tuple[str, FieldResolution]] = []
        for field_name, label in [
            ("nid_10_digit", "Smart NID"),
            ("nid_13_digit", "13-digit NID"),
            ("nid_17_digit", "Old NID"),
        ]:
            r = resolutions.get(field_name)
            if r and r.selected_value is not None:
                found.append((label, r))
        if not found:
            resolutions["nid"] = FieldResolution("nid", None, None, "missing", 0.0, None)
            return
        display = " / ".join(f"{label}: {r.selected_value}" for label, r in found) if len(found) > 1 else str(found[0][1].selected_value)
        status = "resolved"
        conflict = any(r.status == "conflict" for _, r in found)
        if conflict:
            status = "conflict"
        resolutions["nid"] = FieldResolution(
            field_name="nid",
            selected_value=display,
            normalized_value="|".join(str(r.normalized_value) for _, r in found),
            status=status,
            confidence=max(r.confidence for _, r in found),
            selected_source={
                "document_type": "combined_nid_formats",
                "formats": [label for label, _ in found],
                "note": "Different valid NID lengths are retained separately and are not a conflict by length alone.",
            },
            alternatives=[],
            conflict=conflict,
            operator_question="Confirm conflicting NID numbers of the same length." if conflict else "",
        )


    @staticmethod
    def _synthesize_account_number(resolutions: dict[str, FieldResolution], operator_decisions: dict[str, Any]) -> None:
        if "account_number" in operator_decisions:
            decision = operator_decisions["account_number"]
            value = decision.get("value")
            resolutions["account_number"] = FieldResolution(
                field_name="account_number", selected_value=value, normalized_value=canonical_account_number(str(value)),
                status="operator_confirmed", confidence=1.0,
                selected_source={"document_type": "operator_decision", "note": decision.get("note", "")},
            )
            return

        parts: list[tuple[str, FieldResolution]] = []
        full = resolutions.get("account_number_full")
        if full and full.selected_value is not None:
            parts.append(("Full account", full))
        for kind in sorted(ACCOUNT_TYPE_FIELDS):
            r = resolutions.get(f"account_number_{kind.lower()}")
            if r and r.selected_value is not None:
                parts.append((kind, r))
        if not parts:
            resolutions["account_number"] = FieldResolution("account_number", None, None, "missing", 0.0, None)
            return
        display = " / ".join(f"{label}: {r.selected_value}" for label, r in parts) if len(parts) > 1 else str(parts[0][1].selected_value)
        conflict_parts = [(label, r) for label, r in parts if r.status == "conflict"]
        conflict = bool(conflict_parts)
        alternatives = []
        for label, r in conflict_parts:
            alternatives.extend({**item, "account_style": label} for item in r.alternatives)
        resolutions["account_number"] = FieldResolution(
            field_name="account_number",
            selected_value=display,
            normalized_value="|".join(str(r.normalized_value) for _, r in parts),
            status="conflict" if conflict else "resolved",
            confidence=max(r.confidence for _, r in parts),
            selected_source={
                "document_type": "combined_account_styles",
                "styles": [label for label, _ in parts],
                "note": "Full/segmented and CD/SB/STD short account styles are retained separately; only differing values within the same style are conflicts.",
            },
            alternatives=alternatives,
            conflict=conflict,
            operator_question="Confirm differing account numbers within the same writing style." if conflict else "",
        )

    @staticmethod
    def _synthesize_interest_rate(resolutions: dict[str, FieldResolution], operator_decisions: dict[str, Any]) -> None:
        if "interest_rate" in operator_decisions:
            decision = operator_decisions["interest_rate"]
            value = decision.get("value")
            resolutions["interest_rate"] = FieldResolution(
                field_name="interest_rate", selected_value=value, normalized_value=normalize_text(value),
                status="operator_confirmed", confidence=1.0,
                selected_source={"document_type": "operator_decision", "note": decision.get("note", "")},
            )
            return

        labels = {
            "approved_interest_rate": "final approved rate",
            "branch_recommended_rate": "branch-recommended rate",
            "general_interest_rate": "general/default rate",
        }
        for field_name in RATE_FIELDS:
            r = resolutions.get(field_name)
            if r and r.selected_value is not None:
                resolutions["interest_rate"] = FieldResolution(
                    field_name="interest_rate",
                    selected_value=r.selected_value,
                    normalized_value=r.normalized_value,
                    status=r.status,
                    confidence=r.confidence,
                    selected_source={
                        **(r.selected_source or {}),
                        "rate_role": labels[field_name],
                        "controlling_rule": "Final approval > branch recommendation > general/default rate.",
                    },
                    alternatives=r.alternatives,
                    conflict=r.conflict,
                    operator_question=r.operator_question,
                )
                return
        resolutions["interest_rate"] = FieldResolution("interest_rate", None, None, "missing", 0.0, None)


def classify_borrower_type(full_text: str, resolutions: dict[str, FieldResolution]) -> str:
    text = normalize_text(full_text)
    buckets = {
        "government_service": ["government employee", "govt employee", "government service", "assistant teacher", "primary school"],
        "expatriate": ["expatriate", "non resident", "non-resident", "passport", "visa", "remittance", "uk", "saudi", "dubai", "qatar"],
        "business": ["proprietor", "proprietorship", "business", "trade license", "trade licence", "stock", "sales", "working capital", "agro", "poultry"],
        "professional": ["doctor", "engineer", "lawyer", "architect", "consultant", "chartered accountant"],
        "salaried": ["salary", "designation", "employer", "service holder", "employee"],
    }
    scores = {kind: sum(text.count(term) for term in terms) for kind, terms in buckets.items()}
    winner = max(scores, key=scores.get)
    return winner if scores[winner] > 0 else "unknown"


def build_operator_questions(resolutions: dict[str, FieldResolution]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    # Synthetic fields should not duplicate their component questions.
    skip = {"nid", "interest_rate", "account_number"}
    for field_name, resolution in sorted(resolutions.items()):
        if field_name in skip or resolution.status not in {"conflict", "review_required"}:
            continue
        options = []
        if resolution.selected_value is not None:
            options.append(resolution.selected_value)
        options.extend(item["value"] for item in resolution.alternatives[:5])
        questions.append({
            "field_name": field_name,
            "question": resolution.operator_question,
            "critical": field_name in CRITICAL_FIELDS,
            "options": options,
            "selected_source": resolution.selected_source,
        })
    return questions

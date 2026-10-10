from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ManifestItem:
    relative_path: str
    file_type: str
    size_bytes: int
    sha256: str
    status: str
    page_count: int = 0
    message: str = ""


@dataclass(slots=True)
class DocumentPage:
    relative_path: str
    page_number: int
    text: str
    document_type: str
    extraction_method: str
    readable: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceCandidate:
    field_name: str
    value: Any
    normalized_value: str
    relative_path: str
    page_number: int
    document_type: str
    confidence: float
    source_priority: int
    pattern_id: str
    raw_match: str
    valid: bool = True
    rejection_reason: str = ""


@dataclass(slots=True)
class FieldResolution:
    field_name: str
    selected_value: Any | None
    normalized_value: str | None
    status: str
    confidence: float
    selected_source: dict[str, Any] | None
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    conflict: bool = False
    operator_question: str = ""


@dataclass(slots=True)
class ProcessingResult:
    case_id: str
    case_dir: Path
    manifest: list[ManifestItem]
    pages: list[DocumentPage]
    candidates: list[EvidenceCandidate]
    resolutions: dict[str, FieldResolution]
    borrower_type: str
    missing_fields: list[str]
    missing_documents: list[str]
    anomalies: list[dict[str, Any]]
    operator_questions: list[dict[str, Any]]
    variation_explanations: list[dict[str, Any]] = field(default_factory=list)
    generated_files: list[Path] = field(default_factory=list)

    def to_serializable(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "manifest": [asdict(x) for x in self.manifest],
            "pages": [asdict(x) for x in self.pages],
            "candidates": [asdict(x) for x in self.candidates],
            "resolutions": {k: asdict(v) for k, v in self.resolutions.items()},
            "borrower_type": self.borrower_type,
            "missing_fields": self.missing_fields,
            "missing_documents": self.missing_documents,
            "anomalies": self.anomalies,
            "operator_questions": self.operator_questions,
            "variation_explanations": self.variation_explanations,
            "generated_files": [str(x) for x in self.generated_files],
        }

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .anomalies import detect_anomalies
from .classify import classify_pages
from .config import DEFAULT_CONFIG_DIR
from .extract import EvidenceExtractor
from .ingestion import PackageIngestor
from .models import ProcessingResult
from .readers import DocumentReader
from .reports import ReportWriter, make_result_zip
from .requirements_logic import missing_documents_for_type, missing_fields_for_type
from .resolve import EvidenceResolver, build_operator_questions, classify_borrower_type
from .template_engine import TemplateEngine
from .utils import dump_json, safe_filename
from .variations import build_variation_explanations


class ProposalPipeline:
    def __init__(
        self,
        work_root: Path,
        config_dir: Path | None = None,
        enable_ocr: bool = False,
    ) -> None:
        self.work_root = Path(work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.config_dir = Path(config_dir or DEFAULT_CONFIG_DIR)
        self.ingestor = PackageIngestor()
        self.reader = DocumentReader(enable_ocr=enable_ocr)
        self.extractor = EvidenceExtractor(
            self.config_dir / "field_rules.json",
            self.config_dir / "source_priority.json",
        )
        self.resolver = EvidenceResolver()
        self.report_writer = ReportWriter()
        self.template_engine = TemplateEngine()

    def process(
        self,
        proposal_path: Path,
        operator_decisions_path: Path | None = None,
        notesheet_template: Path | None = None,
        sanction_template: Path | None = None,
        template_map_path: Path | None = None,
        leakage_terms: list[str] | None = None,
        controlled_draft: bool = True,
    ) -> ProcessingResult:
        proposal_path = Path(proposal_path)
        case_id = uuid.uuid4().hex[:12]
        case_dir = self.work_root / case_id
        case_dir.mkdir(parents=True, exist_ok=False)

        source_dir, manifest = self.ingestor.ingest(proposal_path, case_dir)
        pages = self.reader.read_all(source_dir, manifest)
        classify_pages(pages)

        candidates = self.extractor.extract(pages)
        decisions = self._load_operator_decisions(operator_decisions_path)
        resolutions = self.resolver.resolve(candidates, decisions)

        full_text = "\n".join(page.text for page in pages)
        borrower_type = classify_borrower_type(full_text, resolutions)
        missing_fields = missing_fields_for_type(borrower_type, resolutions)
        missing_documents = missing_documents_for_type(borrower_type, pages)
        anomalies = detect_anomalies(pages, resolutions, borrower_type)
        operator_questions = build_operator_questions(resolutions)
        variation_explanations = build_variation_explanations(candidates, resolutions)

        result = ProcessingResult(
            case_id=case_id,
            case_dir=case_dir,
            manifest=manifest,
            pages=pages,
            candidates=candidates,
            resolutions=resolutions,
            borrower_type=borrower_type,
            missing_fields=missing_fields,
            missing_documents=missing_documents,
            anomalies=anomalies,
            operator_questions=operator_questions,
            variation_explanations=variation_explanations,
        )

        generated = self.report_writer.write_all(result)
        values = self.template_engine.build_values(resolutions, controlled_draft=controlled_draft)
        output_dir = case_dir / "outputs"

        if notesheet_template:
            suffix = Path(notesheet_template).suffix.lower()
            output = output_dir / f"Controlled_Notesheet{suffix}"
            quality = self.template_engine.generate(
                Path(notesheet_template), output, values, template_map_path, leakage_terms
            )
            dump_json(output_dir / "notesheet_quality_gate.json", quality)
            generated.extend([output, output_dir / "notesheet_quality_gate.json"])

        if sanction_template:
            suffix = Path(sanction_template).suffix.lower()
            output = output_dir / f"Controlled_Sanction_Letter{suffix}"
            quality = self.template_engine.generate(
                Path(sanction_template), output, values, template_map_path, leakage_terms
            )
            dump_json(output_dir / "sanction_quality_gate.json", quality)
            generated.extend([output, output_dir / "sanction_quality_gate.json"])

        result.generated_files = generated
        dump_json(output_dir / "processing_result.json", result.to_serializable())
        result.generated_files.append(output_dir / "processing_result.json")
        make_result_zip(case_dir, case_dir / f"{case_id}_results.zip")
        result.generated_files.append(case_dir / f"{case_id}_results.zip")
        return result

    @staticmethod
    def _load_operator_decisions(path: Path | None) -> dict[str, Any]:
        if path is None:
            return {}
        with Path(path).open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Accept either {field: {value,note}} or {"decisions": {...}}
        return data.get("decisions", data)

    def purge_case(self, case_id: str) -> None:
        target = self.work_root / safe_filename(case_id)
        if target.exists() and target.is_dir():
            shutil.rmtree(target)

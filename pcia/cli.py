from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import ProposalPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process a banking credit-proposal package.")
    parser.add_argument("--proposal", required=True, type=Path, help="ZIP or single proposal file")
    parser.add_argument("--work-root", type=Path, default=Path("./PCIA_CASES"))
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--ocr", action="store_true", help="Use Tesseract only on unreadable pages/images")
    parser.add_argument("--operator-decisions", type=Path)
    parser.add_argument("--notesheet-template", type=Path)
    parser.add_argument("--sanction-template", type=Path)
    parser.add_argument("--template-map", type=Path)
    parser.add_argument("--leakage-term", action="append", default=[])
    parser.add_argument("--final", action="store_true", help="Do not use PENDING VERIFICATION in template fields")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pipeline = ProposalPipeline(args.work_root, args.config_dir, enable_ocr=args.ocr)
    result = pipeline.process(
        proposal_path=args.proposal,
        operator_decisions_path=args.operator_decisions,
        notesheet_template=args.notesheet_template,
        sanction_template=args.sanction_template,
        template_map_path=args.template_map,
        leakage_terms=args.leakage_term,
        controlled_draft=not args.final,
    )
    payload = {
        "case_id": result.case_id,
        "case_dir": str(result.case_dir.resolve()),
        "result_zip": str((result.case_dir / f"{result.case_id}_results.zip").resolve()),
        "borrower_type": result.borrower_type,
        "missing_fields": result.missing_fields,
        "missing_documents": result.missing_documents,
        "anomaly_count": len(result.anomalies),
        "operator_question_count": len(result.operator_questions),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from werkzeug.utils import secure_filename

from .pipeline import ProposalPipeline


def create_app(work_root: Path | str = "./PCIA_CASES") -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024
    root = Path(work_root).resolve()
    upload_dir = root / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def home():
        return jsonify({
            "service": "PCIA Proposal Processor",
            "usage": "POST multipart/form-data to /process with field proposal_zip",
        })

    @app.post("/process")
    def process_case():
        proposal = request.files.get("proposal_zip")
        if proposal is None or not proposal.filename:
            return jsonify({"error": "proposal_zip is required"}), 400

        proposal_path = upload_dir / f"{os.urandom(5).hex()}_{secure_filename(proposal.filename)}"
        proposal.save(proposal_path)

        saved_optional: dict[str, Path] = {}
        for field in ["notesheet_template", "sanction_template", "template_map", "operator_decisions"]:
            upload = request.files.get(field)
            if upload and upload.filename:
                path = upload_dir / f"{os.urandom(5).hex()}_{secure_filename(upload.filename)}"
                upload.save(path)
                saved_optional[field] = path

        leakage_terms = request.form.getlist("leakage_term")
        enable_ocr = request.form.get("ocr", "false").lower() == "true"
        controlled = request.form.get("controlled_draft", "true").lower() != "false"

        pipeline = ProposalPipeline(root, enable_ocr=enable_ocr)
        result = pipeline.process(
            proposal_path=proposal_path,
            operator_decisions_path=saved_optional.get("operator_decisions"),
            notesheet_template=saved_optional.get("notesheet_template"),
            sanction_template=saved_optional.get("sanction_template"),
            template_map_path=saved_optional.get("template_map"),
            leakage_terms=leakage_terms,
            controlled_draft=controlled,
        )
        return jsonify({
            "case_id": result.case_id,
            "borrower_type": result.borrower_type,
            "missing_fields": result.missing_fields,
            "missing_documents": result.missing_documents,
            "anomalies": len(result.anomalies),
            "operator_questions": result.operator_questions,
            "download_url": f"/download/{result.case_id}",
        })

    @app.get("/download/<case_id>")
    def download_case(case_id: str):
        result_zip = root / case_id / f"{case_id}_results.zip"
        if not result_zip.exists():
            return jsonify({"error": "case not found"}), 404
        return send_file(result_zip, as_attachment=True)

    return app

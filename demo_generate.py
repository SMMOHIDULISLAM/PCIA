from pathlib import Path
import json
import shutil
import tempfile

from pcia_engine import initialize, APP_DIR, TEMPLATES_DIR, safe_unpack_uploads, prepare_case, generate_document


def main() -> None:
    registry = initialize()
    demo = APP_DIR / "demo_inputs" / "SAMPLE_NEW_CLIENT.zip"
    if not demo.exists():
        raise FileNotFoundError(demo)
    evidence_dir = Path(tempfile.mkdtemp(prefix="pcia_demo_evidence_"))
    files = safe_unpack_uploads([demo], evidence_dir)
    output_dir = APP_DIR / "demo_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    for doc_type in ("Notesheet", "Sanction Letter"):
        meta = next(x for x in registry.all() if x["product"] == "Pubali Abashon" and x["doc_type"] == doc_type)
        template = APP_DIR / meta["current_file"]
        mapping = json.loads((TEMPLATES_DIR / meta["id"] / "model_map.json").read_text(encoding="utf-8"))
        state = prepare_case(template, doc_type, files, mapping)
        safe_type = doc_type.replace(" ", "_")
        output = output_dir / f"DEMO_New_Client_{safe_type}{template.suffix.lower()}"
        result = generate_document(template, output, mapping, state["proposed"])
        audit = {
            "template": meta,
            "proposed": state["proposed"],
            "evidence": state["evidence"],
            "documents": state["documents"],
            "generation": result,
        }
        output.with_name(output.stem + "_AUDIT.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{doc_type}: safe={result['safe']}, replacements={result['success_count']}, failures={result['failure_count']}")
        if not result["safe"]:
            raise RuntimeError(f"Unsafe demo output for {doc_type}: {result}")

    shutil.rmtree(evidence_dir, ignore_errors=True)
    print("Demo completed. Open the demo_outputs folder.")


if __name__ == "__main__":
    main()

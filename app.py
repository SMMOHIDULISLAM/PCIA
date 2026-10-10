from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, redirect, render_template_string, request, send_file, url_for

from anomaly_letter import generate_anomaly_letter

from pcia_engine import (
    APP_DIR, CASES_DIR, OUTPUTS_DIR, TEMPLATES_DIR,
    DOC_TYPE_FORWARDING, DOC_TYPE_NOTESHEET, DOC_TYPE_SANCTION,
    FIELD_LABELS, PackageDocument, TemplateRegistry,
    analyze_template, compact_ws, generate_document, initialize,
    prepare_case, safe_unpack_uploads, slug,
)

app = Flask(__name__)
app.secret_key = "pcia-final-local-only"
REGISTRY = initialize()
PID_FILE = APP_DIR / "data" / "pcia.pid"

BASE_CSS = r'''
:root{--blue:#174ea6;--navy:#0d2f58;--green:#067647;--amber:#a15c00;--red:#b42318;--bg:#f3f6fb;--line:#d6dfec}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Segoe UI,Arial,sans-serif;color:#172033}
header{background:linear-gradient(120deg,var(--navy),var(--blue));color:white;padding:17px 28px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 3px 12px #0003}
.brand{font-size:23px;font-weight:800}.tag{font-size:12px;opacity:.85}.nav a{color:white;text-decoration:none;margin-left:18px;font-weight:600}
main{max-width:1250px;margin:24px auto;padding:0 18px}.card{background:white;border:1px solid var(--line);border-radius:13px;padding:20px;margin-bottom:18px;box-shadow:0 2px 9px #14335c12}
h1,h2,h3{margin-top:0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
label{display:block;font-weight:700;margin:10px 0 6px}input[type=text],input[type=file],select,textarea{width:100%;padding:10px 11px;border:1px solid #aebbd0;border-radius:8px;font:inherit;background:white}textarea{min-height:90px}
button,.btn{display:inline-block;border:0;border-radius:8px;padding:10px 15px;background:var(--blue);color:white;font-weight:700;text-decoration:none;cursor:pointer}.btn.secondary{background:#5b6678}.btn.danger{background:var(--red)}.btn.green{background:var(--green)}
.notice{padding:12px 14px;border-left:5px solid #e4ae00;background:#fff8d6;border-radius:6px;margin:12px 0}.ok{color:var(--green);font-weight:700}.warn{color:var(--amber);font-weight:700}.bad{color:var(--red);font-weight:700}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{border:1px solid var(--line);padding:8px;vertical-align:top}th{background:#eaf0f9;text-align:left}.small{font-size:12px;color:#5e6a7d}.pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#eaf0f9;font-size:12px;font-weight:700}.missing{background:#fff1f0}.conflict{background:#fff4df}.found{background:#eefbf4}.footer-note{font-size:12px;color:#627087;text-align:center;padding:25px}
@media(max-width:850px){.grid,.grid3{grid-template-columns:1fr}.nav{display:none}}
'''


def page(title: str, body: str, **ctx):
    template = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} — PCIA</title><style>''' + BASE_CSS + r'''</style></head><body>
<header><div><div class="brand">PCIA</div><div class="tag">Enterprise Credit Processing Platform — Final Core</div></div><nav class="nav"><a href="/">Dashboard</a><a href="/templates">Template Library</a><a href="/case/new">New Case</a><a href="/outputs">Generated Documents</a></nav></header>
<main>{% with messages = get_flashed_messages() %}{% if messages %}{% for m in messages %}<div class="notice">{{m}}</div>{% endfor %}{% endif %}{% endwith %}''' + body + r'''</main><div class="footer-note">Master structure remains untouched. Only mapped variable content is replaced from uploaded evidence.</div></body></html>'''
    return render_template_string(template, title=title, **ctx)


@app.get("/")
def dashboard():
    templates = REGISTRY.all()
    outputs = sorted(OUTPUTS_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    body = r'''
<div class="grid3">
<div class="card"><h3>Templates</h3><div style="font-size:34px;font-weight:800">{{templates|length}}</div><div class="small">Seeded only from your Model ZIP plus future uploads.</div></div>
<div class="card"><h3>Generated Documents</h3><div style="font-size:34px;font-weight:800">{{outputs|length}}</div><div class="small">Each output is a new file. Masters are never overwritten.</div></div>
<div class="card"><h3>Core Rule</h3><div class="ok">Model first → Evidence second → New document</div><div class="small">Missing variable data becomes N/F. Old model borrower data is blocked.</div></div>
</div>
<div class="card"><h2>Start a New Case</h2><p>Choose any editable master template, upload a ZIP or multiple customer/branch files, review only missing or conflicting data, then generate.</p><a class="btn green" href="/case/new">Open New Case</a></div>
<div class="card"><h2>What the engine does</h2><div class="grid"><div><h3>Fixed</h3><p>Page setup, fonts, tables, borders, logos, fixed clauses, signature blocks and structure remain as the model.</p></div><div><h3>Variable</h3><p>Branch, borrower, dates, accounts, addresses, amounts, loan terms, guarantor, security, narratives, checklist status and other mapped case data are replaced.</p></div></div></div>
'''
    return page("Dashboard", body, templates=templates, outputs=outputs)


@app.route("/templates", methods=["GET", "POST"])
def templates_page():
    if request.method == "POST":
        upload = request.files.get("master_file")
        product = compact_ws(request.form.get("product", ""))
        doc_type = request.form.get("doc_type", DOC_TYPE_NOTESHEET)
        if not upload or not upload.filename:
            flash("Select a master file.")
            return redirect(url_for("templates_page"))
        if not product:
            flash("Enter the loan product name.")
            return redirect(url_for("templates_page"))
        temp = APP_DIR / "data" / ("incoming_" + uuid.uuid4().hex[:8] + Path(upload.filename).suffix.lower())
        upload.save(temp)
        try:
            REGISTRY.add(temp, product, doc_type, original_name=Path(upload.filename).name)
            flash("Master uploaded and model map created.")
        except Exception as exc:
            flash(f"Master upload failed: {exc}")
        finally:
            temp.unlink(missing_ok=True)
        return redirect(url_for("templates_page"))

    rows = REGISTRY.all()
    body = r'''
<div class="card"><h2>Upload Master Format</h2><form method="post" enctype="multipart/form-data"><div class="grid3"><div><label>Name of the Loan Type</label><input type="text" name="product" placeholder="e.g., Pubali Abashon" required></div><div><label>Document Type</label><select name="doc_type"><option>Notesheet</option><option>Sanction Letter</option><option>Forwarding Letter</option><option>Other</option></select></div><div><label>Upload Master Format</label><input type="file" name="master_file" accept=".odt,.docx,.doc" required></div></div><button type="submit">Upload and Learn Model</button></form><div class="notice">For exact formatting, editable ODT/DOCX is required. Old DOC is converted when LibreOffice is available. PDF may be evidence, but not an exact editable master.</div></div>
<div class="card"><h2>Template Library</h2><table><tr><th>Loan Product</th><th>Document Type</th><th>Master</th><th>Model Learning</th><th>Actions</th></tr>{% for t in rows %}<tr><td>{{t.product}}</td><td><span class="pill">{{t.doc_type}}</span></td><td>{{t.original_name}}<div class="small">Updated {{t.updated_at}}</div></td><td>{{t.slot_count or 0}} variable placements<br><span class="small">{{t.unresolved_count or 0}} expected fields not located in this model</span></td><td><a class="btn" href="/template/{{t.id}}/learn">Preview Mapping</a> <a class="btn secondary" href="/template/{{t.id}}/download">Download</a><form method="post" action="/template/{{t.id}}/delete" style="display:inline" onsubmit="return confirm('Delete this master?')"><button class="btn danger">Delete</button></form><details style="margin-top:8px"><summary>Replace current master</summary><form method="post" action="/template/{{t.id}}/replace" enctype="multipart/form-data"><input type="file" name="master_file" accept=".odt,.docx,.doc" required><button>Replace (old version backed up)</button></form></details></td></tr>{% endfor %}</table></div>
'''
    return page("Template Library", body, rows=rows)


@app.get("/template/<tid>/learn")
def template_learn(tid: str):
    meta = REGISTRY.get(tid)
    map_path = TEMPLATES_DIR / tid / "model_map.json"
    if not map_path.exists():
        mapping = analyze_template(APP_DIR / meta["current_file"], meta["doc_type"])
        map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    body = r'''
<div class="card"><h2>{{meta.product}} — {{meta.doc_type}}</h2><p><b>{{mapping.slots|length}}</b> variable placements learned across body, tables, headers and footers. Structure and non-variable text are fixed.</p><a class="btn secondary" href="/template/{{meta.id}}/map/download">Download Model Map JSON</a></div>
<div class="card"><h3>Variable Placements</h3><table><tr><th>Field</th><th>Model Value / Paragraph</th><th>Location</th><th>Detection</th></tr>{% for s in mapping.slots %}<tr><td>{{s.label}}</td><td>{{s.old_value}}</td><td>{{s.part}} · block {{s.block_index}}</td><td>{{s.context}}</td></tr>{% endfor %}</table></div>
{% if mapping.unresolved %}<div class="card"><h3>Expected fields not located in this model</h3><p class="small">These are not invented or copied. If the model truly contains one, upload a corrected editable master; otherwise the field is ignored for this template.</p><table><tr><th>Field</th><th>Reason</th></tr>{% for u in mapping.unresolved %}<tr><td>{{u.label}}</td><td>{{u.reason}}</td></tr>{% endfor %}</table></div>{% endif %}
'''
    return page("Model Learning", body, meta=meta, mapping=mapping)


@app.get("/template/<tid>/map/download")
def download_map(tid: str):
    path = TEMPLATES_DIR / tid / "model_map.json"
    return send_file(path, as_attachment=True, download_name=f"PCIA_Model_Map_{tid}.json")


@app.get("/template/<tid>/download")
def download_template(tid: str):
    meta = REGISTRY.get(tid)
    path = APP_DIR / meta["current_file"]
    return send_file(path, as_attachment=True, download_name=meta["original_name"])


@app.post("/template/<tid>/replace")
def replace_template(tid: str):
    upload = request.files.get("master_file")
    if not upload or not upload.filename:
        flash("Select a replacement master.")
        return redirect(url_for("templates_page"))
    temp = APP_DIR / "data" / ("replace_" + uuid.uuid4().hex[:8] + Path(upload.filename).suffix.lower())
    upload.save(temp)
    try:
        REGISTRY.replace(tid, temp)
        flash("Master replaced. The previous version was backed up and will be eligible for cleanup after 30 days.")
    except Exception as exc:
        flash(f"Replacement failed: {exc}")
    finally:
        temp.unlink(missing_ok=True)
    return redirect(url_for("templates_page"))


@app.post("/template/<tid>/delete")
def delete_template(tid: str):
    REGISTRY.delete(tid)
    flash("Master deleted.")
    return redirect(url_for("templates_page"))


@app.get("/case/new")
def new_case():
    templates = [t for t in REGISTRY.all() if t.get("doc_type") in {DOC_TYPE_NOTESHEET, DOC_TYPE_SANCTION, DOC_TYPE_FORWARDING}]
    body = r'''
<div class="card"><h2>New Customer / Borrower Case</h2><form method="post" action="/case/analyze" enctype="multipart/form-data"><div class="grid"><div><label>Select Master Template</label><select name="template_id" required>{% for t in templates %}<option value="{{t.id}}">{{t.product}} — {{t.doc_type}} — {{t.original_name}}</option>{% endfor %}</select><label>Case Name (optional)</label><input type="text" name="case_name" placeholder="New borrower / branch reference"></div><div><label>Upload Customer and Branch Documents</label><input type="file" name="case_files" multiple required><div class="notice">Upload one ZIP or multiple files. PDF, DOCX, DOC, ODT, XLSX/ODS, CSV/TXT and scanned images are read. Data is extracted automatically.</div></div></div><button class="btn green" type="submit">Read Model First, Then Analyze Uploaded Documents</button></form></div>
<div class="card"><h3>Demo</h3><p>Use the included <code>demo_inputs\SAMPLE_NEW_CLIENT.zip</code> with a Pubali Abashon Notesheet or Sanction Letter master.</p></div>
'''
    return page("New Case", body, templates=templates)


@app.post("/case/analyze")
def analyze_case():
    tid = request.form.get("template_id", "")
    if tid not in REGISTRY.index:
        return "Template not found", 404
    uploaded = request.files.getlist("case_files")
    if not any(f and f.filename for f in uploaded):
        flash("Upload customer/branch documents.")
        return redirect(url_for("new_case"))
    case_id = uuid.uuid4().hex[:14]
    cdir = CASES_DIR / case_id
    incoming = cdir / "incoming"
    extracted = cdir / "extracted"
    incoming.mkdir(parents=True)
    saved: list[Path] = []
    for f in uploaded:
        if not f or not f.filename:
            continue
        name = Path(f.filename).name
        p = incoming / name
        f.save(p)
        saved.append(p)
    files = safe_unpack_uploads(saved, extracted)
    meta = REGISTRY.get(tid)
    template = APP_DIR / meta["current_file"]
    map_path = TEMPLATES_DIR / tid / "model_map.json"
    mapping = json.loads(map_path.read_text(encoding="utf-8")) if map_path.exists() else analyze_template(template, meta["doc_type"])
    prepared = prepare_case(template, meta["doc_type"], files, mapping, template_product=meta.get("product", ""))
    state = {
        "case_id": case_id,
        "case_name": compact_ws(request.form.get("case_name", "")) or case_id,
        "template_id": tid,
        "template": str(template),
        "template_meta": meta,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        **prepared,
    }
    (cdir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect(url_for("preview_case", case_id=case_id))


@app.route("/case/<case_id>/preview", methods=["GET"])
def preview_case(case_id: str):
    state_path = CASES_DIR / case_id / "state.json"
    if not state_path.exists():
        return "Case not found", 404
    state = json.loads(state_path.read_text(encoding="utf-8"))
    fields = sorted(state["proposed"].keys(), key=lambda x: FIELD_LABELS.get(x.split("::",1)[0], x))
    rows = []
    old_by_field: dict[str, list[str]] = {}
    for s in state["mapping"].get("slots", []):
        old_by_field.setdefault(s["field"], [])
        if s["old_value"] not in old_by_field[s["field"]]:
            old_by_field[s["field"]].append(s["old_value"])
    for field in fields:
        evid = state["evidence"].get(field, [])
        conflict = state["conflicts"].get(field, [])
        value = state["proposed"][field]
        if value.endswith(" N/F") or value == "N/F" or "NOT FOUND" in value:
            css, status = "missing", "Missing — operator may edit or keep N/F"
        elif conflict:
            css, status = "conflict", "Conflict — highest-confidence value selected; review alternatives"
        else:
            css, status = "found", "Found / generated from uploaded evidence"
        evidence_text = "; ".join(f"{e['value']} — {e['source']} ({e['confidence']}%)" for e in evid[:5]) or status
        rows.append({
            "field": field,
            "label": FIELD_LABELS.get(field.split("::",1)[0], field.replace("doc_status::", "Document: ")),
            "old": " | ".join(old_by_field.get(field, [])),
            "value": value,
            "evidence": evidence_text,
            "css": css,
        })
    body = r'''
<div class="card"><h2>Review Before Generation</h2><p><b>{{state.template_meta.product}}</b> — {{state.template_meta.doc_type}} | {{state.documents|length}} evidence files read.</p><div class="notice">PCIA reads every document and every internal page/section by content. N/F is used only after searching all uploaded evidence.</div><a class="btn danger" href="/case/{{state.case_id}}/anomaly-letter">Download Anomaly & Shortcoming Letter</a></div>
{% if state.operator_questions %}<div class="card conflict"><h3>Operator Decision Required</h3><p>The model and the evidence do not fully agree. PCIA will not silently choose the product/profile.</p>{% for q in state.operator_questions %}<div class="notice"><b>{{q.question}}</b><br><span class="small">Model: {{q.model_value}} | Evidence: {{q.evidence_value}}</span></div>{% endfor %}</div>{% endif %}
{% if state.anomalies %}<div class="card"><h3>Detected Anomalies and Shortcomings</h3><table><tr><th>#</th><th>Severity</th><th>Issue</th><th>Details / Required Action</th></tr>{% for a in state.anomalies %}<tr class="{% if a.severity in ['Critical','High'] %}missing{% else %}conflict{% endif %}"><td>{{loop.index}}</td><td><b>{{a.severity}}</b><br><span class="small">{{a.category}}</span></td><td><b>{{a.title}}</b></td><td>{{a.detail}}<br><span class="small"><b>Action:</b> {{a.action}}</span></td></tr>{% endfor %}</table></div>{% endif %}
<form method="post" action="/case/{{state.case_id}}/finalize">{% if state.operator_questions %}<div class="card"><h3>Operator Decisions</h3>{% for q in state.operator_questions %}<label>{{q.question}}</label><select name="decision__{{q.id}}" required><option value="">-- Select decision --</option>{% for option in q.options %}<option value="{{option}}">{{option}}</option>{% endfor %}</select>{% endfor %}</div>{% endif %}<div class="card"><table><tr><th>Required by Model</th><th>Old Model Content</th><th>New Proposed Content</th><th>Evidence / Status</th></tr>{% for r in rows %}<tr class="{{r.css}}"><td><b>{{r.label}}</b></td><td>{{r.old}}</td><td>{% if r.field in ['brief_history','justification','proposal_subject','sanction_subject','forwarding_subject','forwarding_body','security_details','collateral_details','present_proposal','bm_recommendation','recommendation','risk_analysis','financial_analysis','committee_security'] %}<textarea name="field__{{r.field}}">{{r.value}}</textarea>{% else %}<input type="text" name="field__{{r.field}}" value="{{r.value}}">{% endif %}</td><td class="small">{{r.evidence}}</td></tr>{% endfor %}</table><button class="btn green" type="submit">Generate New {{state.template_meta.doc_type}}</button></div></form>
<div class="card"><h3>Uploaded Evidence Files and Content Classification</h3><table><tr><th>File</th><th>Extracted characters</th><th>Internal documents/sections detected</th></tr>{% for d in state.documents %}<tr><td>{{d.name}}</td><td>{{d.chars}}</td><td>{% for c in d.classifications %}<div><b>{% if c.page %}Page {{c.page}}: {% endif %}{{c.type}}</b> ({{c.confidence}}%)</div>{% endfor %}</td></tr>{% endfor %}</table></div>
'''
    return page("Case Preview", body, state=state, rows=rows)


@app.post("/case/<case_id>/finalize")
def finalize_case(case_id: str):
    cdir = CASES_DIR / case_id
    state_path = cdir / "state.json"
    if not state_path.exists():
        return "Case not found", 404
    state = json.loads(state_path.read_text(encoding="utf-8"))
    final_values = {k: compact_ws(v) for k, v in state["proposed"].items()}
    operator_decisions = {}
    for question in state.get("operator_questions", []):
        answer = compact_ws(request.form.get("decision__" + question["id"], ""))
        if question.get("required") and not answer:
            flash("Select all required operator decisions before generation.")
            return redirect(url_for("preview_case", case_id=case_id))
        operator_decisions[question["id"]] = answer
        if answer.startswith("Stop and"):
            flash("Generation stopped. Select or upload the correct model proforma.")
            return redirect(url_for("new_case"))
    if operator_decisions.get("product_model_conflict", "").startswith("Keep the selected model product"):
        final_values["facility_type"] = state["template_meta"].get("product", final_values.get("facility_type", "N/F"))
    for key in list(final_values):
        posted = request.form.get("field__" + key)
        if posted is not None:
            final_values[key] = compact_ws(posted) or "N/F"
    template = Path(state["template"])
    doc_type = state["template_meta"]["doc_type"]
    product = state["template_meta"]["product"]
    borrower = final_values.get("borrower_name", state.get("case_name", "New_Client"))
    filename = f"{slug(product)}_{slug(doc_type)}_{slug(borrower)}_{case_id[:6]}{template.suffix.lower()}"
    output = OUTPUTS_DIR / filename
    result = generate_document(template, output, state["mapping"], final_values)
    audit = {
        "case_id": case_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "template": state["template_meta"],
        "final_values": final_values,
        "generation": result,
        "evidence": state["evidence"],
        "documents": state["documents"],
        "anomalies": state.get("anomalies", []),
        "operator_decisions": operator_decisions,
    }
    audit_path = output.with_name(output.stem + "_AUDIT.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if not result["safe"]:
        output.unlink(missing_ok=True)
        body = r'''<div class="card"><h2 class="bad">Generation Blocked</h2><p>The engine detected old mapped model values still remaining in targeted locations. The master was not returned as output.</p><h3>Retained values</h3><pre>{{result.retained|tojson(indent=2)}}</pre><h3>Critical old identities</h3><pre>{{result.critical_retained|tojson(indent=2)}}</pre><a class="btn" href="/case/{{case_id}}/preview">Return to Preview</a></div>'''
        return page("Generation Blocked", body, result=result, case_id=case_id), 422
    state["final_values"] = final_values
    state["output"] = str(output)
    state["audit"] = str(audit_path)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    body = r'''
<div class="card"><h2 class="ok">New Document Generated</h2><p>The master remains unchanged. {{result.success_count}} mapped variable placements were replaced.</p><a class="btn green" href="/output/{{output.name}}">Download {{output.name}}</a> <a class="btn secondary" href="/output/{{audit.name}}">Download Audit Trail</a></div>
<div class="card"><h3>Safety Result</h3><p>Retained targeted model values: <b>{{result.retained|length}}</b></p><p>Retained critical old identities: <b>{{result.critical_retained|length}}</b></p><p>Replacement failures: <b>{{result.failure_count}}</b></p></div>
'''
    return page("Generated", body, result=result, output=output, audit=audit_path)



@app.get("/case/<case_id>/anomaly-letter")
def anomaly_letter_download(case_id: str):
    state_path = CASES_DIR / case_id / "state.json"
    if not state_path.exists():
        return "Case not found", 404
    state = json.loads(state_path.read_text(encoding="utf-8"))
    values = state.get("values", {})
    borrower = values.get("borrower_name", state.get("case_name", "Borrower"))
    output = OUTPUTS_DIR / f"Anomaly_Shortcoming_Letter_{slug(borrower)}_{case_id[:6]}.docx"
    logo = APP_DIR / "assets" / "pubali_bank_logo.jpg"
    generate_anomaly_letter(
        output,
        values=values,
        anomalies=state.get("anomalies", []),
        doc_status=state.get("doc_status", {}),
        logo_path=logo,
        assessment_date=datetime.now(),
    )
    return send_file(output, as_attachment=True, download_name=output.name)

@app.get("/outputs")
def outputs_page():
    files = sorted((p for p in OUTPUTS_DIR.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    body = r'''<div class="card"><h2>Generated Documents and Audit Trails</h2><table><tr><th>File</th><th>Size</th><th>Modified</th><th></th></tr>{% for f in files %}<tr><td>{{f.name}}</td><td>{{(f.stat().st_size/1024)|round(1)}} KB</td><td>{{f.stat().st_mtime}}</td><td><a class="btn" href="/output/{{f.name}}">Download</a></td></tr>{% endfor %}</table></div>'''
    return page("Generated Documents", body, files=files)


@app.get("/output/<path:name>")
def output_download(name: str):
    safe = Path(name).name
    path = OUTPUTS_DIR / safe
    if not path.exists():
        return "File not found", 404
    return send_file(path, as_attachment=True, download_name=safe)


@app.get("/health")
def health():
    return {"status": "ok", "templates": len(REGISTRY.index), "pid": os.getpid()}


def open_browser_later():
    time.sleep(1.8)
    try:
        webbrowser.open("http://127.0.0.1:5050")
    except Exception:
        pass


if __name__ == "__main__":
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    threading.Thread(target=open_browser_later, daemon=True).start()
    print("PCIA Final Core running at http://127.0.0.1:5050")
    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=5050, threads=6)
    finally:
        PID_FILE.unlink(missing_ok=True)

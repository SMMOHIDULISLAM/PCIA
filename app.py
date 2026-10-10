import os, re, sqlite3, html, zipfile, shutil
from datetime import datetime
from pathlib import Path
from flask import Flask, request, redirect, url_for, send_file, flash, get_flashed_messages, abort
from werkzeug.utils import secure_filename
from docx import Document

APP_NAME = "Pubali Credit Intelligent Analyst (PCIA)"
VERSION = "v0.5"
BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
GENERATED = DATA / "generated"
TEMPLATE_STORE = DATA / "master_templates"
DB = DATA / "pcia.db"
for p in [DATA, UPLOADS, GENERATED, TEMPLATE_STORE]:
    p.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = "pcia-local-secret"

TASKS = [
    "Writing Letter", "Circulars", "Information Input to System", "Forwarding Letter",
    "Analysis of Credit Proposal", "Notesheet Preparation", "Sanction Letter Preparation",
    "Shariah Opinion", "Financial Statement Analysis", "Bank Statement Analysis", "CIB Analysis",
    "Collateral Analysis", "Valuation Analysis", "Legal Document Analysis", "Document Verification",
    "Complete Credit Processing", "Other"
]

INSTRUCTION_TYPES = [
    "Prepare new document from uploaded files", "Follow uploaded model proforma exactly",
    "Prepare forwarding from reference/back files", "Analyze customer proposal ZIP",
    "Check circular/policy compliance", "Prepare missing document report",
    "Prepare editable analyst observation report", "Extract information for notesheet",
    "Extract information for sanction letter", "Other instruction"
]

UPLOAD_BOXES = [
    ("customer_zip", "A. Customer Proposal ZIP / Customer Documents"),
    ("model_proforma", "B. Model Proforma / Official Format"),
    ("circular_policy", "C. Circular / Policy / Guideline"),
    ("reference_back", "D. Reference / Back Files / Previous Letters"),
    ("other_bank", "E. Other Bank Documents")
]

REPORT_TYPES = [
    "Analyst Observation Sheet", "Missing Document Report", "Credit Analysis Report", "ICRR Risk Report"
]

FORMAT_TYPES = ["Editable DOCX", "Editable ODT", "HTML Preview"]

FACILITY_CHECKLISTS = {
    "Bai-Muajjal TR": ["Application", "Credit Proposal", "Trade License", "TIN", "NID", "CIB", "Bank Statement", "Financial Statement", "Stock Report", "Valuation Report", "Legal Opinion", "Mutation/Khatian", "EC/NEC", "Insurance", "Shariah Opinion"],
    "Lease Finance": ["Application", "Credit Proposal", "Quotation", "Money Receipt", "NID", "TIN", "CIB", "Bank Statement", "Guarantor Information", "Insurance", "Post Dated Cheques", "Lease Agreement"],
    "Pubali Abashon": ["Application", "Credit Proposal", "Estimate", "Approved Plan", "NID", "TIN", "CIB", "Income Proof", "Valuation Report", "Legal Opinion", "Title Deed", "Mutation/Khatian", "EC/NEC", "Insurance"],
    "HPSM Pubali Star": ["Application", "Credit Proposal", "Salary/Income Proof", "NID", "TIN", "CIB", "Guarantor Information", "Post Dated Cheques", "Debit Authority"],
    "SME Subarna Rin": ["Application", "Credit Proposal", "Trade License", "TIN", "NID", "CIB", "Bank Statement", "Stock Statement", "Guarantor Information", "Post Dated Cheques"],
    "Green Prantik": ["Application", "Farmer Identification", "NID", "CIB", "Guarantor Information", "10 Taka Account", "Undertaking"],
    "General Credit Proposal": ["Application", "Credit Proposal", "NID", "TIN", "CIB", "Bank Statement", "Financial Statement", "Valuation Report", "Legal Opinion", "Guarantor Information"]
}

KEYWORDS = {
    "Application": ["application", "borrower application", "আবেদন"],
    "Credit Proposal": ["proposal", "credit appraisal", "note sheet", "notesheet"],
    "Trade License": ["trade license", "license"],
    "TIN": ["tin", "tax identification"],
    "NID": ["nid", "national id", "national identity"],
    "CIB": ["cib", "credit information bureau"],
    "Bank Statement": ["bank statement", "statement"],
    "Financial Statement": ["balance sheet", "income statement", "profit", "loss", "trading account"],
    "Stock Report": ["stock", "inventory"],
    "Valuation Report": ["valuation", "valuer", "survey"],
    "Legal Opinion": ["legal opinion", "lawyer", "panel lawyer"],
    "Mutation/Khatian": ["mutation", "khatian", "parcha"],
    "EC/NEC": ["ec", "nec", "encumbrance"],
    "Insurance": ["insurance"],
    "Shariah Opinion": ["shariah", "shari’ah", "sharia"],
    "Quotation": ["quotation", "supplier"],
    "Money Receipt": ["money receipt", "receipt"],
    "Guarantor Information": ["guarantor", "guarantee"],
    "Post Dated Cheques": ["cheque", "micr", "post dated"],
    "Lease Agreement": ["lease agreement"],
    "Estimate": ["estimate", "cost estimation"],
    "Approved Plan": ["approved plan", "building plan"],
    "Income Proof": ["salary", "income", "rent"],
    "Farmer Identification": ["farmer", "farming", "agri"],
    "10 Taka Account": ["10 taka", "১০ টাকার"],
    "Undertaking": ["undertaking", "অঙ্গীকার"],
    "Debit Authority": ["debit authority", "authorization"],
    "Title Deed": ["title deed", "deed", "sro"]
}

BOX_LABEL = dict(UPLOAD_BOXES)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db(); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS cases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, borrower TEXT, facility TEXT NOT NULL,
        task TEXT NOT NULL, instruction_type TEXT, instruction TEXT, created_at TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS files(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER, original_name TEXT, saved_name TEXT, box TEXT, description TEXT, uploaded_at TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER, report_type TEXT, output_format TEXT, file_path TEXT, created_at TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS master_templates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        facility TEXT NOT NULL,
        template_type TEXT NOT NULL,
        original_name TEXT NOT NULL,
        saved_name TEXT NOT NULL,
        version TEXT DEFAULT '1.0',
        status TEXT DEFAULT 'Active',
        uploaded_at TEXT NOT NULL,
        UNIQUE(facility, template_type)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS template_mappings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL,
        variable_key TEXT NOT NULL,
        old_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(template_id) REFERENCES master_templates(id)
    )""")
    
    # lightweight migration for v0.1 databases
    for table, col, typ in [
        ("cases", "instruction_type", "TEXT"),
        ("files", "description", "TEXT"),
        ("reports", "report_type", "TEXT"),
        ("reports", "output_format", "TEXT"),
        ("reports", "file_path", "TEXT")
    ]:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    con.commit(); con.close()

init_db()

CSS = """
<style>
:root{--g:#006b35;--dg:#003b23;--lg:#edf8f1;--bg:#f5faf7;--red:#b00020;--amber:#a66a00;--line:#d7e5dc}
*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:#111827}.top{background:#fff;border-bottom:1px solid #d8e6dd;padding:16px 28px;display:flex;align-items:center;gap:18px}.bank{width:70px;height:54px;border:3px solid var(--g);display:grid;place-items:center;color:var(--g);font-weight:900;border-radius:8px}.top h1{margin:0;color:var(--g);font-size:25px}.top p{margin:5px 0 0;font-weight:700;color:#195c38}.layout{display:flex}.side{width:265px;background:var(--dg);min-height:calc(100vh - 87px);padding:20px 13px;color:#fff}.side a{display:block;color:#fff;text-decoration:none;padding:12px 14px;border-radius:8px;margin:5px 0;font-weight:700}.side a:hover,.side .active{background:var(--g)}.main{flex:1;padding:24px}.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:20px;box-shadow:0 6px 20px rgba(0,0,0,.04)}h1,h2,h3{color:var(--g)}h2{margin-top:0}label{display:block;margin-top:12px;font-weight:700}.row{display:grid;grid-template-columns:1fr 1fr;gap:16px}.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}input,select,textarea{width:100%;padding:12px;border:1px solid #cbd5d1;border-radius:8px;margin-top:6px;font-size:14px}textarea{min-height:100px}.btn{background:var(--g);color:#fff;border:0;border-radius:8px;padding:11px 16px;margin:4px 4px 4px 0;cursor:pointer;font-weight:700;text-decoration:none;display:inline-block}.btn2{background:#fff;color:var(--g);border:1px solid var(--g)}.btnred{background:#fff;color:#b00020;border:1px solid #b00020}.small{padding:7px 10px;font-size:13px}table{border-collapse:collapse;width:100%;background:#fff}th,td{border:1px solid #dae4de;padding:10px;text-align:left;vertical-align:top}th{background:var(--lg);color:var(--dg)}.pill{padding:4px 8px;border-radius:999px;font-weight:700;font-size:12px;white-space:nowrap}.ok{background:#e7f6ec;color:#0b6b32}.bad{background:#fde8e8;color:var(--red)}.warn{background:#fff3d6;color:var(--amber)}.muted{color:#6b7280}.flash{background:#fff7e6;border-left:5px solid #c87900;padding:10px;margin-bottom:15px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.kpi{background:var(--lg);padding:16px;border-radius:10px;border:1px solid #cfe3d6}.footer{padding:14px 24px;background:var(--dg);color:#fff}.section-title{border-left:5px solid var(--g);padding-left:10px}.note{background:#f8fffb;border:1px dashed #b9d5c4;padding:12px;border-radius:10px}.actions{white-space:nowrap}.two-col{display:grid;grid-template-columns:1.2fr .8fr;gap:18px}
</style>
"""


def nav_item(path, text, active):
    cls = "active" if active == text else ""
    return f'<a class="{cls}" href="{path}">{html.escape(text)}</a>'


def page(title, body, active=""):
    menu = [
        ("/", "Dashboard"), ("/pandora", "Pandora Box"), ("/document-intelligence", "AI Document Intelligence"),
        ("/credit-analysis", "Credit Analysis"), ("/icrr", "ICRR Risk Engine"), ("/generator", "Document Generator"),
        ("/reports", "Reports"), ("/templates", "Template Library"), ("/admin", "Administration"), ("/settings", "Settings")
    ]
    flashes = ''.join('<div class="flash">'+html.escape(m)+'</div>' for m in get_flashed_messages())
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>{CSS}</head><body>
    <div class="top"><div class="bank">PBL</div><div><h1>{APP_NAME}</h1><p>PUBALI BANK PLC, SYLHET WEST REGION | {VERSION}</p></div></div>
    <div class="layout"><nav class="side">{''.join(nav_item(p,t,active) for p,t in menu)}</nav><main class="main">{flashes}{body}</main></div>
    <div class="footer">PCIA {VERSION} | Local Offline-Ready Prototype | Editable DOCX report enabled</div></body></html>"""


def options(items, selected=None):
    return ''.join(f'<option {"selected" if x==selected else ""}>{html.escape(x)}</option>' for x in items)


def box_options(selected=None):
    return ''.join(f'<option value="{k}" {"selected" if k==selected else ""}>{html.escape(v)}</option>' for k,v in UPLOAD_BOXES)


def read_text(path: Path):
    name = path.name.lower()
    try:
        if name.endswith('.txt'):
            return path.read_text(errors='ignore')[:20000]
        if name.endswith('.docx'):
            d = Document(path)
            return '\n'.join(p.text for p in d.paragraphs)[:20000]
        if name.endswith('.pdf'):
            import fitz
            doc = fitz.open(path)
            return '\n'.join(page.get_text() for page in doc[:5])[:20000]
        if name.endswith('.zip'):
            with zipfile.ZipFile(path) as z:
                return ' '.join(z.namelist())[:20000]
    except Exception:
        return ""
    return ""


def classify_files(files):
    found = set(); evidence = {}
    for f in files:
        path = UPLOADS / str(f['case_id']) / f['saved_name']
        text = (f['original_name'] + ' ' + (f['description'] or '') + ' ' + read_text(path)).lower()
        for doc_type, kws in KEYWORDS.items():
            if any(k.lower() in text for k in kws):
                found.add(doc_type); evidence.setdefault(doc_type, []).append(f['original_name'])
    return found, evidence


def analyze_case(case_id):
    con = db(); case = con.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
    files = con.execute('SELECT * FROM files WHERE case_id=? ORDER BY id',(case_id,)).fetchall(); con.close()
    checklist = FACILITY_CHECKLISTS.get(case['facility'], FACILITY_CHECKLISTS['General Credit Proposal'])
    found, evidence = classify_files(files)
    rows=[]; missing=[]
    for item in checklist:
        status = 'Found' if item in found else 'Missing'
        if status=='Missing': missing.append(item)
        rows.append({'item':item,'status':status,'evidence':', '.join(evidence.get(item, []))})
    risk_doc = max(0, 100 - len(missing)*7)
    risk_fin = 78 if any(x in found for x in ['Financial Statement','Bank Statement']) else 45
    risk_credit = 78 if 'CIB' in found else 55
    risk_legal = 82 if any(x in found for x in ['Legal Opinion','Valuation Report','Mutation/Khatian','EC/NEC','Title Deed']) else 50
    risk_compliance = 80 if not missing else max(40, 82-len(missing)*5)
    scores = [('Credit Risk',risk_credit),('Documentation Risk',risk_doc),('Financial Risk',risk_fin),('Legal Risk',risk_legal),('Compliance Risk',risk_compliance)]
    avg = round(sum(s for _,s in scores)/len(scores),2)
    grade = 'Low' if avg>=80 else 'Moderate' if avg>=60 else 'High'
    return case, files, rows, missing, scores, avg, grade


def file_path_for(file_row):
    return UPLOADS / str(file_row['case_id']) / file_row['saved_name']


def build_report_content(case_id, report_type):
    case, files, rows, missing, scores, avg, grade = analyze_case(case_id)
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    report_type = report_type or "Analyst Observation Sheet"
    title = report_type
    html_body = f"""<div class='main'><div class='card'><h1>{html.escape(title)}</h1>
    <h2>{html.escape(case['title'])}</h2><p><b>Borrower:</b> {html.escape(case['borrower'] or '')}</p>
    <p><b>Facility:</b> {html.escape(case['facility'])}</p><p><b>Task:</b> {html.escape(case['task'])}</p>
    <p><b>Generated:</b> {now}</p><p><b>Overall ICRR:</b> {grade} Risk | Score {avg}</p></div>"""
    html_body += "<div class='card'><h2>Uploaded Document Groups</h2><table><tr><th>Group</th><th>Files</th></tr>"
    grouped = {}
    for f in files:
        grouped.setdefault(BOX_LABEL.get(f['box'], f['box']), []).append(f['original_name'])
    for g, names in grouped.items():
        html_body += f"<tr><td>{html.escape(g)}</td><td>{'<br>'.join(html.escape(n) for n in names)}</td></tr>"
    html_body += "</table></div>"
    if report_type in ["Analyst Observation Sheet", "Missing Document Report", "Credit Analysis Report", "ICRR Risk Report"]:
        html_body += "<div class='card'><h2>Missing Documents</h2>"
        if missing: html_body += '<ol>' + ''.join(f'<li>{html.escape(m)}</li>' for m in missing) + '</ol>'
        else: html_body += '<p>No checklist document missing based on uploaded files.</p>'
        html_body += "</div><div class='card'><h2>Checklist Verification</h2><table><tr><th>Item</th><th>Status</th><th>Evidence</th></tr>"
        for r in rows:
            html_body += f"<tr><td>{html.escape(r['item'])}</td><td>{r['status']}</td><td>{html.escape(r['evidence'] or '—')}</td></tr>"
        html_body += "</table></div>"
    if report_type in ["Analyst Observation Sheet", "Credit Analysis Report", "ICRR Risk Report"]:
        html_body += "<div class='card'><h2>ICRR Risk</h2><table><tr><th>Category</th><th>Score</th><th>Observation</th></tr>"
        for n,s in scores:
            obs = 'Acceptable' if s>=80 else 'Needs Review' if s>=60 else 'High Attention Required'
            html_body += f"<tr><td>{n}</td><td>{s}</td><td>{obs}</td></tr>"
        html_body += "</table></div>"
    if False:  # disabled: no intermediate data-sheet documents
        html_body += "<div class='card'><h2>Proforma/Document Data Sheet</h2><table><tr><th>Required Field</th><th>Value</th><th>Status</th><th>Analyst Action</th></tr>"
        fields = ["Borrower Name", "Facility Type", "Loan Amount", "Purpose", "Tenure", "Rate", "Security", "Guarantor", "Branch", "Reference Letter", "Special Conditions"]
        for field in fields:
            value = case['borrower'] if field=='Borrower Name' else case['facility'] if field=='Facility Type' else 'To be extracted / entered'
            status = 'Available' if field in ['Borrower Name','Facility Type'] else 'Review Required'
            action = 'Verify before generation' if status=='Available' else 'Analyst input required'
            html_body += f"<tr><td>{field}</td><td>{html.escape(value or '')}</td><td>{status}</td><td>{action}</td></tr>"
        html_body += "</table></div>"
    html_body += "<div class='card'><h2>Suggested Analyst Action</h2><ol>"
    if missing:
        for m in missing: html_body += f"<li>Obtain / verify {html.escape(m)} before final processing.</li>"
    else:
        html_body += "<li>Proceed to detailed financial, legal and final analyst review.</li>"
    html_body += "</ol></div></div>"
    return title, now, case, files, rows, missing, scores, avg, grade, html_body


def generate_docx(case_id, report_type, output_path):
    title, now, case, files, rows, missing, scores, avg, grade, _ = build_report_content(case_id, report_type)
    doc = Document(); doc.add_heading(title, 0)
    for line in [f"Case: {case['title']}", f"Borrower: {case['borrower'] or ''}", f"Facility: {case['facility']}", f"Task: {case['task']}", f"Generated: {now}", f"Overall ICRR: {grade} Risk | Score {avg}"]:
        doc.add_paragraph(line)
    doc.add_heading('Uploaded Document Groups', 1)
    grouped = {}
    for f in files: grouped.setdefault(BOX_LABEL.get(f['box'], f['box']), []).append(f['original_name'])
    for group, names in grouped.items():
        doc.add_paragraph(group, style='List Bullet')
        for n in names: doc.add_paragraph(n, style='List Bullet 2')
    if report_type in ["Analyst Observation Sheet", "Missing Document Report", "Credit Analysis Report", "ICRR Risk Report"]:
        doc.add_heading('Missing Documents', 1)
        if missing:
            for m in missing: doc.add_paragraph(m, style='List Bullet')
        else: doc.add_paragraph('No checklist document missing based on uploaded files.')
        doc.add_heading('Checklist Verification', 1)
        table=doc.add_table(rows=1, cols=3); table.style='Table Grid'; hdr=table.rows[0].cells; hdr[0].text='Item'; hdr[1].text='Status'; hdr[2].text='Evidence'
        for r in rows:
            cells=table.add_row().cells; cells[0].text=r['item']; cells[1].text=r['status']; cells[2].text=r['evidence'] or '—'
    if report_type in ["Analyst Observation Sheet", "Credit Analysis Report", "ICRR Risk Report"]:
        doc.add_heading('ICRR Risk Scores', 1)
        t=doc.add_table(rows=1, cols=3); t.style='Table Grid'; h=t.rows[0].cells; h[0].text='Category'; h[1].text='Score'; h[2].text='Observation'
        for n,s in scores:
            c=t.add_row().cells; c[0].text=n; c[1].text=str(s); c[2].text='Acceptable' if s>=80 else 'Needs Review' if s>=60 else 'High Attention Required'
    if False:  # disabled: no intermediate data-sheet documents
        doc.add_heading('Proforma/Document Data Sheet', 1)
        t=doc.add_table(rows=1, cols=4); t.style='Table Grid'; h=t.rows[0].cells; h[0].text='Required Field'; h[1].text='Value'; h[2].text='Status'; h[3].text='Analyst Action'
        fields = ["Borrower Name", "Facility Type", "Loan Amount", "Purpose", "Tenure", "Rate", "Security", "Guarantor", "Branch", "Reference Letter", "Special Conditions"]
        for field in fields:
            c=t.add_row().cells; c[0].text=field; c[1].text=case['borrower'] if field=='Borrower Name' else case['facility'] if field=='Facility Type' else 'To be extracted / entered'; c[2].text='Available' if field in ['Borrower Name','Facility Type'] else 'Review Required'; c[3].text='Verify before generation' if c[2].text=='Available' else 'Analyst input required'
    doc.add_heading('Suggested Analyst Action', 1)
    if missing:
        for m in missing: doc.add_paragraph(f'Obtain / verify {m} before final processing.', style='List Number')
    else: doc.add_paragraph('Proceed to detailed financial, legal and final analyst review.', style='List Number')
    doc.save(output_path)


def generate_odt_minimal(case_id, report_type, output_path):
    # Simple editable ODT text package without external dependency. Formatting is basic but editable.
    title, now, case, files, rows, missing, scores, avg, grade, _ = build_report_content(case_id, report_type)
    def p(txt): return f'<text:p>{html.escape(str(txt))}</text:p>'
    content = [p(title), p(f"Case: {case['title']}"), p(f"Borrower: {case['borrower'] or ''}"), p(f"Facility: {case['facility']}"), p(f"Generated: {now}"), p(f"Overall ICRR: {grade} Risk | Score {avg}"), p("Missing Documents:")]
    if missing:
        content += [p(f"- {m}") for m in missing]
    else:
        content.append(p("No checklist document missing based on uploaded files."))
    content.append(p("ICRR Risk Scores:"))
    for n,s in scores:
        content.append(p(f"{n}: {s}"))
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:text>{''.join(content)}</office:text></office:body></office:document-content>'''
    styles = '''<?xml version="1.0" encoding="UTF-8"?><office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" office:version="1.2"><office:styles/></office:document-styles>'''
    with zipfile.ZipFile(output_path, 'w') as z:
        z.writestr('mimetype', 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
        z.writestr('content.xml', xml)
        z.writestr('styles.xml', styles)
        z.writestr('META-INF/manifest.xml', '''<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/></manifest:manifest>''')


def parse_replacements(raw):
    reps = []
    for line in (raw or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=>' in line:
            old, new = line.split('=>', 1)
        elif '=' in line:
            old, new = line.split('=', 1)
        else:
            continue
        old = old.strip()
        new = new.strip()
        if old:
            reps.append((old, new))
    return reps


def clone_docx_by_xml(template_path: Path, output_path: Path, replacements):
    """Clone DOCX and replace text in XML only. Formatting, margins, tables, headers and footers remain unchanged."""
    with zipfile.ZipFile(template_path, 'r') as zin, zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith('word/') and item.filename.endswith('.xml'):
                text = data.decode('utf-8', errors='ignore')
                for old, new in replacements:
                    text = text.replace(html.escape(old), html.escape(new))
                    text = text.replace(old, new)
                data = text.encode('utf-8')
            zout.writestr(item, data)


def clone_odt_by_xml(template_path: Path, output_path: Path, replacements):
    """Clone ODT and replace text in content/styles XML only. Original ODT package structure is preserved."""
    with zipfile.ZipFile(template_path, 'r') as zin, zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in ('content.xml', 'styles.xml') or item.filename.endswith('.xml'):
                text = data.decode('utf-8', errors='ignore')
                for old, new in replacements:
                    text = text.replace(html.escape(old), html.escape(new))
                    text = text.replace(old, new)
                data = text.encode('utf-8')
            if item.filename == 'mimetype':
                zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
            else:
                zout.writestr(item, data)


def clone_template_preserve_format(template_row, document_kind, replacements):
    src = file_path_for(template_row)
    ext = src.suffix.lower()
    safe_kind = re.sub(r'[^A-Za-z0-9_]+', '_', document_kind).strip('_') or 'Cloned_Document'
    folder = GENERATED / str(template_row['case_id'])
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{safe_kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    if ext == '.docx':
        clone_docx_by_xml(src, out, replacements)
    elif ext == '.odt':
        clone_odt_by_xml(src, out, replacements)
    else:
        raise ValueError('Only DOCX and ODT master templates are supported for exact clone generation in this build.')
    return out




def extract_template_text(template_path: Path):
    name = template_path.name.lower()
    try:
        if name.endswith('.docx'):
            d = Document(template_path)
            parts = []
            for p in d.paragraphs:
                if p.text.strip(): parts.append(p.text.strip())
            for tbl in d.tables:
                for row in tbl.rows:
                    for cell in row.cells:
                        txt = cell.text.strip()
                        if txt: parts.append(txt)
            return '\n'.join(parts)
        if name.endswith('.odt'):
            with zipfile.ZipFile(template_path,'r') as z:
                raw=z.read('content.xml').decode('utf-8',errors='ignore')
                raw=re.sub(r'<[^>]+>',' ',raw)
                raw=html.unescape(raw)
                raw=re.sub(r'\s+',' ',raw)
                return raw
    except Exception as e:
        return f"ERROR READING TEMPLATE: {e}"
    return ''


def suggest_variable_candidates(text):
    """Return likely variable text candidates. Analyst still approves mapping."""
    pats = [
        r'\b(?:Mr\.|Mst\.|Md\.|M/S\.|Mrs\.)\s*[A-Za-z][A-Za-z\.\s]{2,80}',
        r'Tk\.?\s*[0-9,\.]+\s*(?:Lac|Crore|/-)?',
        r'\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b',
        r'\b\d{1,2}\s*\(?[A-Za-z]+\)?\s*(?:months?|years?|Years?|Months?)\b',
        r'@\s*\d{1,2}(?:\.\d+)?\s*%[^\n,;]*',
        r'\b\d{10,17}\b',
        r'\b[A-Za-z ]+ Branch\b',
    ]
    found=[]
    for pat in pats:
        for m in re.findall(pat, text, flags=re.I):
            val = re.sub(r'\s+',' ',m).strip()
            if 3 <= len(val) <= 160 and val not in found:
                found.append(val)
    return found[:150]


def mapping_rows(template_id):
    con=db(); rows=con.execute('SELECT * FROM template_mappings WHERE template_id=? ORDER BY id',(template_id,)).fetchall(); con.close(); return rows


def values_from_textarea(txt):
    vals={}
    for line in (txt or '').splitlines():
        if '=' in line:
            k,v=line.split('=',1)
            vals[k.strip()]=v.strip()
        elif '=>' in line:
            k,v=line.split('=>',1)
            vals[k.strip()]=v.strip()
    return vals


def generate_from_mapping(template_row, values, prefix='Generated'):
    maps=mapping_rows(template_row['id'])
    repl={}
    missing=[]
    for m in maps:
        key=m['variable_key']
        if key in values and values[key] != '':
            repl[m['old_text']] = values[key]
        else:
            missing.append(key)
    if missing:
        raise ValueError('Missing values for: ' + ', '.join(sorted(set(missing))))
    src=template_file_path(template_row)
    ext=src.suffix.lower()
    folder=GENERATED/'mapped_documents'; folder.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r'[^A-Za-z0-9_]+','_',prefix).strip('_') or 'Generated'
    out=folder/f"{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
    if ext=='.docx': clone_docx_by_xml(src,out,repl)
    elif ext=='.odt': clone_odt_by_xml(src,out,repl)
    else: raise ValueError('Only DOCX/ODT supported.')
    return out

@app.route('/')
def dashboard():
    con=db(); total=con.execute('SELECT COUNT(*) c FROM cases').fetchone()['c']; files=con.execute('SELECT COUNT(*) c FROM files').fetchone()['c']; reps=con.execute('SELECT COUNT(*) c FROM reports').fetchone()['c']; recent=con.execute('SELECT * FROM cases ORDER BY id DESC LIMIT 5').fetchall(); con.close()
    body=f"""<div class='card'><h2>Dashboard</h2><div class='grid3'><div class='kpi'><b>Total Cases</b><h2>{total}</h2></div><div class='kpi'><b>Uploaded Files</b><h2>{files}</h2></div><div class='kpi'><b>Generated Reports</b><h2>{reps}</h2></div></div><a class='btn' href='/new'>Create New Case</a> <a class='btn btn2' href='/pandora'>Open Pandora Box</a></div>
    <div class='card'><h2>Recent Cases</h2><table><tr><th>ID</th><th>Title</th><th>Borrower</th><th>Facility</th><th>Action</th></tr>"""
    for r in recent:
        body += f"<tr><td>{r['id']}</td><td>{html.escape(r['title'])}</td><td>{html.escape(r['borrower'] or '')}</td><td>{html.escape(r['facility'])}</td><td><a href='/case/{r['id']}'>Open</a></td></tr>"
    body += "</table></div>"
    return page('PCIA Dashboard', body, 'Dashboard')

@app.route('/new', methods=['GET','POST'])
def new_case():
    if request.method=='POST':
        title=request.form.get('title','').strip() or 'Untitled Case'
        borrower=request.form.get('borrower','').strip()
        facility=request.form.get('facility','General Credit Proposal')
        task=request.form.get('task','Analysis of Credit Proposal')
        instruction_type=request.form.get('instruction_type','')
        instruction=request.form.get('instruction','')
        con=db(); cur=con.cursor(); cur.execute('INSERT INTO cases(title,borrower,facility,task,instruction_type,instruction,created_at) VALUES(?,?,?,?,?,?,?)',(title,borrower,facility,task,instruction_type,instruction,datetime.now().isoformat(timespec='seconds'))); cid=cur.lastrowid; con.commit(); con.close()
        flash('Case created. Pandora Box is ready for separate uploads.')
        return redirect(url_for('case_view', case_id=cid))
    body=f"""<div class='card'><h2>Create New Case</h2><form method='post'>
    <div class='row'><div><label>Case Title</label><input name='title' placeholder='Example: Shiyam Enterprise Bai-Muajjal TR'></div><div><label>Borrower / Customer Name</label><input name='borrower'></div></div>
    <div class='row'><div><label>Facility Type</label><select name='facility'>{options(FACILITY_CHECKLISTS.keys())}</select></div><div><label>Task Description</label><select name='task'>{options(TASKS, 'Analysis of Credit Proposal')}</select></div></div>
    <label>Instruction Type</label><select name='instruction_type'>{options(INSTRUCTION_TYPES)}</select>
    <label>AI Instruction Panel / Analyst Instruction</label><textarea name='instruction' placeholder='Write exact instruction for PCIA here. Example: prepare missing document report and editable analyst observation sheet.'></textarea>
    <button class='btn'>Create Case</button></form></div>"""
    return page('New Case', body, 'Pandora Box')

@app.route('/pandora')
def pandora():
    con=db(); rows=con.execute('SELECT * FROM cases ORDER BY id DESC LIMIT 20').fetchall(); con.close()
    body="""<div class='card'><h2>Pandora Box</h2><p class='note'>Create a case first, then upload documents in separate boxes: Customer ZIP, Model Proforma, Circular/Policy, Reference/Back Files, and Other Bank Documents.</p><a class='btn' href='/new'>Create New Pandora Case</a></div><div class='card'><h2>Open Existing Case</h2><table><tr><th>ID</th><th>Title</th><th>Task</th><th>Action</th></tr>"""
    for r in rows:
        body += f"<tr><td>{r['id']}</td><td>{html.escape(r['title'])}</td><td>{html.escape(r['task'])}</td><td><a href='/case/{r['id']}'>Open Pandora Box</a></td></tr>"
    body += "</table></div>"
    return page('Pandora Box', body, 'Pandora Box')

@app.route('/cases')
def cases():
    con=db(); rows=con.execute('SELECT * FROM cases ORDER BY id DESC').fetchall(); con.close()
    body="<div class='card'><h2>Cases</h2><table><tr><th>ID</th><th>Title</th><th>Borrower</th><th>Facility</th><th>Created</th><th>Action</th></tr>"
    for r in rows:
        body+=f"<tr><td>{r['id']}</td><td>{html.escape(r['title'])}</td><td>{html.escape(r['borrower'] or '')}</td><td>{html.escape(r['facility'])}</td><td>{r['created_at']}</td><td><a href='/case/{r['id']}'>Open</a></td></tr>"
    body += "</table></div>"
    return page('Cases', body, 'Pandora Box')

@app.route('/case/<int:case_id>', methods=['GET','POST'])
def case_view(case_id):
    if request.method=='POST':
        box=request.form.get('box','customer_zip')
        description=request.form.get('description','').strip()
        folder=UPLOADS/str(case_id); folder.mkdir(parents=True, exist_ok=True)
        uploaded=request.files.getlist('files')
        con=db(); count=0
        for f in uploaded:
            if not f or not f.filename: continue
            safe=secure_filename(f.filename)
            stamp=datetime.now().strftime('%Y%m%d%H%M%S%f')
            saved=f'{stamp}_{safe}'
            f.save(folder/saved)
            con.execute('INSERT INTO files(case_id,original_name,saved_name,box,description,uploaded_at) VALUES(?,?,?,?,?,?)',(case_id,f.filename,saved,box,description,datetime.now().isoformat(timespec='seconds')))
            count += 1
        con.commit(); con.close(); flash(f'{count} file(s) uploaded to {BOX_LABEL.get(box, box)}.')
        return redirect(url_for('case_view', case_id=case_id))
    con=db(); case=con.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone(); files=con.execute('SELECT * FROM files WHERE case_id=? ORDER BY id DESC',(case_id,)).fetchall(); con.close()
    if not case: return page('Not Found','<div class=card>Case not found.</div>')
    body=f"""<div class='card'><h2>Case #{case['id']}: {html.escape(case['title'])}</h2>
    <p><b>Borrower:</b> {html.escape(case['borrower'] or '')} | <b>Facility:</b> {html.escape(case['facility'])} | <b>Task:</b> {html.escape(case['task'])}</p>
    <p><b>Instruction Type:</b> {html.escape(case['instruction_type'] or '')}</p><p><b>AI/Analyst Instruction:</b> {html.escape(case['instruction'] or '')}</p>
    <a class='btn' href='/clone-template/{case_id}'>Generate Notesheet / Sanction Letter Clone</a> <a class='btn btn2' href='/analyze/{case_id}'>Run Analysis</a> <a class='btn btn2' href='/report-select/{case_id}'>Select Report</a></div>
    <div class='card'><h2 class='section-title'>Pandora Box Upload</h2><form method='post' enctype='multipart/form-data'>
    <label>Upload Category</label><select name='box'>{box_options()}</select>
    <label>Description / Use of These Files</label><input name='description' placeholder='Example: Previous forwarding letters to follow / Customer ZIP / Circular for checking'>
    <label>Select One or Multiple Files</label><input type='file' name='files' multiple>
    <button class='btn'>Upload Files</button></form></div>
    <div class='card'><h2>Uploaded Files with Controls</h2><table><tr><th>#</th><th>File</th><th>Category</th><th>Description</th><th>Uploaded</th><th>Action</th></tr>"""
    for i,f in enumerate(files,1):
        file_id = f["id"]
        original_name = html.escape(f["original_name"] or "")
        box_name = html.escape(BOX_LABEL.get(f["box"], f["box"] or ""))
        description = html.escape(f["description"] or "")
        uploaded_at = html.escape(f["uploaded_at"] or "")
        body += f"""<tr><td>{i}</td><td>{original_name}</td><td>{box_name}</td><td>{description}</td><td>{uploaded_at}</td><td class='actions'><a class='btn btn2 small' href='/file/{file_id}/view'>View</a><a class='btn btn2 small' href='/file/{file_id}/edit'>Edit</a><form method='post' action='/file/{file_id}/delete' style='display:inline' onsubmit='return confirm(&quot;Delete this file?&quot;)'><button class='btn btnred small'>Delete</button></form></td></tr>"""
    body+='</table></div>'
    return page('Case', body, 'Pandora Box')

@app.route('/file/<int:file_id>/view')
def view_file(file_id):
    con=db(); f=con.execute('SELECT * FROM files WHERE id=?',(file_id,)).fetchone(); con.close()
    if not f: abort(404)
    path=file_path_for(f)
    return send_file(path, as_attachment=False, download_name=f['original_name'])

@app.route('/file/<int:file_id>/edit', methods=['GET','POST'])
def edit_file(file_id):
    con=db(); f=con.execute('SELECT * FROM files WHERE id=?',(file_id,)).fetchone(); con.close()
    if not f: abort(404)
    if request.method=='POST':
        new_name=request.form.get('original_name','').strip() or f['original_name']
        box=request.form.get('box',f['box'])
        desc=request.form.get('description','')
        con=db(); con.execute('UPDATE files SET original_name=?, box=?, description=? WHERE id=?',(new_name,box,desc,file_id)); con.commit(); con.close()
        flash('File metadata updated.')
        return redirect(url_for('case_view', case_id=f['case_id']))
    body=f"""<div class='card'><h2>Edit Uploaded File</h2><form method='post'>
    <label>Display File Name</label><input name='original_name' value='{html.escape(f['original_name'])}'>
    <label>Upload Category</label><select name='box'>{box_options(f['box'])}</select>
    <label>Description / Use</label><textarea name='description'>{html.escape(f['description'] or '')}</textarea>
    <button class='btn'>Save</button> <a class='btn btn2' href='/case/{f['case_id']}'>Cancel</a></form></div>"""
    return page('Edit File', body, 'Pandora Box')

@app.route('/file/<int:file_id>/delete', methods=['POST'])
def delete_file(file_id):
    con=db(); f=con.execute('SELECT * FROM files WHERE id=?',(file_id,)).fetchone()
    if not f: con.close(); abort(404)
    case_id=f['case_id']; path=file_path_for(f)
    try:
        if path.exists(): path.unlink()
    except Exception:
        pass
    con.execute('DELETE FROM files WHERE id=?',(file_id,)); con.commit(); con.close()
    flash('File deleted.')
    return redirect(url_for('case_view', case_id=case_id))

@app.route('/analyze/<int:case_id>')
def analyze(case_id):
    case, files, rows, missing, scores, avg, grade = analyze_case(case_id)
    body=f"<div class='card'><h2>Analysis Result: {html.escape(case['title'])}</h2><p><b>Overall ICRR:</b> <span class='pill {'ok' if grade=='Low' else 'warn' if grade=='Moderate' else 'bad'}'>{grade} Risk | Score {avg}</span></p><a class='btn' href='/report-select/{case_id}'>Select Report / Format</a></div>"
    body += "<div class='card'><h2>Checklist Verification</h2><table><tr><th>Required Item</th><th>Status</th><th>Evidence</th></tr>"
    for r in rows:
        cls='ok' if r['status']=='Found' else 'bad'
        body += f"<tr><td>{html.escape(r['item'])}</td><td><span class='pill {cls}'>{r['status']}</span></td><td>{html.escape(r['evidence'] or '—')}</td></tr>"
    body += "</table></div><div class='card'><h2>ICRR Risk Scores</h2><table><tr><th>Risk Category</th><th>Score</th><th>Comment</th></tr>"
    for name,score in scores:
        comment = 'Acceptable' if score>=80 else 'Needs Review' if score>=60 else 'High Attention Required'
        body += f"<tr><td>{name}</td><td>{score}</td><td>{comment}</td></tr>"
    body += "</table></div>"
    return page('Analysis', body, 'Credit Analysis')


@app.route('/clone-template/<int:case_id>', methods=['GET','POST'])
def clone_template(case_id):
    con=db()
    case=con.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
    templates=con.execute("SELECT * FROM files WHERE case_id=? AND box='model_proforma' ORDER BY id DESC",(case_id,)).fetchall()
    con.close()
    if not case: abort(404)
    supported=[]
    for t in templates:
        if (t['original_name'] or '').lower().endswith(('.docx','.odt')):
            supported.append(t)
    if request.method=='POST':
        template_id=int(request.form.get('template_id','0'))
        document_kind=request.form.get('document_kind','Notesheet')
        replacements=parse_replacements(request.form.get('replacements',''))
        if not replacements:
            flash('No replacement data found. Use lines like: old text => new text')
            return redirect(url_for('clone_template', case_id=case_id))
        con=db(); t=con.execute('SELECT * FROM files WHERE id=? AND case_id=?',(template_id,case_id)).fetchone(); con.close()
        if not t: abort(404)
        try:
            path=clone_template_preserve_format(t, document_kind, replacements)
        except Exception as e:
            flash(str(e))
            return redirect(url_for('clone_template', case_id=case_id))
        con=db(); con.execute('INSERT INTO reports(case_id,report_type,output_format,file_path,created_at) VALUES(?,?,?,?,?)',(case_id,document_kind,'Editable '+path.suffix.upper().replace('.',''),str(path),datetime.now().isoformat(timespec='seconds'))); con.commit(); con.close()
        return send_file(path, as_attachment=True)
    opts=''.join(f"<option value='{t['id']}'>{html.escape(t['original_name'])}</option>" for t in supported)
    if not opts:
        opts="<option value='0'>No supported DOCX/ODT model proforma uploaded</option>"
    sample = f"""{case['borrower'] or 'Old Borrower Name'} => New Borrower Name
{case['facility']} => New Facility Type
Tk.40.00 Lac => Tk.00.00 Lac
09.04.2026 => New Date"""
    body=f"""<div class='card'><h2>Clone Notesheet / Sanction Letter</h2>
    <p class='note'>This copies the uploaded model proforma and replaces only variable text. It does not create data sheet reports.</p>
    <form method='post'>
    <label>Select Uploaded Model Proforma</label><select name='template_id'>{opts}</select>
    <label>Document Type</label><select name='document_kind'><option>Notesheet</option><option>Sanction Letter</option><option>Forwarding Letter</option><option>Shariah Opinion</option></select>
    <label>Variable Replacement Data</label><textarea name='replacements' style='min-height:240px' placeholder='old text => new text'>{html.escape(sample)}</textarea>
    <button class='btn'>Generate Exact Clone Document</button> <a class='btn btn2' href='/case/{case_id}'>Back</a>
    </form></div>"""
    return page('Clone Document', body, 'Document Generator')

@app.route('/report-select/<int:case_id>', methods=['GET','POST'])
def report_select(case_id):
    con=db(); case=con.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone(); con.close()
    if not case: abort(404)
    if request.method=='POST':
        report_type=request.form.get('report_type','Analyst Observation Sheet')
        output_format=request.form.get('output_format','Editable DOCX')
        return redirect(url_for('generate_report', case_id=case_id, report_type=report_type, output_format=output_format))
    body=f"""<div class='card'><h2>Select Report Before Delivery</h2><p><b>Case:</b> {html.escape(case['title'])}</p><form method='post'>
    <label>Which report/document do you want?</label><select name='report_type'>{options(REPORT_TYPES, 'Analyst Observation Sheet')}</select>
    <label>Select output format</label><select name='output_format'>{options(FORMAT_TYPES, 'Editable DOCX')}</select>
    <button class='btn'>Generate Selected Report</button> <a class='btn btn2' href='/case/{case_id}'>Back</a></form></div>"""
    return page('Report Selection', body, 'Reports')

@app.route('/generate-report/<int:case_id>')
def generate_report(case_id):
    report_type=request.args.get('report_type','Analyst Observation Sheet')
    output_format=request.args.get('output_format','Editable DOCX')
    folder=GENERATED/str(case_id); folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[^A-Za-z0-9_]+','_', report_type).strip('_') or 'Report'
    if output_format == 'Editable DOCX':
        path=folder/f'{safe}.docx'; generate_docx(case_id, report_type, path)
    elif output_format == 'Editable ODT':
        path=folder/f'{safe}.odt'; generate_odt_minimal(case_id, report_type, path)
    else:
        _, _, _, _, _, _, _, _, _, html_body = build_report_content(case_id, report_type)
        path=folder/f'{safe}.html'; path.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(report_type)}</title>{CSS}</head><body>{html_body}</body></html>", encoding='utf-8')
    con=db(); con.execute('INSERT INTO reports(case_id,report_type,output_format,file_path,created_at) VALUES(?,?,?,?,?)',(case_id,report_type,output_format,str(path),datetime.now().isoformat(timespec='seconds'))); con.commit(); con.close()
    return send_file(path, as_attachment=(output_format!='HTML Preview'))

@app.route('/reports')
def reports():
    con=db(); rows=con.execute('SELECT reports.*, cases.title FROM reports LEFT JOIN cases ON cases.id=reports.case_id ORDER BY reports.id DESC LIMIT 100').fetchall(); con.close()
    body="<div class='card'><h2>Generated Reports</h2><table><tr><th>ID</th><th>Case</th><th>Report</th><th>Format</th><th>Created</th><th>Action</th></tr>"
    for r in rows:
        body += f"<tr><td>{r['id']}</td><td>{html.escape(r['title'] or '')}</td><td>{html.escape(r['report_type'] or '')}</td><td>{html.escape(r['output_format'] or '')}</td><td>{r['created_at']}</td><td><a href='/report-file/{r['id']}'>Open</a></td></tr>"
    body += "</table></div>"
    return page('Reports', body, 'Reports')

@app.route('/report-file/<int:report_id>')
def report_file(report_id):
    con=db(); r=con.execute('SELECT * FROM reports WHERE id=?',(report_id,)).fetchone(); con.close()
    if not r or not r['file_path']: abort(404)
    return send_file(r['file_path'], as_attachment=False)


def template_file_path(t):
    return TEMPLATE_STORE / t['saved_name']

@app.route('/templates/upload', methods=['POST'])
def upload_template():
    facility = request.form.get('facility','').strip()
    template_type = request.form.get('template_type','').strip()
    version = request.form.get('version','1.0').strip() or '1.0'
    f = request.files.get('template_file')
    if not facility or not template_type or not f or not f.filename:
        flash('Select facility, template type and file.')
        return redirect(url_for('templates_page'))
    if not f.filename.lower().endswith(('.docx','.odt')):
        flash('Only DOCX/ODT master templates are accepted for exact clone.')
        return redirect(url_for('templates_page'))
    safe = secure_filename(f.filename)
    stamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    saved = f"{stamp}_{safe}"
    TEMPLATE_STORE.mkdir(parents=True, exist_ok=True)
    f.save(TEMPLATE_STORE / saved)
    con=db()
    old=con.execute('SELECT * FROM master_templates WHERE facility=? AND template_type=?',(facility,template_type)).fetchone()
    if old:
        try:
            old_path = TEMPLATE_STORE / old['saved_name']
            if old_path.exists(): old_path.unlink()
        except Exception:
            pass
        con.execute('UPDATE master_templates SET original_name=?, saved_name=?, version=?, status=?, uploaded_at=? WHERE facility=? AND template_type=?',
                    (f.filename, saved, version, 'Active', datetime.now().isoformat(timespec='seconds'), facility, template_type))
    else:
        con.execute('INSERT INTO master_templates(facility,template_type,original_name,saved_name,version,status,uploaded_at) VALUES(?,?,?,?,?,?,?)',
                    (facility, template_type, f.filename, saved, version, 'Active', datetime.now().isoformat(timespec='seconds')))
    con.commit(); con.close()
    flash(f'{template_type} template uploaded for {facility}.')
    return redirect(url_for('templates_page'))

@app.route('/templates/<int:template_id>/download')
def download_template(template_id):
    con=db(); t=con.execute('SELECT * FROM master_templates WHERE id=?',(template_id,)).fetchone(); con.close()
    if not t: abort(404)
    return send_file(template_file_path(t), as_attachment=True, download_name=t['original_name'])

@app.route('/templates/<int:template_id>/delete', methods=['POST'])
def delete_template(template_id):
    con=db(); t=con.execute('SELECT * FROM master_templates WHERE id=?',(template_id,)).fetchone()
    if not t: con.close(); abort(404)
    try:
        path=template_file_path(t)
        if path.exists(): path.unlink()
    except Exception:
        pass
    con.execute('DELETE FROM master_templates WHERE id=?',(template_id,)); con.commit(); con.close()
    flash('Template deleted.')
    return redirect(url_for('templates_page'))

@app.route('/templates/<int:template_id>/clone', methods=['GET','POST'])
def clone_library_template(template_id):
    con=db(); t=con.execute('SELECT * FROM master_templates WHERE id=?',(template_id,)).fetchone(); con.close()
    if not t: abort(404)
    if request.method=='POST':
        replacements=parse_replacements(request.form.get('replacements',''))
        if not replacements:
            flash('Enter replacement lines: old text => new text')
            return redirect(url_for('clone_library_template', template_id=template_id))
        src=template_file_path(t)
        ext=src.suffix.lower()
        folder=GENERATED/'library_clones'; folder.mkdir(parents=True, exist_ok=True)
        safe_kind=re.sub(r'[^A-Za-z0-9_]+','_',t['template_type']).strip('_') or 'Document'
        out=folder/f"{t['facility'].replace(' ','_')}_{safe_kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        if ext=='.docx':
            clone_docx_by_xml(src,out,replacements)
        elif ext=='.odt':
            clone_odt_by_xml(src,out,replacements)
        else:
            flash('Only DOCX/ODT supported.')
            return redirect(url_for('templates_page'))
        con=db(); con.execute('INSERT INTO reports(case_id,report_type,output_format,file_path,created_at) VALUES(?,?,?,?,?)',
                              (None, f"Cloned {t['template_type']}", 'Editable '+ext.upper().replace('.',''), str(out), datetime.now().isoformat(timespec='seconds'))); con.commit(); con.close()
        return send_file(out, as_attachment=True)
    body=f"""<div class='card'><h2>Clone {html.escape(t['template_type'])}</h2>
    <p><b>Facility:</b> {html.escape(t['facility'])}</p><p><b>Master:</b> {html.escape(t['original_name'])}</p>
    <form method='post'><label>Variable Replacement Data</label>
    <textarea name='replacements' style='min-height:280px' placeholder='Old text exactly as in template => New value'></textarea>
    <button class='btn'>Generate Exact Clone</button> <a class='btn btn2' href='/templates'>Back</a></form></div>"""
    return page('Clone Master Template', body, 'Template Library')


@app.route('/templates/<int:template_id>/mapping', methods=['GET','POST'])
def template_mapping(template_id):
    con=db(); t=con.execute('SELECT * FROM master_templates WHERE id=?',(template_id,)).fetchone(); con.close()
    if not t: abort(404)
    if request.method=='POST':
        action=request.form.get('action','add')
        if action=='add':
            key=request.form.get('variable_key','').strip()
            old=request.form.get('old_text','').strip()
            if key and old:
                con=db(); con.execute('INSERT INTO template_mappings(template_id,variable_key,old_text,created_at) VALUES(?,?,?,?)',(template_id,key,old,datetime.now().isoformat(timespec='seconds'))); con.commit(); con.close()
                flash('Mapping saved.')
            else: flash('Variable name and exact old text are required.')
        elif action=='delete':
            mid=int(request.form.get('mapping_id','0'))
            con=db(); con.execute('DELETE FROM template_mappings WHERE id=? AND template_id=?',(mid,template_id)); con.commit(); con.close(); flash('Mapping deleted.')
        return redirect(url_for('template_mapping',template_id=template_id))
    path=template_file_path(t)
    text=extract_template_text(path)
    candidates=suggest_variable_candidates(text)
    maps=mapping_rows(template_id)
    cand_html=''.join(f"<tr><td>{html.escape(c)}</td><td><form method='post' style='display:flex;gap:8px'><input type='hidden' name='old_text' value='{html.escape(c,quote=True)}'><input name='variable_key' placeholder='e.g. BorrowerName'><input type='hidden' name='action' value='add'><button class='btn small'>Add</button></form></td></tr>" for c in candidates)
    map_html=''.join(f"<tr><td>{html.escape(m['variable_key'])}</td><td>{html.escape(m['old_text'])}</td><td><form method='post'><input type='hidden' name='action' value='delete'><input type='hidden' name='mapping_id' value='{m['id']}'><button class='btn btnred small'>Delete</button></form></td></tr>" for m in maps) or "<tr><td colspan='3'>No mapping saved yet.</td></tr>"
    body=f"""<div class='card'><h2>Template Mapping Editor</h2><p><b>{html.escape(t['facility'])}</b> / {html.escape(t['template_type'])}<br>{html.escape(t['original_name'])}</p>
    <p class='note'>Add exact text from the master template and assign a variable name. Generation will replace only this exact text.</p>
    <form method='post'><input type='hidden' name='action' value='add'><div class='row'><div><label>Variable Name</label><input name='variable_key' placeholder='BorrowerName'></div><div><label>Exact Old Text in Template</label><input name='old_text' placeholder='Md. Ali Ahmed'></div></div><button class='btn'>Save Mapping</button> <a class='btn btn2' href='/templates/{template_id}/generate'>Generate Document</a> <a class='btn btn2' href='/templates'>Back</a></form></div>
    <div class='card'><h2>Saved Mapping</h2><table><tr><th>Variable</th><th>Exact Template Text</th><th>Action</th></tr>{map_html}</table></div>
    <div class='card'><h2>Auto-Suggested Candidates</h2><table><tr><th>Detected Text</th><th>Map As</th></tr>{cand_html}</table></div>
    <div class='card'><h2>Template Text Preview</h2><textarea readonly style='min-height:260px'>{html.escape(text[:12000])}</textarea></div>"""
    return page('Template Mapping Editor',body,'Template Library')

@app.route('/templates/<int:template_id>/generate', methods=['GET','POST'])
def template_generate(template_id):
    con=db(); t=con.execute('SELECT * FROM master_templates WHERE id=?',(template_id,)).fetchone(); con.close()
    if not t: abort(404)
    maps=mapping_rows(template_id)
    if request.method=='POST':
        mode=request.form.get('mode','manual')
        try:
            if mode=='manual':
                values={m['variable_key']:request.form.get(m['variable_key'],'').strip() for m in maps}
                out=generate_from_mapping(t,values,prefix=t['template_type'])
                con=db(); con.execute('INSERT INTO reports(case_id,report_type,output_format,file_path,created_at) VALUES(?,?,?,?,?)',(None, f"Generated {t['template_type']}", 'Editable '+out.suffix.upper().replace('.',''), str(out), datetime.now().isoformat(timespec='seconds'))); con.commit(); con.close()
                return send_file(out,as_attachment=True,download_name=out.name)
            elif mode=='bulk':
                import csv, io
                csv_text=request.form.get('csv_values','')
                reader=csv.DictReader(io.StringIO(csv_text))
                folder=GENERATED/'bulk_outputs'; folder.mkdir(parents=True,exist_ok=True)
                stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
                zip_path=folder/f"bulk_{t['template_type'].replace(' ','_')}_{stamp}.zip"
                generated=[]
                for i,row in enumerate(reader,1):
                    prefix=row.get('FileName') or row.get('BorrowerName') or f'Document_{i}'
                    out=generate_from_mapping(t,{k:(v or '').strip() for k,v in row.items()},prefix=prefix)
                    generated.append(out)
                with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
                    for f in generated: z.write(f,arcname=f.name)
                return send_file(zip_path,as_attachment=True,download_name=zip_path.name)
        except Exception as e:
            flash('Generation failed: '+str(e))
            return redirect(url_for('template_generate',template_id=template_id))
    fields=''.join(f"<label>{html.escape(m['variable_key'])}</label><input name='{html.escape(m['variable_key'],quote=True)}' placeholder='New value replacing: {html.escape(m['old_text'],quote=True)}'>" for m in maps)
    header=','.join(['FileName']+[m['variable_key'] for m in maps])
    sample=header+'\nSample_1,'+','.join(['' for _ in maps])
    body=f"""<div class='card'><h2>Generate from Mapped Template</h2><p><b>{html.escape(t['facility'])}</b> / {html.escape(t['template_type'])}</p>
    <p class='note'>Mapped variables: {len(maps)}. If zero, go to Mapping first.</p>
    <form method='post'><input type='hidden' name='mode' value='manual'>{fields}<button class='btn'>Generate One Editable Document</button> <a class='btn btn2' href='/templates/{template_id}/mapping'>Edit Mapping</a></form></div>
    <div class='card'><h2>Bulk Generate Many Documents</h2><p>Paste CSV. Header must match variable names. Add optional FileName column.</p>
    <form method='post'><input type='hidden' name='mode' value='bulk'><textarea name='csv_values' style='min-height:260px'>{html.escape(sample)}</textarea><button class='btn'>Generate ZIP of Documents</button></form></div>"""
    return page('Generate from Mapping',body,'Template Library')

@app.route('/templates')
def templates_page():
    con=db(); rows=con.execute('SELECT * FROM master_templates ORDER BY facility, template_type').fetchall(); con.close()
    lookup={(r['facility'],r['template_type']):r for r in rows}
    body="""<div class='card'><h2>Template Library</h2><p class='note'>Functional library: upload/replace master DOCX or ODT. Clone output preserves the uploaded template format and replaces only variable text.</p>
    <form method='post' action='/templates/upload' enctype='multipart/form-data'><div class='row3'>
    <div><label>Facility</label><select name='facility'>"""+options(FACILITY_CHECKLISTS.keys())+"""</select></div>
    <div><label>Template Type</label><select name='template_type'><option>Notesheet</option><option>Sanction Letter</option><option>Forwarding Letter</option><option>Shariah Opinion</option></select></div>
    <div><label>Version</label><input name='version' value='1.0'></div></div>
    <label>Select Master Template DOCX/ODT</label><input type='file' name='template_file' accept='.docx,.odt'>
    <button class='btn'>Upload / Replace Template</button></form></div>
    <div class='card'><h2>Stored Master Templates</h2><table><tr><th>Facility</th><th>Notesheet</th><th>Sanction Letter</th><th>Forwarding Letter</th><th>Shariah Opinion</th></tr>"""
    types=['Notesheet','Sanction Letter','Forwarding Letter','Shariah Opinion']
    for facility in FACILITY_CHECKLISTS:
        body += f"<tr><td>{html.escape(facility)}</td>"
        for typ in types:
            t=lookup.get((facility,typ))
            if t:
                body += f"<td><b>{html.escape(t['original_name'])}</b><br><span class='pill ok'>Active v{html.escape(t['version'] or '1.0')}</span><br><a class='btn btn2 small' href='/templates/{t['id']}/download'>Download</a> <a class='btn btn2 small' href='/templates/{t['id']}/mapping'>Mapping</a> <a class='btn btn2 small' href='/templates/{t['id']}/generate'>Generate</a> <a class='btn btn2 small' href='/templates/{t['id']}/clone'>Old Clone</a> <form method='post' action='/templates/{t['id']}/delete' style='display:inline' onsubmit='return confirm(&quot;Delete this template?&quot;)'><button class='btn btnred small'>Delete</button></form></td>"
            else:
                body += "<td><span class='pill warn'>Pending Upload</span></td>"
        body += "</tr>"
    body += "</table></div>"
    return page('Templates', body, 'Template Library')

@app.route('/document-intelligence')
def doc_intel():
    return page('AI Document Intelligence', "<div class='card'><h2>AI Document Intelligence</h2><p>This build uses local keyword-based classification. AI API connection will be added in next version.</p><a class='btn' href='/pandora'>Open Pandora Box</a></div>", 'AI Document Intelligence')

@app.route('/credit-analysis')
def credit_analysis_page():
    return page('Credit Analysis', "<div class='card'><h2>Credit Analysis</h2><p>Open a case and run analysis to verify checklist, missing documents and basic risk score.</p><a class='btn' href='/pandora'>Select Case</a></div>", 'Credit Analysis')

@app.route('/icrr')
def icrr_page():
    return page('ICRR', "<div class='card'><h2>ICRR Risk Engine</h2><p>ICRR currently scores Credit, Documentation, Financial, Legal and Compliance risk from uploaded files.</p><a class='btn' href='/pandora'>Run From Case</a></div>", 'ICRR Risk Engine')

@app.route('/generator')
def generator_page():
    return page('Document Generator', "<div class='card'><h2>Document Generator</h2><p>Generate only cloned Notesheet / Sanction Letter from uploaded master proforma. No data sheet.</p><a class='btn' href='/pandora'>Select Case</a></div>", 'Document Generator')

@app.route('/admin')
def admin_page():
    return page('Administration', "<div class='card'><h2>Administration</h2><p>User roles, template approval, backup and audit logs will be configured here in future build.</p></div>", 'Administration')

@app.route('/settings')
def settings():
    return page('Settings', "<div class='card'><h2>Settings</h2><p>AI provider, offline mode, backup path and user roles will be configured here in next build.</p></div>", 'Settings')

if __name__ == '__main__':
    print('PCIA v0.2 running at http://127.0.0.1:5050')
    app.run(host='127.0.0.1', port=5050, debug=False)

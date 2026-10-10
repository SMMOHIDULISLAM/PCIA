from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


def _set_cell_border(cell, **kwargs):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = tcPr.first_child_found_in("w:tcBorders")
    if tcBorders is None:
        tcBorders = OxmlElement("w:tcBorders")
        tcPr.append(tcBorders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        if edge in kwargs:
            edge_data = kwargs.get(edge)
            tag = "w:{}".format(edge)
            element = tcBorders.find(qn(tag))
            if element is None:
                element = OxmlElement(tag)
                tcBorders.append(element)
            for key in ["val", "sz", "space", "color"]:
                if key in edge_data:
                    element.set(qn("w:{}".format(key)), str(edge_data[key]))


def _no_borders(table):
    for row in table.rows:
        for cell in row.cells:
            _set_cell_border(
                cell,
                top={"val": "nil"}, left={"val": "nil"}, bottom={"val": "nil"}, right={"val": "nil"}
            )


def _set_run_font(run, name="Times New Roman", size=11, bold=None, color=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


def _add_mixed_paragraph(doc, title: str, detail: str, action: str | None = None, number: int | None = None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.05
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if number is not None:
        r = p.add_run(f"{number}. ")
        _set_run_font(r, bold=True)
    r = p.add_run(title + ": ")
    _set_run_font(r, bold=True)
    r = p.add_run(detail)
    _set_run_font(r)
    if action:
        r = p.add_run(" Required action: ")
        _set_run_font(r, bold=True)
        r = p.add_run(action)
        _set_run_font(r)
    return p


def _subject_for_letter(values: dict[str, str]) -> str:
    subject = (values.get("branch_subject") or "").strip()
    subject = re.sub(r"^Sub(?:ject)?\s*:\s*", "", subject, flags=re.I)
    borrower = values.get('borrower_name', 'N/F')
    # A PDF may split the branch subject across lines. Rebuild it when the captured text is incomplete.
    incomplete = (not subject or borrower.lower() not in subject.lower() or "branch" not in subject.lower())
    if incomplete:
        amount_words = values.get('amount_words', 'N/F')
        amount_words = re.sub(r"^Taka\s+", "", amount_words, flags=re.I)
        grace = values.get('grace_period', 'N/F')
        if re.fullmatch(r"0?6\s*months?", grace, flags=re.I):
            grace = "06 (Six) Months"
        subject = (
            f"Proposal for sanction of a {values.get('facility_type', 'Loan Facility')} limit of "
            f"{values.get('loan_amount', 'N/F')}/- ({amount_words}) only for the period of "
            f"{values.get('tenure', 'N/F')} with {grace} Grace Period "
            f"A/c. {borrower} of our Branch."
        )
    subject = re.sub(r"\bour Branch\b", "your Branch", subject, flags=re.I)
    return subject


def generate_anomaly_letter(
    output_path: Path,
    values: dict[str, str],
    anomalies: list[dict[str, Any]],
    doc_status: dict[str, str],
    logo_path: Path,
    reference_no: str | None = None,
    assessment_date: datetime | None = None,
) -> Path:
    assessment_date = assessment_date or datetime.now()
    reference_no = reference_no or f"PBPCL/RO/SYL-WEST/PROP/____/{assessment_date.year}"

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.35)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)

    styles = doc.styles
    styles["Normal"].font.name = "Times New Roman"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    styles["Normal"].font.size = Pt(11)

    header = doc.add_table(rows=1, cols=2)
    header.alignment = WD_TABLE_ALIGNMENT.CENTER
    header.autofit = False
    header.columns[0].width = Inches(4.25)
    header.columns[1].width = Inches(2.7)
    _no_borders(header)
    c0, c1 = header.rows[0].cells
    c0.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    c1.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if logo_path.exists():
        p = c0.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.add_run().add_picture(str(logo_path), width=Inches(4.15))
    p = c1.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for i, text in enumerate([
        "REGIONAL OFFICE, SYLHET WEST",
        "Syl-Valley Castle, VIP Road, Telihaor, Sylhet-3100.",
        "Tel.: 0821-728919 & 728461, Cell # 01926-996360",
        "IP No. 09612827471-78, Fax No. 880-821-714821",
        "rosylwest@pubalibankbd.com | www.pubalibangla.com",
    ]):
        if i:
            p.add_run("\n")
        r = p.add_run(text)
        _set_run_font(r, name="Arial", size=10 if i == 0 else 7.5, bold=(i == 0), color=(0, 102, 0))

    # Green divider line.
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(4)
    pPr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "008000")
    pbdr.append(bottom)
    pPr.append(pbdr)

    rt = doc.add_table(rows=1, cols=2)
    rt.alignment = WD_TABLE_ALIGNMENT.CENTER
    rt.autofit = False
    rt.columns[0].width = Inches(4.6)
    rt.columns[1].width = Inches(2.4)
    _no_borders(rt)
    left, right = rt.rows[0].cells
    p = left.paragraphs[0]
    r = p.add_run(f"REF: {reference_no}")
    _set_run_font(r, name="Arial", size=10.5, bold=True)
    p = right.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p.add_run(f"Date: {assessment_date.strftime('%d.%m.%Y')}")
    _set_run_font(r, name="Arial", size=10.5, bold=True)

    branch = values.get("branch_name") or "Pathantula Branch, Sylhet"
    for line in ["The Branch Manager", "Pubali Bank PLC.", branch]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(line)
        _set_run_font(r, size=11)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(7)
    p.paragraph_format.space_after = Pt(7)
    r = p.add_run("Subject: ")
    _set_run_font(r, bold=True)
    r = p.add_run(_subject_for_letter(values))
    _set_run_font(r, bold=True)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run("Dear Sir,")
    _set_run_font(r)

    borrower = values.get("borrower_name", "N/F")
    facility = values.get("facility_type", "N/F")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run(
        f'With reference to your Credit proposal “{borrower} - {facility}”, we found the following anomalies and shortcomings. '
        "Please rectify the same and resubmit the proposal with the required supporting documents for further consideration."
    )
    _set_run_font(r)

    # Split into requested reporting groups.
    data_anomalies = [a for a in anomalies if a.get("category") != "Authenticity Verification"]
    authenticity = [a for a in anomalies if a.get("category") == "Authenticity Verification"]
    missing = [name for name, status in doc_status.items() if status == "N/F"]

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("A. ANOMALIES, WRONG INFORMATION AND DATA MISMATCHES")
    _set_run_font(r, bold=True, size=11.5)

    serial = 1
    for item in data_anomalies:
        _add_mixed_paragraph(doc, item.get("title", "Anomaly"), item.get("detail", ""), item.get("action"), serial)
        serial += 1

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("B. SHORTAGE OF NECESSARY DOCUMENTS / INFORMATION")
    _set_run_font(r, bold=True, size=11.5)

    if missing:
        for name in missing:
            _add_mixed_paragraph(
                doc,
                name,
                "The document/information could not be reliably identified in the submitted proposal packet.",
                "Submit a clear, current and duly authenticated copy, or state why it is not applicable.",
                serial,
            )
            serial += 1
    else:
        _add_mixed_paragraph(doc, "Document checklist", "No checklist item was automatically marked missing; however, adequacy and validity must still be verified from originals.", None, serial)
        serial += 1

    # Case-specific missing/support requirements even when keyword detection marked a document submitted.
    support_requirements = [
        ("Updated borrower liability certificate", "The submitted borrower liability certificate is dated 25.09.2025 and is not contemporaneous with the proposal dated 21.06.2026."),
        ("Employment and income evidence", "Submit service certificate, latest pay certificate, salary account statements and proof of spouse salary/agricultural income used in repayment assessment."),
        ("Corrected applicant-specific cost estimate", "Submit a certified estimate reconciling total project cost, cost attributable to the applicant, work completed, own contribution and balance requirement."),
        ("Corrected valuation report with FSV", "Submit corrected rate/value arithmetic and state Market Value, Forced Sale Value and security coverage."),
        ("Verified title and proportionate land-share documents", "Submit deed/allotment/partition documents, mutation record, rent receipt, EC, approved plan and legal opinion showing the exact mortgagable share."),
        ("Guarantor information", "Provide complete details, NID verification, liability/CIB, net worth and consent/personal guarantee of Pinku Ranjan Das."),
    ]
    for title, detail in support_requirements:
        _add_mixed_paragraph(doc, title, detail, "Submit the required evidence with the corrected proposal.", serial)
        serial += 1

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("C. DOCUMENTS / ENTRIES REQUIRING AUTHENTICITY, SOURCE AND LEGIBILITY VERIFICATION")
    _set_run_font(r, bold=True, size=11.5)

    if authenticity:
        for item in authenticity:
            _add_mixed_paragraph(doc, item.get("title", "Verification required"), item.get("detail", ""), item.get("action"), serial)
            serial += 1
    else:
        _add_mixed_paragraph(
            doc,
            "Original-document verification",
            "No conclusion that any document is counterfeit, fabricated or synthetic can be reached from the submitted copies alone. Materially inconsistent entries must nevertheless be checked against the originals and issuing-office records.",
            "Verify original deeds, mutation records, valuation, approvals, certificates and signatures from their issuing sources.",
            serial,
        )
        serial += 1

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_before = Pt(7)
    p.paragraph_format.space_after = Pt(10)
    r = p.add_run(
        "You are requested to submit a point-wise compliance reply along with the corrected proposal and supporting documents. "
        "The proposal may be reassessed after satisfactory rectification of the above issues."
    )
    _set_run_font(r)

    p = doc.add_paragraph()
    r = p.add_run("Yours faithfully,")
    _set_run_font(r)

    sig = doc.add_table(rows=1, cols=2)
    sig.alignment = WD_TABLE_ALIGNMENT.CENTER
    sig.autofit = False
    sig.columns[0].width = Inches(3.6)
    sig.columns[1].width = Inches(3.6)
    _no_borders(sig)
    for idx, (title, align) in enumerate([
        ("Assessment Officer", WD_ALIGN_PARAGRAPH.LEFT),
        ("Regional Relationship Manager", WD_ALIGN_PARAGRAPH.RIGHT),
    ]):
        cell = sig.rows[0].cells[idx]
        p = cell.paragraphs[0]
        p.alignment = align
        r = p.add_run("\n\n\n____________________________\n" + title + "\nPubali Bank PLC.\nRegional Office, Sylhet West")
        _set_run_font(r, size=10.5, bold=True)

    # Footer page number.
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("PCIA Credit Proposal Anomaly & Shortcoming Report")
    _set_run_font(r, name="Arial", size=8, color=(100, 100, 100))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    return output_path

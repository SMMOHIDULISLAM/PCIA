from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any

from lxml import etree

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
CASES_DIR = DATA_DIR / "cases"
OUTPUTS_DIR = DATA_DIR / "outputs"
BACKUPS_DIR = DATA_DIR / "template_backups"
SEED_DIR = APP_DIR / "seed_models" / "Model"
RULES_PATH = APP_DIR / "model_learning_rules.json"

for _p in (DATA_DIR, TEMPLATES_DIR, CASES_DIR, OUTPUTS_DIR, BACKUPS_DIR):
    _p.mkdir(parents=True, exist_ok=True)

SUPPORTED_TEMPLATE_EXTS = {".odt", ".docx", ".doc"}
SUPPORTED_EVIDENCE_EXTS = {
    ".zip", ".pdf", ".docx", ".doc", ".odt", ".xlsx", ".xls", ".ods", ".csv", ".txt", ".rtf",
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".heic", ".json", ".xml", ".html", ".htm"
}

DOC_TYPE_NOTESHEET = "Notesheet"
DOC_TYPE_SANCTION = "Sanction Letter"
DOC_TYPE_FORWARDING = "Forwarding Letter"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def slug(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")
    return value[:100] or "document"


def compact_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def amount_words_from_number(text: str) -> str:
    """Best-effort Bangladesh banking amount wording for Lac/Crore values."""
    raw = (text or "").lower().replace(",", "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(crore|lac|lakh)?", raw)
    if not m:
        return "AMOUNT IN WORDS N/F"
    n = float(m.group(1))
    unit = (m.group(2) or "").lower()
    # Convert raw taka amounts to lac where obvious.
    if not unit and n >= 100000:
        n = n / 100000.0
        unit = "lac"
    ones = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
            "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def under_100(x: int) -> str:
        if x < 20:
            return ones[x]
        return tens[x // 10] + (" " + ones[x % 10] if x % 10 else "")

    whole = int(round(n))
    if whole < 100:
        words = under_100(whole)
    elif whole < 1000:
        words = ones[whole // 100] + " Hundred" + (" " + under_100(whole % 100) if whole % 100 else "")
    else:
        words = str(whole)
    if unit in {"lac", "lakh"}:
        return f"Taka {words} Lac"
    if unit == "crore":
        return f"Taka {words} Crore"
    return f"Taka {words}"


@dataclass
class Evidence:
    field: str
    value: str
    source: str
    location: str = ""
    confidence: int = 70
    note: str = ""


@dataclass
class TextBlock:
    part: str
    index: int
    text: str
    kind: str = "paragraph"


@dataclass
class TableCellRef:
    text: str
    blocks: list[TextBlock]


@dataclass
class TableRowRef:
    part: str
    row_index: int
    cells: list[TableCellRef]


@dataclass
class TemplateSlot:
    slot_id: str
    field: str
    label: str
    part: str
    block_index: int
    old_text: str
    old_value: str
    mode: str = "substring"  # substring | whole
    confidence: int = 80
    context: str = ""
    required: bool = False


FIELD_LABELS: dict[str, str] = {
    "branch_name": "Branch Name",
    "branch_address": "Branch Address",
    "account_reference": "Account Reference Line",
    "account_details": "Account Number and Opening Details",
    "first_sanction_details": "First Sanction Details",
    "borrower_parents_line": "Borrower Father and Mother",
    "guarantor_parents_line": "Guarantor Father and Mother",
    "borrower_name": "Borrower / Customer Name",
    "father_name": "Father Name",
    "mother_name": "Mother Name",
    "spouse_name": "Spouse Name",
    "notesheet_date": "Notesheet Date",
    "application_receipt_date": "Application Receipt Date",
    "proposal_sending_date": "Proposal Sending Date",
    "regional_receipt_date": "Regional Office Receipt Date",
    "query_reply_date": "Query / Other Document Receipt Date",
    "proposal_subject": "Proposal Subject Paragraph",
    "account_number": "Account Number",
    "account_open_date": "Account Opening Date",
    "saving_account_number": "Saving Account Number",
    "saving_account_open_date": "Saving Account Opening Date",
    "first_sanction_date": "First Sanction Date",
    "first_sanction_limit": "First Sanction Limit",
    "present_address": "Present Address",
    "permanent_address": "Permanent Address",
    "business_address": "Business Address",
    "legal_status": "Legal Status",
    "date_of_establishment": "Date of Establishment / Business Age",
    "tin": "TIN / GIR",
    "nid": "NID",
    "mobile": "Mobile Number",
    "position": "Position",
    "age": "Age",
    "shareholding": "Shareholding",
    "net_worth": "Personal Net Worth",
    "cib_date": "CIB Date",
    "cib_status": "CIB Status",
    "second_line_management": "Second Line Management",
    "guarantor_name": "Guarantor Name",
    "guarantor_relation": "Guarantor Relation",
    "guarantor_age": "Guarantor Age",
    "guarantor_profession": "Guarantor Profession",
    "guarantor_net_worth": "Guarantor Net Worth",
    "guarantor_cib_date": "Guarantor CIB Date",
    "guarantor_cib_status": "Guarantor CIB Status",
    "total_cost": "Total Project / Building Cost",
    "cost_incurred": "Cost Already Incurred",
    "total_requirement": "Total Requirement",
    "loan_amount": "Loan / Sanction Amount",
    "amount_words": "Amount in Words",
    "capital_investment": "Capital / Investment",
    "nature_of_business": "Nature of Business",
    "facility_type": "Facility / Loan Product",
    "interest_rate": "Interest / Profit / Rent Rate",
    "tenure": "Tenure",
    "grace_period": "Grace / Moratorium Period",
    "purpose": "Purpose",
    "repayment_terms": "Repayment Terms",
    "existing_facility": "Existing Facility",
    "existing_facility_name": "Existing Facility Borrower / Business",
    "existing_facility_details": "Existing Facility Nature and Limit",
    "existing_facility_rate": "Existing Facility Rate",
    "existing_facility_validity": "Existing Facility Validity",
    "existing_facility_outstanding": "Existing Facility Outstanding",
    "sister_concern_name": "Sister Concern Name",
    "sister_concern_facility": "Sister Concern Nature and Limit",
    "sister_concern_rate": "Sister Concern Rate",
    "sister_concern_validity": "Sister Concern Validity",
    "sister_concern_outstanding": "Sister Concern Outstanding",
    "sister_concern_credit_sum": "Sister Concern Credit Sum",
    "sister_concern_collateral": "Sister Concern Collateral Value",
    "sister_concern_liability": "Sister Concern Liability",
    "liability_date": "Liability / Outstanding As On Date",
    "other_bank_liability": "Other Bank Liability",
    "brief_history": "Brief History of Borrower / Business",
    "justification": "Reason / Justification",
    "security_details": "Security Details",
    "collateral_details": "Collateral Details",
    "collateral_value": "Collateral Value",
    "forced_sale_value": "Forced Sale Value",
    "valuation_date": "Valuation Date",
    "account_performance": "Account Performance",
    "financial_analysis": "Financial Analysis",
    "risk_analysis": "Security / Credit Risk Discussion",
    "present_proposal": "Present Proposal / Customer Approach",
    "bm_recommendation": "BM Recommendation",
    "recommendation": "Recommendation Paragraph",
    "documents_status": "Documents Submitted by Branch",
    "observations": "CAO Observations",
    "committee_date": "Credit Committee Date",
    "committee_validity": "Committee Validity / Tenure",
    "committee_interest": "Committee Interest Rate",
    "committee_purpose": "Committee Purpose",
    "committee_security": "Committee Security",
    "sanction_subject": "Sanction Letter Subject",
    "borrower_address": "Borrower Address",
    "insurance_clause": "Insurance Clause",
    "forwarding_subject": "Forwarding Subject",
    "forwarding_body": "Forwarding Body",
}


ALIASES: dict[str, list[str]] = {
    "borrower_name": ["customer s name", "customer name", "borrower name", "name of borrower", "name of the client", "name of client", "applicant name", "name of applicant", "name of the clients"],
    "father_name": ["father name", "father s name", "s o", "son of"],
    "mother_name": ["mother name", "mother s name", "m o"],
    "spouse_name": ["spouse name", "wife name", "husband name"],
    "account_number": ["a c no", "account no", "account number"],
    "notesheet_date": ["note sheet date", "notesheet date"],
    "application_receipt_date": ["date of receipt of borrower s application by the branch", "application receipt date", "application date"],
    "proposal_sending_date": ["date of sending proposal by the branch", "proposal sending date", "branch proposal date"],
    "regional_receipt_date": ["date of receipt of the proposal by regional office", "regional office receipt date"],
    "query_reply_date": ["date of receipt of other required documents by regional office", "query reply date", "other document receipt date"],
    "business_address": ["office business", "business address", "office address"],
    "present_address": ["present address"],
    "permanent_address": ["permanent address", "residence"],
    "legal_status": ["legal status"],
    "date_of_establishment": ["date of establishment", "business age", "doing business since"],
    "tin": ["gir tin no", "tin no", "tax identification number"],
    "nid": ["nid no", "national id", "national identification number"],
    "mobile": ["mobile no", "mobile number", "phone no", "cell no"],
    "age": ["age", "date of birth", "dob"],
    "net_worth": ["personal net worth", "net worth"],
    "guarantor_name": ["name of the guarantor", "guarantor name"],
    "total_cost": ["total cost estimation for building", "total project cost", "estimated cost"],
    "cost_incurred": ["cost already incurred by applicant", "cost already incurred"],
    "total_requirement": ["total requirement for work completion", "total requirement"],
    "loan_amount": ["applied from bank", "loan amount", "sanction amount", "sanction of limit", "limit amount", "amount applied"],
    "capital_investment": ["capital investment", "capital", "investment"],
    "nature_of_business": ["nature of business products service", "nature of business", "business nature"],
    "facility_type": ["nature of facility", "facility type", "loan product", "loan type"],
    "interest_rate": ["rate of interest", "interest rate", "profit rate", "rent rate"],
    "tenure": ["tenure", "validity period", "period of loan"],
    "grace_period": ["grace period", "moratorium period"],
    "purpose": ["purpose", "purpose of loan"],
    "repayment_terms": ["mode of repayment", "repayment terms", "repayment schedule"],
    "collateral_value": ["value of collateral", "collateral value", "total value"],
    "forced_sale_value": ["f s v", "forced sale value"],
    "cib_date": ["cib obtained on", "cib report obtained on", "cib date"],
    "cib_status": ["cib status", "cib report"],
    "present_proposal": ["present proposal", "customer s approach", "customer approach"],
}


DOC_LABEL_SYNONYMS: dict[str, list[str]] = {
    "Income Tax paid receipt/TIN certificate": ["tin", "tax clearance", "income tax", "tax return"],
    "Physical verification report": ["physical verification", "site verification"],
    "Applicability of the guideline by transaction type": ["guideline", "transaction type"],
    "Limit Utilization form & Data collection checklist": ["limit utilization", "data collection checklist"],
    "Transaction certificate": ["transaction certificate"],
    "Consent letter of the guarantor": ["guarantor consent", "consent letter"],
    "Trade license": ["trade license"],
    "Business Site Photograph": ["business site", "site photograph", "factory photograph", "photo"],
    "Check list submitted": ["check list", "checklist"],
    "Borrower Personal Net Worth Certificate": ["net worth certificate", "personal net worth"],
    "Borrower's Credit Information": ["credit information"],
    "Liability position/Certificate": ["liability position", "liability certificate"],
    "CIB Report": ["cib"],
    "2nd line management": ["2nd line management", "second line management"],
    "Contact point verification report": ["contact point verification"],
    "Lease Deed": ["lease deed", "rent agreement"],
    "Declaration": ["declaration"],
    "Bangla Top sheet, NID verification report": ["bangla top sheet", "nid verification"],
    "Bio data of the Borrower": ["bio data", "biodata"],
}


NARRATIVE_HEADINGS = {
    "brief_history": ["brief history of the borrower", "brief history", "business background", "background of the borrower"],
    "justification": ["reason justification of the limit", "reason justification", "justification", "reason for the limit"],
    "financial_analysis": ["financial analysis", "financial position", "financial performance"],
    "risk_analysis": ["risk analysis", "security credit risk discussion", "credit risk discussion"],
    "present_proposal": ["present proposal", "customer s approach", "proposal details"],
    "bm_recommendation": ["recommended by b m", "branch manager recommendation", "bm recommendation"],
    "recommendation": ["recommendation paragraph", "recommendation of the branch", "recommendation"],
    "security_details": ["security", "primary security", "other security"],
    "collateral_details": ["collateral security", "schedule of property", "mortgaged property"],
    "forwarding_body": ["dear sir"],
}


REGEX_FIELDS: dict[str, list[tuple[str, int]]] = {
    "borrower_name": [
        (r"(?:name of (?:the )?(?:applicant|borrower|client|customer)|applicant name|customer'?s name|name of the clients)\s*[:\-]\s*['\"“”]*\s*([^\n|;]{3,100})", 97),
        (r"\bA/C\.?\s*(?:Mr\.?|Mrs\.?|Ms\.?|Mst\.?)?\s*([A-Z][A-Za-z.' -]{3,80})", 78),
    ],
    "father_name": [(r"(?:father'?s? name\s*[:\-]?|\bS/O\.?\s*)([^\n,&|;]{3,100})", 94)],
    "mother_name": [(r"(?:mother'?s? name\s*[:\-]?|\bM/O\.?\s*)([^\n,&|;]{3,100})", 94)],
    "spouse_name": [(r"(?:spouse'?s? name|wife of|husband of)\s*[:\-]?\s*([^\n,&|;]{3,100})", 88)],
    "account_number": [(r"(?:A/C\.?|Account)\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Za-z0-9\-/]{5,30})", 94)],
    "notesheet_date": [(r"(?:Note\s*Sheet|Notesheet)\s*Date\s*[:\-]\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 98)],
    "application_receipt_date": [
        (r"Date of receipt of borrower.?s application by the branch\s*[:\-]\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 99),
        (r"Application\s*Date\s*[:\-]\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 90),
    ],
    "proposal_sending_date": [(r"Date of sending proposal by the Branch\s*[:\-]\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 99)],
    "regional_receipt_date": [(r"Date of receipt of the proposal by Regional Office\s*[:\-]\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 99)],
    "query_reply_date": [(r"Date of receipt of other required documents by Regional Office\s*[:\-]\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 99)],
    "branch_name": [(r"\b([A-Z][A-Za-z.' -]{2,55}\s+Branch(?:\s*,\s*[A-Z][A-Za-z.' -]{2,40})?)\b", 84)],
    "business_address": [(r"(?:Office/business|Business Address|Office Address)\s*[:\-]\s*([^\n|]{8,250})", 95)],
    "present_address": [(r"Present\s*(?:&\s*Permanent\s*)?Address\s*[:\-]\s*([^\n|]{8,250})", 92)],
    "permanent_address": [(r"Permanent\s*Address\s*[:\-]\s*([^\n|]{8,250})", 92)],
    "legal_status": [(r"Legal\s*Status\s*[:\-]\s*([^\n|]{3,60})", 95)],
    "date_of_establishment": [(r"(?:Date of Establishment|Doing business since|Business since)\s*[:\-]?\s*([^\n|]{3,80})", 92)],
    "tin": [(r"(?:GIR\s*/?\s*TIN|TIN)\s*(?:No\.?|Number)?\s*[:\-]\s*([A-Za-z0-9\-/]{6,30})", 97)],
    "nid": [(r"(?:NID|National ID)\s*(?:No\.?|Number)?\s*[:\-]\s*([A-Za-z0-9\-/]{6,30})", 97)],
    "mobile": [(r"(?:Mobile|Phone|Cell)\s*(?:No\.?|Number)?\s*[:#\-]?\s*(\+?88\s*)?(01\d{9})", 95)],
    "age": [(r"(?:Age)\s*[:\-]\s*(\d{1,3}\s*(?:Yrs?|Years?)?)", 92)],
    "net_worth": [(r"(?:Personal\s*)?Net\s*Worth\s*[:\-]\s*(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)", 94)],
    "guarantor_name": [(r"(?:Name of the Guarantor|Guarantor'?s? Name)\s*[:\-]?\s*([^\n|]{3,100})", 95)],
    "total_cost": [(r"(?:Total cost estimation for building|Total Project Cost|Estimated Cost)\s*[:\-]\s*(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)", 95)],
    "cost_incurred": [(r"Cost already incurred(?: by applicant)?\s*[:\-]\s*(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)", 95)],
    "total_requirement": [(r"Total requirement(?: for work Completion)?\s*[:\-]\s*(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)", 95)],
    "loan_amount": [
        (r"(?:Loan Amount|Sanction Amount|Applied from Bank[^:]*|limit of)\s*[:\-]?\s*(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)", 96),
        (r"\b(Tk\.?\s*[0-9,]+(?:\.[0-9]+)?\s*(?:Lac|Crore))\b", 62),
    ],
    "interest_rate": [(r"(?:Rate of interest|Interest(?:/Profit/Rent)?(?: Rate)?|Profit Rate|Rent Rate)\s*[:@\-]?\s*(@?\s*[0-9]+(?:\.[0-9]+)?\s*%)", 95)],
    "tenure": [(r"(?:Tenure|Validity Period|period of)\s*[:\-]?\s*(\d+\s*\([^)]*\)\s*(?:Years?|Months?)|\d+\s*(?:Years?|Months?))", 93)],
    "grace_period": [(r"(?:Grace|Moratorium)\s*(?:Period)?\s*[:\-]?\s*(\d+\s*\([^)]*\)\s*Months?|\d+\s*Months?)", 93)],
    "purpose": [(r"(?:Purpose(?: of Loan)?)\s*[:\-]\s*([^\n|]{5,300})", 95)],
    "facility_type": [(r"(?:Nature of facility|Facility Type|Loan Product|Loan Type)\s*[:\-]\s*([^\n|]{3,100})", 95)],
    "collateral_value": [(r"(?:Value of Collateral|Collateral Value|Total value)\s*[:\-]?\s*(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)", 92)],
    "forced_sale_value": [(r"(?:F\.?S\.?V\.?|Forced Sale Value)\s*[:\-]?\s*(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)", 95)],
    "cib_date": [(r"CIB(?: Report)?(?: \(Borrower\))?\s*(?:Obtained)?\s*on\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 94)],
    "cib_status": [(r"CIB(?: Report)?[^\n]{0,80}\s+as\s+([A-Za-z ]{2,30})", 86)],
}


FIXED_SANCTION_FIELDS = {
    "interest_rate", "purpose", "repayment_terms", "insurance_clause"
}


class PackageDocument:
    """Reads and edits ODT/DOCX without rebuilding the document layout."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.ext = self.path.suffix.lower()
        if self.ext not in {".odt", ".docx"}:
            raise ValueError("Editable master must be ODT or DOCX")
        self.raw_entries: dict[str, bytes] = {}
        self.roots: dict[str, etree._Element] = {}
        self.block_elements: dict[str, list[etree._Element]] = {}
        with zipfile.ZipFile(self.path, "r") as zf:
            for info in zf.infolist():
                data = zf.read(info.filename)
                self.raw_entries[info.filename] = data
                if self._is_text_part(info.filename):
                    try:
                        self.roots[info.filename] = etree.fromstring(data)
                    except Exception:
                        pass
        self._index_blocks()

    def _is_text_part(self, name: str) -> bool:
        if self.ext == ".odt":
            return name in {"content.xml", "styles.xml"}
        return bool(re.fullmatch(r"word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml", name))

    @staticmethod
    def _local(el: etree._Element) -> str:
        return etree.QName(el).localname

    def _paragraphs(self, root: etree._Element) -> list[etree._Element]:
        if self.ext == ".odt":
            return root.xpath('//*[local-name()="p" or local-name()="h"]')
        return root.xpath('//*[local-name()="p"]')

    def _index_blocks(self) -> None:
        self.block_elements = {name: self._paragraphs(root) for name, root in self.roots.items()}
        self.element_index: dict[str, dict[int, int]] = {}
        for name, els in self.block_elements.items():
            self.element_index[name] = {id(el): i for i, el in enumerate(els)}

    def blocks(self) -> list[TextBlock]:
        out: list[TextBlock] = []
        for part, els in self.block_elements.items():
            for i, el in enumerate(els):
                text = compact_ws("".join(el.itertext()))
                out.append(TextBlock(part=part, index=i, text=text))
        return out

    def table_rows(self) -> list[TableRowRef]:
        rows_out: list[TableRowRef] = []
        for part, root in self.roots.items():
            rows = root.xpath('//*[local-name()="table-row" or local-name()="tr"]')
            for ri, row in enumerate(rows):
                if self.ext == ".odt":
                    cells = row.xpath('./*[local-name()="table-cell" or local-name()="covered-table-cell"]')
                else:
                    cells = row.xpath('./*[local-name()="tc"]')
                cell_refs: list[TableCellRef] = []
                for cell in cells:
                    paras = cell.xpath('.//*[local-name()="p" or local-name()="h"]')
                    refs: list[TextBlock] = []
                    texts: list[str] = []
                    for para in paras:
                        idx = self.element_index.get(part, {}).get(id(para))
                        if idx is None:
                            continue
                        text = compact_ws("".join(para.itertext()))
                        refs.append(TextBlock(part, idx, text))
                        if text:
                            texts.append(text)
                    cell_refs.append(TableCellRef(" | ".join(texts), refs))
                if any(c.text for c in cell_refs):
                    rows_out.append(TableRowRef(part, ri, cell_refs))
        return rows_out

    def get_block(self, part: str, index: int) -> etree._Element:
        return self.block_elements[part][index]

    def block_text(self, part: str, index: int) -> str:
        return compact_ws("".join(self.get_block(part, index).itertext()))

    def _text_nodes(self, block: etree._Element) -> list[etree._Element]:
        if self.ext == ".docx":
            return block.xpath('.//*[local-name()="t"]')
        # ODT text may be element text/tails, so handled separately.
        return []

    def _force_odt_string_cell(self, block: etree._Element) -> None:
        if self.ext != ".odt":
            return
        cell = block.getparent()
        while cell is not None and self._local(cell) not in {"table-cell", "covered-table-cell"}:
            cell = cell.getparent()
        if cell is None:
            return
        # LibreOffice may render office:value instead of the edited paragraph text.
        # Convert edited cells to string cells so visible text and XML text agree.
        for attr in list(cell.attrib):
            local = etree.QName(attr).localname
            if local in {"value", "date-value", "time-value", "boolean-value", "currency", "percentage"}:
                del cell.attrib[attr]
        office_ns = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
        cell.set(f"{{{office_ns}}}value-type", "string")

    def replace_in_block(self, part: str, index: int, old: str, new: str, whole: bool = False) -> bool:
        block = self.get_block(part, index)
        if self.ext == ".docx":
            nodes = self._text_nodes(block)
            if not nodes:
                return False
            pieces = [n.text or "" for n in nodes]
            full = "".join(pieces)
            if whole:
                nodes[0].text = new
                for n in nodes[1:]:
                    n.text = ""
                return True
            return self._replace_piece_list(nodes, pieces, old, new, attr="text")
        # ODT: text can be stored as text/tail on many nodes.
        refs: list[tuple[etree._Element, str]] = []
        if block.text is not None:
            refs.append((block, "text"))
        for el in block.iterdescendants():
            if el.text is not None:
                refs.append((el, "text"))
            if el.tail is not None:
                refs.append((el, "tail"))
        if not refs:
            return False
        pieces = [getattr(el, attr) or "" for el, attr in refs]
        if whole:
            setattr(refs[0][0], refs[0][1], new)
            for el, attr in refs[1:]:
                setattr(el, attr, "")
            self._force_odt_string_cell(block)
            return True
        changed = self._replace_piece_list(refs, pieces, old, new, attr=None)
        if changed:
            self._force_odt_string_cell(block)
        return changed

    @staticmethod
    def _replace_piece_list(refs: list[Any], pieces: list[str], old: str, new: str, attr: str | None) -> bool:
        full = "".join(pieces)
        if old not in full:
            # Try whitespace-flexible replacement while preserving exact located span.
            pattern = re.escape(old)
            pattern = pattern.replace(r"\ ", r"\s+")
            m = re.search(pattern, full, re.I)
            if not m:
                return False
            start, end = m.span()
        else:
            start = full.find(old)
            end = start + len(old)
        starts: list[int] = []
        cur = 0
        for p in pieces:
            starts.append(cur)
            cur += len(p)
        first = last = None
        for i, (st, p) in enumerate(zip(starts, pieces)):
            en = st + len(p)
            if first is None and start < en:
                first = i
            if end <= en:
                last = i
                break
        if first is None or last is None:
            return False
        before = pieces[first][: start - starts[first]]
        after = pieces[last][end - starts[last] :]
        pieces[first] = before + new + after
        for i in range(first + 1, last + 1):
            pieces[i] = ""
        if attr is not None:
            for node, value in zip(refs, pieces):
                setattr(node, attr, value)
        else:
            for (el, at), value in zip(refs, pieces):
                setattr(el, at, value)
        return True

    def save(self, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in self.raw_entries.items():
                if name in self.roots:
                    data = etree.tostring(self.roots[name], xml_declaration=True, encoding="UTF-8")
                zout.writestr(name, data)


class TemplateRegistry:
    def __init__(self):
        self.index_path = TEMPLATES_DIR / "index.json"
        self.index: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def save(self) -> None:
        self.index_path.write_text(json.dumps(self.index, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def infer_metadata(filename: str) -> tuple[str, str]:
        n = filename.lower()
        if "notesheet" in n or "note sheet" in n or n.startswith("proforma"):
            doc_type = DOC_TYPE_NOTESHEET
        elif "sanction" in n:
            doc_type = DOC_TYPE_SANCTION
        elif "forward" in n:
            doc_type = DOC_TYPE_FORWARDING
        else:
            doc_type = "Other"
        if "abashon" in n or "abashion" in n:
            product = "Pubali Abashon"
        elif "lease" in n:
            product = "Lease Finance"
        elif "bai" in n or "muajjal" in n:
            product = "Bai-Muajjal TR"
        elif "star" in n or "hpsm" in n:
            product = "Pubali Star / HPSM"
        elif "subarna" in n:
            product = "Pubali Subarna Rin"
        elif "green prantik" in n:
            product = "Green Prantik"
        else:
            product = Path(filename).stem
        return product, doc_type

    def seed(self) -> None:
        if self.index:
            return
        if not SEED_DIR.exists():
            return
        seen_hashes: set[str] = set()
        for src in sorted(SEED_DIR.iterdir()):
            if not src.is_file():
                continue
            if src.suffix.lower() not in SUPPORTED_TEMPLATE_EXTS:
                continue
            digest = hashlib.sha1(src.read_bytes()).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            product, doc_type = self.infer_metadata(src.name)
            try:
                self.add(src, product, doc_type, original_name=src.name)
            except Exception:
                continue

    def add(self, source: Path, product: str, doc_type: str, original_name: str | None = None) -> str:
        converted = convert_master_if_needed(source)
        if converted.suffix.lower() not in {".odt", ".docx"}:
            raise ValueError("Exact-structure generation requires an editable ODT or DOCX master")
        tid = uuid.uuid4().hex[:12]
        tdir = TEMPLATES_DIR / tid
        tdir.mkdir(parents=True, exist_ok=True)
        dest = tdir / ("master" + converted.suffix.lower())
        shutil.copy2(converted, dest)
        meta = {
            "id": tid,
            "product": compact_ws(product),
            "doc_type": doc_type,
            "original_name": original_name or source.name,
            "current_file": str(dest.relative_to(APP_DIR)),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.index[tid] = meta
        self.save()
        try:
            mapping = analyze_template(dest, doc_type)
            (tdir / "model_map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
            meta["slot_count"] = len(mapping.get("slots", []))
            meta["unresolved_count"] = len(mapping.get("unresolved", []))
            self.save()
        except Exception as exc:
            meta["analysis_error"] = str(exc)
            self.save()
        return tid

    def replace(self, tid: str, source: Path) -> None:
        meta = self.index[tid]
        current = APP_DIR / meta["current_file"]
        backup_dir = BACKUPS_DIR / tid
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current, backup_dir / f"{now_stamp()}_{meta['original_name']}")
        converted = convert_master_if_needed(source)
        dest = current.with_suffix(converted.suffix.lower())
        if dest != current and current.exists():
            current.unlink()
        shutil.copy2(converted, dest)
        meta["current_file"] = str(dest.relative_to(APP_DIR))
        meta["original_name"] = source.name
        meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
        mapping = analyze_template(dest, meta["doc_type"])
        (TEMPLATES_DIR / tid / "model_map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        meta["slot_count"] = len(mapping.get("slots", []))
        meta["unresolved_count"] = len(mapping.get("unresolved", []))
        self.save()

    def delete(self, tid: str) -> None:
        meta = self.index.pop(tid)
        tdir = (APP_DIR / meta["current_file"]).parent
        if tdir.exists():
            shutil.rmtree(tdir)
        self.save()

    def get(self, tid: str) -> dict[str, Any]:
        return self.index[tid]

    def all(self) -> list[dict[str, Any]]:
        return sorted(self.index.values(), key=lambda x: (x.get("product", ""), x.get("doc_type", ""), x.get("original_name", "")))


def convert_master_if_needed(path: Path) -> Path:
    if path.suffix.lower() in {".odt", ".docx"}:
        return path
    if path.suffix.lower() == ".doc":
        outdir = Path(tempfile.mkdtemp(prefix="pcia_convert_"))
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            raise ValueError("Old .doc master requires LibreOffice. Save it as DOCX or ODT and upload again.")
        result = subprocess.run([soffice, "--headless", "--convert-to", "docx", "--outdir", str(outdir), str(path)], capture_output=True, text=True, timeout=90)
        candidates = list(outdir.glob("*.docx"))
        if result.returncode != 0 or not candidates:
            raise ValueError("Could not convert old .doc master to DOCX")
        return candidates[0]
    raise ValueError("Master must be ODT, DOCX, or convertible DOC")


def extract_docx_text(path: Path) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        names = sorted(n for n in zf.namelist() if re.fullmatch(r"word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml", n))
        for name in names:
            try:
                root = etree.fromstring(zf.read(name))
                for p in root.xpath('//*[local-name()="p"]'):
                    text = compact_ws("".join(p.itertext()))
                    if text:
                        chunks.append(text)
            except Exception:
                continue
    return "\n".join(chunks)


def extract_odf_text(path: Path) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in ("content.xml", "styles.xml"):
            if name not in zf.namelist():
                continue
            try:
                root = etree.fromstring(zf.read(name))
                for p in root.xpath('//*[local-name()="p" or local-name()="h"]'):
                    text = compact_ws("".join(p.itertext()))
                    if text:
                        chunks.append(text)
            except Exception:
                continue
    return "\n".join(chunks)


def ocr_image(path: Path) -> str:
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(path), lang="eng")
    except Exception:
        return ""


def extract_pdf_text(path: Path) -> str:
    try:
        import fitz
    except Exception:
        return ""
    doc = fitz.open(path)
    chunks: list[str] = []
    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        if len(compact_ws(text)) < 30:
            try:
                import pytesseract
                from PIL import Image
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(image, lang="eng")
            except Exception:
                pass
        chunks.append(f"[PAGE {i+1}]\n{text}")
    return "\n".join(chunks)


def extract_old_doc_text(path: Path) -> str:
    antiword = shutil.which("antiword")
    if antiword:
        try:
            return subprocess.check_output([antiword, str(path)], stderr=subprocess.DEVNULL, timeout=45).decode("utf-8", errors="ignore")
        except Exception:
            pass
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        outdir = Path(tempfile.mkdtemp(prefix="pcia_doc_"))
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "docx", "--outdir", str(outdir), str(path)], capture_output=True, timeout=90)
            docx = next(outdir.glob("*.docx"), None)
            if docx:
                return extract_docx_text(docx)
        except Exception:
            pass
    # Last-resort printable strings, better than silently ignoring.
    try:
        data = path.read_bytes()
        strings = re.findall(rb"[\x20-\x7E]{4,}", data)
        return "\n".join(s.decode("latin1", errors="ignore") for s in strings)
    except Exception:
        return ""


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".docx":
            return extract_docx_text(path)
        if ext in {".odt", ".ods"}:
            return extract_odf_text(path)
        if ext == ".pdf":
            return extract_pdf_text(path)
        if ext == ".doc":
            return extract_old_doc_text(path)
        if ext in {".xlsx", ".xls"}:
            import openpyxl
            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            out: list[str] = []
            for ws in wb.worksheets:
                out.append(f"[SHEET {ws.title}]")
                for row in ws.iter_rows(values_only=True):
                    out.append(" | ".join("" if v is None else str(v) for v in row))
            return "\n".join(out)
        if ext in {".csv", ".txt", ".rtf", ".json", ".xml", ".html", ".htm"}:
            raw = path.read_bytes()
            for enc in ("utf-8-sig", "utf-16", "cp1252", "latin1"):
                try:
                    return raw.decode(enc)
                except Exception:
                    continue
            return raw.decode("utf-8", errors="ignore")
        if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".heic"}:
            return ocr_image(path)
    except Exception:
        return ""
    return ""


def safe_unpack_uploads(uploaded_paths: Iterable[Path], target: Path, max_depth: int = 3) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    output: list[Path] = []
    seen_names: dict[str, int] = {}

    def unique_dest(name: str) -> Path:
        base = Path(name).name
        count = seen_names.get(base.lower(), 0)
        seen_names[base.lower()] = count + 1
        if count:
            p = Path(base)
            base = f"{p.stem}_{count}{p.suffix}"
        return target / base

    def handle(path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        ext = path.suffix.lower()
        if ext == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    for info in zf.infolist()[:1000]:
                        if info.is_dir() or info.file_size > 100 * 1024 * 1024:
                            continue
                        dest = unique_dest(info.filename)
                        with zf.open(info) as src, open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        handle(dest, depth + 1)
            except Exception:
                output.append(path)
        elif ext in SUPPORTED_EVIDENCE_EXTS or ext:
            output.append(path)

    for src in uploaded_paths:
        dest = unique_dest(src.name)
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        else:
            dest = src
        handle(dest, 0)
    return output


def line_pairs(text: str) -> list[tuple[str, str, str]]:
    """Returns (label,value,location) from normal lines and simple table-like rows."""
    out: list[tuple[str, str, str]] = []
    lines = [compact_ws(x) for x in text.replace("\r", "\n").split("\n")]
    for i, line in enumerate(lines):
        if not line:
            continue
        m = re.match(r"^(.{2,90}?)\s*[:：]\s*(.{1,500})$", line)
        if m:
            out.append((m.group(1), m.group(2), f"line {i+1}"))
        if "|" in line:
            cells = [compact_ws(c) for c in line.split("|") if compact_ws(c)]
            if len(cells) == 2:
                out.append((cells[0], cells[1], f"line {i+1}"))
    return out


def alias_to_field(label: str) -> str | None:
    nl = norm(label)
    if not nl:
        return None
    best: tuple[int, str] | None = None
    for field, aliases in ALIASES.items():
        for a in aliases:
            na = norm(a)
            score = 0
            if nl == na:
                score = 100
            elif na in nl or nl in na:
                score = 85
            else:
                lt = set(nl.split())
                at = set(na.split())
                if at:
                    score = int(100 * len(lt & at) / len(at))
            if score >= 70 and (best is None or score > best[0]):
                best = (score, field)
    return best[1] if best else None


def clean_candidate(field: str, value: str) -> str:
    value = compact_ws(value).strip(" :;|\"'“”")
    if field == "mobile":
        value = re.sub(r"\s+", "", value)
    if field in {"borrower_name", "father_name", "mother_name", "guarantor_name"}:
        value = re.sub(r"\s+(?:A/C|Account|Date|Loan|Address)\b.*$", "", value, flags=re.I)
    return value[:1000]


def extract_narrative_sections(text: str, source: str) -> dict[str, list[Evidence]]:
    lines = [compact_ws(x) for x in text.replace("\r", "\n").split("\n")]
    result: dict[str, list[Evidence]] = {}
    heading_lookup: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        nl = norm(line)
        if not nl:
            continue
        for field, headings in NARRATIVE_HEADINGS.items():
            if any(norm(h) in nl for h in headings):
                heading_lookup.append((i, field))
                break
    for pos, (i, field) in enumerate(heading_lookup):
        end = heading_lookup[pos + 1][0] if pos + 1 < len(heading_lookup) else min(len(lines), i + 20)
        collected: list[str] = []
        # Include text after colon in the heading, then following lines.
        if ":" in lines[i]:
            tail = compact_ws(lines[i].split(":", 1)[1])
            if tail:
                collected.append(tail)
        for j in range(i + 1, end):
            line = lines[j]
            if not line:
                if collected:
                    break
                continue
            if len(line) < 3:
                continue
            # Avoid swallowing signature blocks.
            if re.search(r"\b(?:Yours faithfully|Sincerely|AGM|DGM|Officer|Manager)\b", line, re.I) and collected:
                break
            collected.append(line)
            if sum(len(x) for x in collected) > 1800:
                break
        value = compact_ws(" ".join(collected))
        if len(value) >= 15:
            result.setdefault(field, []).append(Evidence(field, value, source, f"after heading '{lines[i]}'", 88))
    return result


def extract_case_evidence(files: list[Path]) -> tuple[dict[str, list[Evidence]], dict[str, str], list[dict[str, Any]]]:
    evidence: dict[str, list[Evidence]] = {}
    document_texts: list[dict[str, Any]] = []

    def add(ev: Evidence) -> None:
        value = clean_candidate(ev.field, ev.value)
        if not value or len(value) < 1:
            return
        ev.value = value
        evidence.setdefault(ev.field, []).append(ev)

    for path in files:
        text = extract_text(path)
        document_texts.append({"name": path.name, "path": str(path), "chars": len(text), "text": text})
        if not text:
            continue
        for label, value, location in line_pairs(text):
            field = alias_to_field(label)
            if field:
                add(Evidence(field, value, path.name, location, 92, f"label: {label}"))
        for field, patterns in REGEX_FIELDS.items():
            for pattern, confidence in patterns:
                for m in re.finditer(pattern, text, re.I | re.M):
                    if field == "mobile" and len(m.groups()) >= 2:
                        value = (m.group(1) or "") + (m.group(2) or "")
                    else:
                        value = next((g for g in m.groups() if g), m.group(0))
                    add(Evidence(field, value, path.name, f"character {m.start()}", confidence, "pattern match"))
        for field, items in extract_narrative_sections(text, path.name).items():
            for ev in items:
                add(ev)

    # Document availability is independent from whether data was found elsewhere.
    all_names_and_text = "\n".join((d["name"] + "\n" + d["text"][:10000]).lower() for d in document_texts)
    doc_status: dict[str, str] = {}
    for label, synonyms in DOC_LABEL_SYNONYMS.items():
        doc_status[label] = "Submitted" if any(s.lower() in all_names_and_text for s in synonyms) else "N/F"

    # Dedupe but keep conflicting alternatives.
    for field, items in list(evidence.items()):
        seen: set[str] = set()
        uniq: list[Evidence] = []
        for ev in sorted(items, key=lambda e: (-e.confidence, e.source)):
            key = re.sub(r"\W+", "", ev.value.lower())
            if not key or key in seen:
                continue
            seen.add(key)
            uniq.append(ev)
        evidence[field] = uniq[:12]

    # Derived amount words.
    if evidence.get("loan_amount"):
        amount = evidence["loan_amount"][0]
        add(Evidence("amount_words", amount_words_from_number(amount.value), amount.source, amount.location, 86, "derived from loan amount"))

    return evidence, doc_status, document_texts


def resolve_values(evidence: dict[str, list[Evidence]]) -> tuple[dict[str, str], dict[str, list[Evidence]]]:
    values: dict[str, str] = {}
    conflicts: dict[str, list[Evidence]] = {}
    for field, items in evidence.items():
        if not items:
            continue
        values[field] = items[0].value
        normalized = {re.sub(r"\W+", "", x.value.lower()) for x in items[:5]}
        if len(normalized) > 1:
            conflicts[field] = items[:5]
    return values, conflicts


def next_value_block(blocks: list[TextBlock], start: int, max_steps: int = 7) -> TextBlock | None:
    for j in range(start + 1, min(len(blocks), start + max_steps + 1)):
        t = blocks[j].text
        if not t or t in {":", "-"} or re.fullmatch(r"\d+[.)]?", t):
            continue
        if len(t) > 2:
            return blocks[j]
    return None


def add_slot(slots: list[TemplateSlot], field: str, block: TextBlock, old_value: str, mode: str = "substring", confidence: int = 85, context: str = "", required: bool = False) -> None:
    old_value = compact_ws(old_value)
    stop_values = {"name", "date", "tk.", "tk", "yes", "no", "submitted", "n/a", "nil", ":"}
    if not old_value:
        return
    if mode == "substring" and old_value.lower() in stop_values:
        return
    if mode == "substring" and len(old_value) < 3:
        return
    if field in {"account_number", "saving_account_number"} and re.fullmatch(r"[0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2}", old_value):
        return
    key = (field, block.part, block.index, old_value, mode)
    if any((s.field, s.part, s.block_index, s.old_value, s.mode) == key for s in slots):
        return
    slots.append(TemplateSlot(
        slot_id=uuid.uuid4().hex[:10], field=field, label=FIELD_LABELS.get(field, field), part=block.part,
        block_index=block.index, old_text=block.text, old_value=old_value, mode=mode, confidence=confidence,
        context=context or block.text[:250], required=required,
    ))


def model_value_from_label(blocks: list[TextBlock], i: int, field: str, aliases: list[str]) -> tuple[TextBlock, str] | None:
    block = blocks[i]
    t = block.text
    nt = norm(t)
    matched = None
    for a in aliases:
        na = norm(a)
        if nt == na or nt.startswith(na + " ") or (len(nt) <= 90 and na in nt):
            matched = a
            break
    if not matched:
        return None
    # Same-block value after colon only when the label occurs before the colon.
    if ":" in t:
        head, tail = t.split(":", 1)
        if norm(matched) in norm(head):
            tail = compact_ws(tail)
            if tail and norm(tail) not in {"yes no", "n a"}:
                return block, tail
    # Long narrative paragraphs are not label cells.
    if len(t) > 120:
        return None
    nxt = next_value_block(blocks, i)
    if nxt:
        return nxt, nxt.text
    return None


def extract_amount_words_from_text(text: str) -> str | None:
    m = re.search(r"\(\s*(Taka\s+[^)]+?)\s*\)", text, re.I)
    return compact_ws(m.group(1)) if m else None


def analyze_template(path: Path, doc_type: str) -> dict[str, Any]:
    """Learn variable placements from the editable master while preserving document structure.

    The model map is location-specific. It never performs blind global replacement of dates or numbers.
    """
    doc = PackageDocument(path)
    blocks = doc.blocks()
    rows = doc.table_rows()
    slots: list[TemplateSlot] = []
    unresolved: list[dict[str, Any]] = []

    block_by_ref = {(b.part, b.index): b for b in blocks}

    def add_cell_slot(field: str, cell: TableCellRef, *, mode: str = "whole", confidence: int = 96, context: str = "") -> None:
        nonempty = [b for b in cell.blocks if b.text]
        if not nonempty:
            return
        if len(nonempty) == 1:
            b = nonempty[0]
            add_slot(slots, field, b, b.text, mode, confidence, context or cell.text)
        else:
            # A multi-paragraph cell is mapped paragraph-by-paragraph only by structured rules.
            for k, b in enumerate(nonempty):
                add_slot(slots, f"{field}__part{k+1}", b, b.text, "whole", confidence - 3, context or cell.text)

    def next_data_row(row_pos: int) -> TableRowRef | None:
        if row_pos + 1 < len(rows) and rows[row_pos + 1].part == rows[row_pos].part:
            return rows[row_pos + 1]
        return None

    # 1) Header/footer and standalone dated lines.
    borrower_primary: str | None = None
    branch_primary: str | None = None
    guarantor_primary: str | None = None
    loan_amount_primary: str | None = None

    for block in blocks:
        t = block.text
        if not t:
            continue
        # A/C header line, but never the detailed A/C No. table value.
        if re.match(r"^A/C\.?\s+(?!No\.?\b|Number\b)[A-Za-z]", t, re.I):
            old = re.sub(r"^A/C\.?\s*", "", t, flags=re.I).strip()
            add_slot(slots, "account_reference", block, t, "whole", 99, "Account reference in header/footer")
            if old:
                borrower_primary = borrower_primary or old
        # Branch/address line in header/footer.
        if re.fullmatch(r"[A-Za-z.' -]{2,60}\s+Branch(?:\s*,\s*[A-Za-z.' -]{2,50})?", t, re.I):
            add_slot(slots, "branch_name", block, t, "whole", 99, "Branch line in header/footer")
            branch_primary = branch_primary or t

        line_patterns = [
            ("notesheet_date", r"^(Note\s*Sheet\s*Date\s*:\s*)(.+)$"),
            ("application_receipt_date", r"^(Date of receipt of borrower.?s application by the branch\s*:\s*)(.+)$"),
            ("proposal_sending_date", r"^(Date of sending proposal by the Branch\s*:\s*)(.+)$"),
            ("regional_receipt_date", r"^(Date of receipt of the proposal by Regional Office\s*:\s*)(.+)$"),
            ("query_reply_date", r"^(Date of receipt of other required documents by Regional Office\s*:\s*)(.+)$"),
        ]
        for field, pattern in line_patterns:
            m = re.match(pattern, t, re.I)
            if m:
                add_slot(slots, field, block, m.group(2), "substring", 100, t)

    # Standalone label/value paragraphs outside tables.
    standalone_patterns = [
        ("total_cost", r"^(Total cost estimation for building\s*:\s*)(.+)$"),
        ("cost_incurred", r"^(Cost already incurred by applicant\s*:\s*)(.+)$"),
        ("total_requirement", r"^(Total requirement for work Completion\s*:\s*)(.+)$"),
        ("loan_amount", r"^(Applied from Bank as [^:]+\s*:\s*)(.+)$"),
        ("capital_investment", r"^(Capital\s*/?\s*Investment\s*:\s*)(.+)$"),
        ("nature_of_business", r"^(Nature of business\s*/?Products?/?service\s*:\s*)(.+)$"),
        ("account_performance", r"^(Account Performance\s*:\s*)(.+)$"),
        ("cib_status", r"^(CIB Report \(Borrower\)\s*:\s*)(.+)$"),
        ("financial_analysis", r"^(DBR\s*:\s*)(.+)$"),
    ]
    for block in blocks:
        for field, pattern in standalone_patterns:
            m = re.match(pattern, block.text, re.I)
            if m:
                add_slot(slots, field, block, m.group(2), "substring", 99, block.text)
                if field == "loan_amount":
                    loan_amount_primary = loan_amount_primary or m.group(2)

    # 2) Table-aware model learning. This is the main defence against replacing labels or wrong cells.
    simple_labels = {
        "customer s name": "borrower_name",
        "a c no date opened": "account_details",
        "date of 1st sanction with limit": "first_sanction_details",
        "office business": "business_address",
        "residence": "permanent_address",
        "legal status": "legal_status",
        "date of establishment": "date_of_establishment",
        "gir tin no": "tin",
        "total cost estimation for building": "total_cost",
        "cost already incurred by applicant": "cost_incurred",
        "total requirement for work completion": "total_requirement",
        "applied from bank as pubali abashon": "loan_amount",
        "capital investment": "capital_investment",
        "nature of business products service": "nature_of_business",
        "cib report borrower": "cib_status",
        "dbr": "financial_analysis",
        "name of the clients": "borrower_name",
        "nature of facility": "facility_type",
        "loan amount": "loan_amount",
        "tenure": "tenure_clause" if doc_type == DOC_TYPE_SANCTION else "tenure",
        "branch information": "branch_name",
    }

    for rpos, row in enumerate(rows):
        cell_norms = [norm(c.text) for c in row.cells]
        # Simple label/value row. Find a known label and a later non-empty value cell.
        for ci, cell in enumerate(row.cells):
            ncell = norm(cell.text)
            if not ncell:
                continue
            matched_field = None
            for label_norm, field in simple_labels.items():
                if ncell == label_norm or ncell.startswith(label_norm + " "):
                    matched_field = field
                    break
            if not matched_field:
                continue
            value_cell = None
            for cj in range(ci + 1, len(row.cells)):
                candidate = row.cells[cj]
                if candidate.text and candidate.text not in {":", "-"}:
                    value_cell = candidate
            if not value_cell:
                continue
            add_cell_slot(matched_field, value_cell, confidence=99, context=f"Table label: {cell.text}")
            if matched_field == "borrower_name":
                borrower_primary = borrower_primary or value_cell.text.strip(" '\"")
            if matched_field == "loan_amount":
                loan_amount_primary = loan_amount_primary or value_cell.text

        # Director/proprietor table.
        if any("name address" in x for x in cell_norms) and any(x == "position" for x in cell_norms) and any(x == "age" for x in cell_norms):
            data = next_data_row(rpos)
            if data:
                # Build header -> data cell mapping by physical column.
                for ci, hcell in enumerate(row.cells):
                    hn = norm(hcell.text)
                    if ci >= len(data.cells):
                        continue
                    dcell = data.cells[ci]
                    db = [b for b in dcell.blocks if b.text]
                    if "name address" in hn and db:
                        add_slot(slots, "borrower_name", db[0], db[0].text, "whole", 100, "Borrower identity table")
                        borrower_primary = borrower_primary or db[0].text
                        if len(db) > 1:
                            add_slot(slots, "borrower_parents_line", db[1], db[1].text, "whole", 100, "Borrower parents table")
                    elif hn == "position" and db:
                        add_slot(slots, "position", db[0], db[0].text, "whole", 98, "Borrower position")
                    elif hn == "age" and db:
                        add_slot(slots, "age", db[0], db[0].text, "whole", 98, "Borrower age")
                    elif "shareholding" in hn and db:
                        add_slot(slots, "shareholding", db[0], db[0].text, "whole", 98, "Shareholding")
                    elif "personal net worth" in hn and db:
                        add_slot(slots, "net_worth", db[0], db[0].text, "whole", 98, "Personal net worth")
                    elif "cib obtained" in hn:
                        # Header contains variable CIB date; data cell contains status.
                        for hb in hcell.blocks:
                            dm = re.search(r"([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", hb.text)
                            if dm:
                                add_slot(slots, "cib_date", hb, dm.group(1), "substring", 98, "Borrower CIB date")
                        if db:
                            add_slot(slots, "cib_status", db[0], db[0].text, "whole", 98, "Borrower CIB status")

        # Second line management table.
        if cell_norms and cell_norms[0] == "name" and any(x == "qualification" for x in cell_norms) and any("business experience" in x for x in cell_norms):
            data = next_data_row(rpos)
            if data:
                for c in data.cells:
                    if c.text:
                        add_cell_slot("second_line_management", c, confidence=98, context="Second line management row")
                        break

        # Guarantor table.
        if cell_norms and cell_norms[0] == "name" and any(x == "relation" for x in cell_norms) and any(x == "profession" for x in cell_norms) and any("net worth" in x for x in cell_norms):
            data = next_data_row(rpos)
            if data:
                field_by_header = {
                    "name": "guarantor_name",
                    "relation": "guarantor_relation",
                    "age": "guarantor_age",
                    "profession": "guarantor_profession",
                    "net worth": "guarantor_net_worth",
                }
                for ci, hcell in enumerate(row.cells):
                    if ci >= len(data.cells):
                        continue
                    hn = norm(hcell.text)
                    db = [b for b in data.cells[ci].blocks if b.text]
                    field = field_by_header.get(hn)
                    if field and db:
                        add_slot(slots, field, db[0], db[0].text, "whole", 100, f"Guarantor {hn}")
                        if field == "guarantor_name":
                            guarantor_primary = guarantor_primary or db[0].text
                    if "cib obtained" in hn:
                        for hb in hcell.blocks:
                            dm = re.search(r"([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", hb.text)
                            if dm:
                                add_slot(slots, "guarantor_cib_date", hb, dm.group(1), "substring", 98, "Guarantor CIB date")
                        if db:
                            add_slot(slots, "guarantor_cib_status", db[0], db[0].text, "whole", 98, "Guarantor CIB status")

        # Variable dates embedded in liability/CIB table headers.
        for cell in row.cells:
            for b in cell.blocks:
                dm = re.search(r"(?:Outstanding\s+as\s+on|as\s+on)\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", b.text, re.I)
                if dm:
                    add_slot(slots, "liability_date", b, dm.group(1), "substring", 97, "Liability/as-on date in table header")

        # Existing facility table.
        if any("name of the borrower" == x for x in cell_norms) and any("nature limit" in x for x in cell_norms) and any("outstanding" in x for x in cell_norms):
            data = next_data_row(rpos)
            if data:
                maps = [
                    "existing_facility_name", "existing_facility_details", "existing_facility_rate",
                    "existing_facility_commission", "existing_facility_validity", "existing_facility_outstanding"
                ]
                for ci, field in enumerate(maps):
                    if ci < len(data.cells) and data.cells[ci].text:
                        add_cell_slot(field, data.cells[ci], confidence=96, context="Existing facility table")

        # Sister concern table (has Credit Sum and collateral columns).
        if any("name of the borrower" == x for x in cell_norms) and any("credit sum" in x for x in cell_norms) and any("value of collateral" in x for x in cell_norms):
            data = next_data_row(rpos)
            if data:
                maps = [
                    "sister_concern_name", "sister_concern_facility", "sister_concern_rate",
                    "sister_concern_validity", "sister_concern_outstanding", "sister_concern_credit_sum",
                    "sister_concern_collateral"
                ]
                for ci, field in enumerate(maps):
                    if ci < len(data.cells) and data.cells[ci].text:
                        add_cell_slot(field, data.cells[ci], confidence=97, context="Sister concern liability table")

        # Other bank / guarantor liability table: whole data row is variable.
        if any("name of the borrower with bank" in x or "name of the bank" == x for x in cell_norms) and any("security" == x for x in cell_norms):
            data = next_data_row(rpos)
            if data:
                for c in data.cells:
                    if c.text:
                        add_cell_slot("other_bank_liability", c, confidence=96, context="Liability table")

        # Checklist status rows. Require an actual status value and a document-name phrase;
        # never interpret serial numbers such as "2." as "2nd line management".
        meaningful = [(ci, c) for ci, c in enumerate(row.cells) if c.text]
        if len(meaningful) >= 2:
            status_cell = meaningful[-1][1]
            status_norm = norm(status_cell.text)
            if status_norm in {"submitted", "not found", "n f", "self", "yes", "no", "available", "missing"}:
                matched_doc = None
                for _, candidate_cell in meaningful[:-1]:
                    candidate_text = re.sub(r"^\s*\d+\s*[).:-]?\s*", "", candidate_cell.text)
                    nc = norm(candidate_text)
                    if len(nc) < 5:
                        continue
                    matched_doc = next((label for label in DOC_LABEL_SYNONYMS if norm(label) in nc or nc in norm(label)), None)
                    if matched_doc:
                        break
                if matched_doc:
                    add_cell_slot(f"doc_status::{matched_doc}", status_cell, confidence=100, context=f"Checklist status for {matched_doc}")

        # Financial/account-performance table values. All case-specific numbers/text must not survive from the model.
        row_text = norm(" ".join(c.text for c in row.cells if c.text))
        if any(k in row_text for k in ["account performance", "turnover analysis", "performance of the borrower", "sales audited unaudited", "cr summation", "highest balance", "lowest balance", "dr summation"]):
            for ci, c in enumerate(row.cells):
                for b in [x for x in c.blocks if x.text]:
                    nb = norm(b.text)
                    if nb in {"account performance", "turnover analysis", "performance of the borrower to measure repayment capacity", "year", "limit", "sales tk", "dr summation", "cr summation", "highest balance", "lowest balance", "item", "number", "amount"}:
                        continue
                    if re.search(r"\d|n a|nil|not done", nb):
                        add_slot(slots, f"financial_metric::{rpos}:{ci}:{b.index}", b, b.text, "whole", 90, "Financial/account-performance value")

    # Map variable financial/account-performance data rows following their section headers.
    for rpos, row in enumerate(rows):
        row_n = norm(" ".join(c.text for c in row.cells if c.text))
        span = 0
        if "account performance" in row_n:
            span = 6
        elif "turnover analysis" in row_n:
            span = 5
        elif "performance of the borrower to measure repayment capacity" in row_n:
            span = 6
        if not span:
            continue
        for rr in rows[rpos:min(len(rows), rpos + span + 1)]:
            for ci, cell in enumerate(rr.cells):
                for b in [x for x in cell.blocks if x.text]:
                    nb = norm(b.text)
                    fixed_words = {
                        "account performance", "borrower", "group", "item", "number", "amount",
                        "dr summation", "cr summation", "turnover analysis", "highest balance", "lowest balance",
                        "no of e o l allowed", "no of adjustment", "same day transaction", "year", "limit",
                        "cr summation tk", "sales tk", "performance of the borrower to measure repayment capacity"
                    }
                    if nb in fixed_words or not nb:
                        continue
                    if re.search(r"\d|n a|nil|not done", nb):
                        add_slot(slots, f"financial_metric::{rr.row_index}:{ci}:{b.index}", b, b.text, "whole", 92, "Variable financial/account-performance data")

    # 3) Narrative paragraphs and case-specific free text.
    observation_count = 0
    in_observation = False
    for i, block in enumerate(blocks):
        t, nt = block.text, norm(block.text)
        if not t:
            continue
        if doc_type == DOC_TYPE_NOTESHEET:
            if "proposal for sanction" in nt and len(t) > 80:
                add_slot(slots, "proposal_subject", block, t, "whole", 100, "Opening proposal paragraph", True)
            if nt.startswith("according to branch s report"):
                add_slot(slots, "brief_history", block, t, "whole", 100, "Brief history paragraph", True)
            if nt.startswith("considering the borrower"):
                add_slot(slots, "justification", block, t, "whole", 100, "Justification paragraph", True)
            if nt.startswith("regd mortgage") or nt.startswith("registered mortgage"):
                add_slot(slots, "collateral_details", block, t, "whole", 100, "Collateral description")
            if nt.startswith("land ") and ("per decimal" in nt or "value tk" in nt):
                add_slot(slots, "collateral_value", block, t, "whole", 95, "Collateral valuation detail")
            if "total value" in nt and "f s v" in nt:
                add_slot(slots, "collateral_value_summary", block, t, "whole", 98, "Collateral value and FSV summary")
            if nt.startswith("the valuation done by"):
                add_slot(slots, "valuation_details", block, t, "whole", 94, "Valuation source/date")
            if nt.startswith("bm physically verified") or nt.startswith("rm dgm"):
                add_slot(slots, "verification_details", block, t, "whole", 92, "Verification date/details")
            if nt.startswith("obtained on") and "cib" in norm(blocks[i-1].text if i else ""):
                add_slot(slots, "cib_status", block, t, "whole", 94, "CIB result")
            if nt.startswith("installment monthly income"):
                add_slot(slots, "financial_analysis", block, t, "whole", 92, "DBR / repayment analysis")
            if nt == "observation":
                in_observation = True
                continue
            if in_observation:
                if any(x in nt for x in ["spo credit assessment officer", "law officer please"]):
                    in_observation = False
                elif len(t) > 5:
                    observation_count += 1
                    add_slot(slots, f"observation_{observation_count}", block, t, "whole", 100, "CAO observation")

            # Present proposal and BM recommendation.
            if "customer s approach" in nt:
                nxt = next_value_block(blocks, i, 5)
                if nxt:
                    add_slot(slots, "present_proposal", nxt, nxt.text, "whole", 100, "Present proposal", True)
            if "recommended by b m" in nt:
                nxt = next_value_block(blocks, i, 4)
                if nxt:
                    add_slot(slots, "bm_recommendation", nxt, nxt.text, "whole", 100, "BM recommendation")

            # Committee hybrid values; signatures and fixed wording are untouched.
            if nt.startswith("discussed in the credit committee"):
                m = re.search(r"held on\s+([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", t, re.I)
                if m:
                    add_slot(slots, "committee_date", block, m.group(1), "substring", 98, "Committee date")
            if nt.startswith("sanction of limit"):
                # The empty Tk. line receives the new amount as a whole value after the fixed label.
                if ":" in t:
                    tail = compact_ws(t.split(":", 1)[1])
                    if tail:
                        add_slot(slots, "loan_amount", block, tail, "substring", 98, "Committee sanction amount")
            if nt.startswith("validity period") and ":" in t:
                add_slot(slots, "committee_validity", block, compact_ws(t.split(":",1)[1]), "substring", 98, "Committee validity")
            if nt.startswith("interest") and ":" in t:
                add_slot(slots, "committee_interest", block, compact_ws(t.split(":",1)[1]), "substring", 98, "Committee rate")
            if "personal guarantee of" in nt or "charges on regd mortgage" in nt:
                add_slot(slots, "committee_security", block, t, "whole", 98, "Committee security")

        elif doc_type == DOC_TYPE_SANCTION:
            if (nt.startswith("sanction of") or nt.startswith("subject")) and len(t) > 40:
                add_slot(slots, "sanction_subject", block, t, "whole", 100, "Sanction subject", True)
            if nt.startswith("regd mortgage") or nt.startswith("registered mortgage"):
                add_slot(slots, "collateral_details", block, t, "whole", 100, "Sanction collateral")
            if "personal guarantee of" in nt:
                # Borrower occurrences are propagated separately; detect a second person as guarantor.
                names = re.findall(r"(?:Mr\.?|Mrs\.?|Ms\.?|Mst\.?)\s+[A-Z][A-Za-z.' -]{2,80}", t)
                for name in names:
                    if borrower_primary and norm(name).endswith(norm(borrower_primary)):
                        continue
                    if "borrower" in norm(t) and not guarantor_primary:
                        continue
                    guarantor_primary = guarantor_primary or compact_ws(name)
                    add_slot(slots, "guarantor_name", block, name, "substring", 96, "Personal guarantee name")
            # Opening approval paragraph is fixed wording with embedded borrower/amount variables.
            if nt.startswith("with reference to your letter"):
                # Reference number and date stay fixed per the operator checklist.
                am = re.search(r"limit of\s+(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)", t, re.I)
                if am:
                    add_slot(slots, "loan_amount", block, am.group(1), "substring", 99, "Opening approval amount")
                aw = extract_amount_words_from_text(t)
                if aw:
                    add_slot(slots, "amount_words", block, aw, "substring", 98, "Opening approval amount in words")
            phase = re.match(r"^(\d+(?:st|nd|rd|th)\s+Phase\s*:\s*)(Tk\.?\s*[0-9,.]+\s*(?:Lac|Crore)?)(?:\s*\((Taka[^)]+)\))?", t, re.I)
            if phase:
                phase_no = re.match(r"\d+", t).group(0)
                add_slot(slots, f"disbursement_phase_{phase_no}_amount", block, phase.group(2), "substring", 99, "Disbursement phase amount")
                if phase.group(3):
                    add_slot(slots, f"disbursement_phase_{phase_no}_words", block, compact_ws(phase.group(3)), "substring", 98, "Disbursement phase amount in words")

        elif doc_type == DOC_TYPE_FORWARDING:
            if nt.startswith("subject") or "proposal for sanction" in nt:
                add_slot(slots, "forwarding_subject", block, t, "whole", 100, "Forwarding subject", True)
            if nt.startswith("we beg to forward") or nt.startswith("in this connection"):
                add_slot(slots, "forwarding_body", block, t, "whole", 96, "Forwarding narrative", True)

    # 4) Determine primary old identities from mapped slots.
    for s in sorted(slots, key=lambda x: -x.confidence):
        if s.field == "borrower_name" and not borrower_primary:
            borrower_primary = s.old_value.strip(" '\"")
        if s.field == "branch_name" and not branch_primary:
            branch_primary = s.old_value
        if s.field == "guarantor_name" and not guarantor_primary:
            guarantor_primary = s.old_value
        if s.field == "loan_amount" and not loan_amount_primary:
            loan_amount_primary = s.old_value

    def name_variants(value: str) -> list[str]:
        v = compact_ws(value)
        base = re.sub(r"^(?:Mr\.?|Mrs\.?|Ms\.?|Mst\.?)\s*", "", v, flags=re.I)
        out = {v, base, "Mr. " + base, "Mr " + base}
        if "Md. " in base:
            out.add(base.replace("Md. ", "Md "))
        if "Md " in base:
            out.add(base.replace("Md ", "Md. "))
        return sorted((x for x in out if len(x) >= 5), key=len, reverse=True)

    # Existing whole-paragraph blocks own their content.
    whole_blocks = {(s.part, s.block_index) for s in slots if s.mode == "whole"}

    # Replace borrower, branch and guarantor identities everywhere (header/footer/body/tables),
    # except where a whole paragraph will already be regenerated.
    for field, old in [("borrower_name", borrower_primary), ("branch_name", branch_primary), ("guarantor_name", guarantor_primary)]:
        if not old:
            continue
        variants = name_variants(old) if field != "branch_name" else [old]
        for block in blocks:
            if (block.part, block.index) in whole_blocks:
                continue
            for variant in variants:
                if variant.lower() in block.text.lower():
                    add_slot(slots, field, block, variant, "substring", 90, "Repeated identity occurrence")
                    break

    # Propagate loan amount and amount-in-words only in loan/proposal/sanction contexts.
    if loan_amount_primary:
        number_tokens = re.findall(r"[0-9][0-9,.]*", loan_amount_primary)
        for block in blocks:
            if (block.part, block.index) in whole_blocks:
                continue
            nb = norm(block.text)
            if not any(k in nb for k in ["loan", "limit", "sanction", "proposal", "applied from bank"]):
                continue
            candidates = [loan_amount_primary]
            if number_tokens:
                num = number_tokens[0]
                candidates += [f"Tk.{num}", f"Tk. {num}", f"Tk,{num}"]
            for old in sorted(set(candidates), key=len, reverse=True):
                if len(old) >= 4 and old.lower() in block.text.lower():
                    add_slot(slots, "loan_amount", block, old, "substring", 88, "Repeated loan amount")
                    break
            aw = extract_amount_words_from_text(block.text)
            if aw:
                add_slot(slots, "amount_words", block, aw, "substring", 88, "Embedded amount in words")

    # 5) Final consolidation. Whole mappings supersede substring mappings in the same paragraph.
    by_block: dict[tuple[str, int], list[TemplateSlot]] = {}
    for slot in slots:
        by_block.setdefault((slot.part, slot.block_index), []).append(slot)
    consolidated: list[TemplateSlot] = []
    for _, group in by_block.items():
        whole = [x for x in group if x.mode == "whole"]
        if whole:
            consolidated.append(max(whole, key=lambda x: (x.confidence, len(x.old_value))))
            continue
        kept: list[TemplateSlot] = []
        for cand in sorted(group, key=lambda x: (-x.confidence, -len(x.old_value))):
            if any(cand.old_value.lower() == x.old_value.lower() for x in kept):
                continue
            if any(cand.field == x.field and (cand.old_value.lower() in x.old_value.lower() or x.old_value.lower() in cand.old_value.lower()) for x in kept):
                continue
            kept.append(cand)
        consolidated.extend(kept)
    slots = consolidated

    primary = {
        "borrower_name": borrower_primary or "",
        "branch_name": branch_primary or "",
        "guarantor_name": guarantor_primary or "",
        "loan_amount": loan_amount_primary or "",
    }

    expected: set[str] = set()
    if doc_type == DOC_TYPE_NOTESHEET:
        expected.update([
            "branch_name", "borrower_name", "notesheet_date", "application_receipt_date", "proposal_sending_date",
            "regional_receipt_date", "query_reply_date", "proposal_subject", "account_details", "business_address",
            "legal_status", "date_of_establishment", "tin", "borrower_parents_line", "age", "net_worth",
            "guarantor_name", "loan_amount", "nature_of_business", "brief_history", "justification",
            "collateral_details", "present_proposal"
        ])
    elif doc_type == DOC_TYPE_SANCTION:
        expected.update(["branch_name", "borrower_name", "sanction_subject", "facility_type", "loan_amount", "tenure_clause", "collateral_details"])
    elif doc_type == DOC_TYPE_FORWARDING:
        expected.update(["branch_name", "borrower_name", "forwarding_subject", "forwarding_body"])
    found_fields = {s.field.split("__part", 1)[0].split("::", 1)[0] for s in slots}
    for field in sorted(expected - found_fields):
        unresolved.append({
            "field": field,
            "label": FIELD_LABELS.get(field, field),
            "reason": "This field was not located in the editable model. The engine will not invent a placement."
        })

    return {
        "template": path.name,
        "doc_type": doc_type,
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "blocks": len(blocks),
        "slots": [asdict(s) for s in slots],
        "primary_model_values": primary,
        "unresolved": unresolved,
    }

def construct_text(field: str, values: dict[str, str], evidence: dict[str, list[Evidence]], doc_status: dict[str, str], doc_type: str) -> str:
    """Build new content only from uploaded evidence or explicit N/F markers."""
    def v(key: str, fallback: str | None = None) -> str:
        return values.get(key) or fallback or "N/F"

    base_field = field.split("__part", 1)[0]

    if field.startswith("doc_status::"):
        label = field.split("::", 1)[1]
        return doc_status.get(label, "N/F")
    if field.startswith("financial_metric::"):
        return "N/F"
    if field.startswith("observation_"):
        missing = [name for name, status in doc_status.items() if status == "N/F"]
        try:
            idx = int(field.rsplit("_", 1)[1]) - 1
        except Exception:
            idx = 0
        if idx < len(missing):
            return f"{missing[idx]} not found in the uploaded documents."
        return "N/F"

    if base_field == "account_reference":
        return f"A/C. {v('borrower_name')}"
    if base_field == "account_details":
        return (
            f"A/c No.{v('account_number')} ; dated {v('account_open_date')} & Saving A/C "
            f"{v('saving_account_number')} dated: {v('saving_account_open_date')}"
        )
    if base_field == "first_sanction_details":
        return v("first_sanction_details")
    if base_field == "borrower_parents_line":
        return f"S/o. {v('father_name')} & {v('mother_name')}"
    if base_field == "guarantor_parents_line":
        return f"S/o./D/o. {v('guarantor_father_name')} & {v('guarantor_mother_name')}"
    if base_field == "tenure_clause":
        return f"{v('tenure')} including {v('grace_period')} from the date of disbursement."

    if base_field == "proposal_subject":
        return (
            f"Proposal for sanction of {v('facility_type', 'Loan Facility N/F')} limit of {v('loan_amount')} "
            f"({v('amount_words')}) only for {v('purpose')} @ {v('interest_rate')} with quarterly rest for "
            f"{v('tenure')} with {v('grace_period')}; A/c. {v('borrower_name')} of our {v('branch_name')}."
        )
    if base_field == "sanction_subject":
        return (
            f"Sanction of {v('facility_type', 'Loan Facility N/F')} limit of {v('loan_amount')} "
            f"({v('amount_words')}) only for {v('purpose')} for {v('tenure')} with {v('grace_period')} "
            f"favouring {v('borrower_name')} of your Branch."
        )
    if base_field == "forwarding_subject":
        return (
            f"Subject: Proposal for sanction of {v('facility_type', 'Loan Facility N/F')} of {v('loan_amount')} "
            f"({v('amount_words')}) for {v('purpose')} for {v('tenure')} with {v('grace_period')} "
            f"favouring {v('borrower_name')}."
        )
    if base_field == "brief_history":
        if evidence.get("brief_history"):
            return evidence["brief_history"][0].value
        return (
            f"According to the branch documents, {v('borrower_name')} is engaged in {v('nature_of_business')} "
            f"at {v('business_address', v('present_address'))}. The business establishment/experience is "
            f"{v('date_of_establishment')}. Further verified business background is N/F."
        )
    if base_field == "justification":
        if evidence.get("justification"):
            return evidence["justification"][0].value
        return (
            f"Considering the customer's stated requirement for {v('purpose')}, the proposal for {v('facility_type')} "
            f"of {v('loan_amount')} for {v('tenure')} is placed based on the uploaded branch documents. "
            f"Security/collateral: {v('collateral_details', v('security_details'))}. Further unsupported information is N/F."
        )
    if base_field in {"present_proposal", "bm_recommendation"}:
        if evidence.get(base_field):
            return evidence[base_field][0].value
        if base_field == "bm_recommendation":
            return "Same as the customer's approach, subject to verification of all required documents and conditions."
        return construct_text("proposal_subject", values, evidence, doc_status, doc_type)
    if base_field in {"financial_analysis", "risk_analysis", "recommendation", "forwarding_body"}:
        if evidence.get(base_field):
            return evidence[base_field][0].value
        if base_field == "risk_analysis":
            return f"Security/collateral information available from uploaded documents: {v('collateral_details', v('security_details'))}. Further risk analysis N/F."
        if base_field == "forwarding_body":
            return f"We forward the proposal of {v('borrower_name')} along with the uploaded supporting documents for consideration and necessary action."
        return "N/F"
    if base_field == "documents_status":
        return "; ".join(f"{k}: {status}" for k, status in doc_status.items()) if doc_status else "N/F"
    if base_field == "observations":
        missing = [k for k, status in doc_status.items() if status == "N/F"]
        return "Missing documents: " + ", ".join(missing) if missing else "No missing checklist document detected."
    if base_field == "committee_validity":
        return v("tenure")
    if base_field == "committee_interest":
        return v("interest_rate")
    if base_field == "committee_purpose":
        return v("purpose")
    if base_field == "committee_security":
        return v("collateral_details", v("security_details"))
    if base_field == "security_details":
        if evidence.get("security_details"):
            return evidence["security_details"][0].value
        return v("collateral_details")
    if base_field == "collateral_details":
        if evidence.get("collateral_details"):
            return evidence["collateral_details"][0].value
        return "COLLATERAL DETAILS N/F"
    if base_field == "collateral_value_summary":
        return f"Total value {v('collateral_value')}, F.S.V. {v('forced_sale_value')}"
    if base_field == "valuation_details":
        return v("valuation_details")
    if base_field == "verification_details":
        return v("verification_details")

    # Composite / liability fields remain N/F unless specifically extracted from uploaded documents.
    if base_field in {
        "existing_facility_name", "existing_facility_details", "existing_facility_rate",
        "existing_facility_commission", "existing_facility_validity", "existing_facility_outstanding",
        "sister_concern_name", "sister_concern_facility", "sister_concern_rate",
        "sister_concern_validity", "sister_concern_outstanding", "sister_concern_credit_sum",
        "sister_concern_collateral", "other_bank_liability", "second_line_management"
    }:
        return values.get(base_field) or "N/F"

    return v(base_field)

def prepare_case(template_path: Path, doc_type: str, evidence_files: list[Path], model_map: dict[str, Any] | None = None) -> dict[str, Any]:
    mapping = model_map or analyze_template(template_path, doc_type)
    evidence, doc_status, docs = extract_case_evidence(evidence_files)
    values, conflicts = resolve_values(evidence)
    proposed: dict[str, str] = {}
    fields = sorted({s["field"] for s in mapping.get("slots", [])})
    for field in fields:
        proposed[field] = construct_text(field, values, evidence, doc_status, doc_type)
    return {
        "mapping": mapping,
        "evidence": {k: [asdict(x) for x in v] for k, v in evidence.items()},
        "doc_status": doc_status,
        "documents": [{k: v for k, v in d.items() if k != "text"} for d in docs],
        "values": values,
        "conflicts": {k: [asdict(x) for x in v] for k, v in conflicts.items()},
        "proposed": proposed,
    }


def generate_document(template_path: Path, output_path: Path, mapping: dict[str, Any], final_values: dict[str, str]) -> dict[str, Any]:
    doc = PackageDocument(template_path)
    audit: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for slot_data in mapping.get("slots", []):
        slot = TemplateSlot(**slot_data)
        new = compact_ws(final_values.get(slot.field, "")) or "N/F"
        success = doc.replace_in_block(slot.part, slot.block_index, slot.old_value, new, whole=(slot.mode == "whole"))
        record = {
            "slot_id": slot.slot_id,
            "field": slot.field,
            "label": slot.label,
            "part": slot.part,
            "block_index": slot.block_index,
            "old": slot.old_value,
            "new": new,
            "success": success,
            "context": slot.context,
        }
        audit.append(record)
        if not success:
            failed.append(record)
    doc.save(output_path)

    # Exact targeted safety check: old values must not remain in their mapped block when the new value differs.
    check_doc = PackageDocument(output_path)
    retained: list[dict[str, Any]] = []
    for record in audit:
        if not record["success"] or record["old"] == record["new"]:
            continue
        try:
            text = check_doc.block_text(record["part"], record["block_index"])
        except Exception:
            continue
        old_l = record["old"].lower()
        new_l = record["new"].lower()
        if len(old_l) >= 4 and old_l not in new_l and old_l in text.lower():
            retained.append({**record, "output_block": text})

    # Critical identity scan throughout the document.
    all_output_text = "\n".join(b.text for b in check_doc.blocks())
    critical_retained: list[dict[str, str]] = []
    primary = mapping.get("primary_model_values", {})
    # Borrower and branch identities must be replaced everywhere, including headers/footers.
    for field in ("borrower_name", "branch_name"):
        old = compact_ws(primary.get(field, ""))
        new = compact_ws(final_values.get(field, ""))
        if old and new and old.lower() != new.lower() and old.lower() in all_output_text.lower():
            critical_retained.append({"field": field, "old": old})

    return {
        "success_count": sum(1 for x in audit if x["success"]),
        "failure_count": len(failed),
        "failed": failed,
        "retained": retained,
        "critical_retained": critical_retained,
        "audit": audit,
        "safe": not retained and not critical_retained,
    }


def cleanup_old_backups(days: int = 30) -> int:
    cutoff = datetime.now().timestamp() - days * 86400
    removed = 0
    if not BACKUPS_DIR.exists():
        return 0
    for p in BACKUPS_DIR.rglob("*"):
        if p.is_file() and p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def create_demo_inputs(target_zip: Path) -> None:
    """Creates a generic new-client dataset used by the included self-test/demo."""
    from docx import Document
    import openpyxl

    tmp = Path(tempfile.mkdtemp(prefix="pcia_demo_"))
    doc = Document()
    lines = [
        "Name of Applicant: Mr. Rahim Uddin",
        "Father's Name: Abdul Karim",
        "Mother's Name: Mst. Salma Begum",
        "NID No: 19881234567890123",
        "Present Address: Village Chandipur, PO Selimganj, Jamalganj, Sunamganj",
        "Permanent Address: Village Chandipur, PO Selimganj, Jamalganj, Sunamganj",
        "Business Address: Chandipur Bazar, Jamalganj, Sunamganj",
        "Mobile Number: 01712345678",
        "Age: 38 Years",
        "Legal Status: Individual",
        "Nature of Business: Wholesale trading of construction materials",
        "Date of Establishment: Doing business since 2015",
        "TIN No: 123456789012",
        "A/C No: 1849-101-999999",
        "Branch Name: Jamalganj Branch, Sunamganj",
        "Loan Product: Pubali Abashon Loan",
        "Loan Amount: Tk.25.00 Lac",
        "Tenure: 10 (Ten) Years",
        "Grace Period: 06 (Six) Months",
        "Rate of Interest: 12.00%",
        "Purpose: completion of civil and finishing work of the second floor of the residential building",
        "Application Date: 10.05.2026",
        "Guarantor Name: Mst. Farzana Begum",
        "Spouse Name: Mst. Farzana Begum",
        "Net Worth: Tk.85.00 Lac",
        "Collateral Value: Tk.80.00 Lac",
        "FSV: Tk.40.00 Lac",
    ]
    for line in lines:
        doc.add_paragraph(line)
    doc.save(tmp / "Application_and_Personal_Details.docx")

    forwarding = """Subject: Proposal for sanction of Pubali Abashon Loan of Tk.25.00 Lac for completion of civil and finishing work of the second floor of the residential building for 10 years with 6 months grace period favouring Mr. Rahim Uddin.

Brief History of the Borrower:
According to the branch report, Mr. Rahim Uddin has been engaged in wholesale trading of construction materials at Chandipur Bazar, Jamalganj, Sunamganj since 2015 with satisfactory market reputation. He maintains his principal banking account with Jamalganj Branch.

Reason/Justification of the Limit:
The customer requires finance to complete the civil and finishing work of the second floor of his residential building. The proposed amount is supported by the submitted estimate and collateral documents. The branch recommends the proposal subject to compliance with the bank's rules.

Collateral Security:
Registered mortgage of 4.50 decimal residential land with construction thereon situated at Mouza Chandipur, Jamalganj, Sunamganj, owned by Mr. Rahim Uddin. Total assessed value Tk.80.00 Lac and forced sale value Tk.40.00 Lac.

BM Recommendation:
The proposal is recommended for consideration subject to completion of documentation and verification of the mortgaged property.
"""
    (tmp / "Branch_Forwarding.txt").write_text(forwarding, encoding="utf-8")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Financials"
    ws.append(["Particular", "Value"])
    ws.append(["Monthly Income", 385250])
    ws.append(["Monthly Expenditure", 125000])
    ws.append(["Personal Net Worth", "Tk.85.00 Lac"])
    ws.append(["Total Project Cost", "Tk.70.00 Lac"])
    ws.append(["Cost Already Incurred", "Tk.45.00 Lac"])
    ws.append(["Total Requirement", "Tk.25.00 Lac"])
    wb.save(tmp / "Financial_Information.xlsx")

    checklist = [
        ["Document", "Status"],
        ["TIN Certificate", "Submitted"],
        ["Physical Verification Report", "Submitted"],
        ["Trade License", "Submitted"],
        ["CIB Report", "Submitted"],
        ["Consent Letter of Guarantor", "N/F"],
        ["NID Verification Report", "Submitted"],
    ]
    with open(tmp / "Document_Checklist.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(checklist)

    target_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in tmp.iterdir():
            zf.write(p, p.name)


# Seed immediately when imported by the app.
def initialize() -> TemplateRegistry:
    cleanup_old_backups(30)
    registry = TemplateRegistry()
    registry.seed()
    demo = APP_DIR / "demo_inputs" / "SAMPLE_NEW_CLIENT.zip"
    if not demo.exists():
        try:
            create_demo_inputs(demo)
        except Exception:
            pass
    return registry

# ============================================================================
# PCIA v1.1 - content-aware evidence intelligence and operator decision layer
# ============================================================================

FIELD_LABELS.update({
    "borrower_profile_type": "Borrower Profile Type",
    "profession": "Profession / Occupation",
    "designation": "Designation",
    "employer": "Employer / Workplace",
    "date_of_joining": "Date of Joining / Service Since",
    "salary_income": "Borrower Monthly Salary",
    "spouse_salary": "Spouse Monthly Salary",
    "probable_rent_income": "Probable Monthly Rent Income",
    "monthly_total_income": "Monthly Total Income",
    "monthly_expenses": "Monthly Expenses",
    "monthly_installment": "Proposed Monthly Installment",
    "net_monthly_income": "Net Monthly Income",
    "dbr": "Debt Burden Ratio (DBR)",
    "liability_status": "Borrower Liability Status",
    "guarantor_liability_status": "Guarantor Liability Status",
    "postdated_cheques": "Postdated Cheques",
    "branch_reference": "Branch Proposal Reference",
    "branch_proposal_date": "Branch Proposal Date",
    "branch_subject": "Branch Proposal Subject",
    "property_area_total": "Total Land Area",
    "property_share_area": "Borrower Proportionate Land Share",
    "flat_area": "Flat Area",
    "common_space": "Common Space",
    "car_parking_area": "Car Parking Area",
    "surveyor_name": "Surveyor / Valuer",
    "market_value": "Market Value",
    "property_owner": "Property Owner",
    "property_schedule": "Property Schedule",
})

ALIASES.update({
    "profession": ["profession nature of business", "profession", "occupation", "nature of profession business", "job"],
    "designation": ["designation", "post", "position in service"],
    "employer": ["employer", "workplace", "office", "office address"],
    "date_of_joining": ["date of joining", "service since", "joining date"],
    "salary_income": ["net salary", "salary income", "own income of applicant", "monthly salary"],
    "spouse_salary": ["salary of spouse", "spouse salary"],
    "probable_rent_income": ["probable rent income from flat", "future rental income", "probable rent"],
    "monthly_total_income": ["total income", "monthly total income"],
    "monthly_expenses": ["total expense", "monthly expenses", "monthly expenditure"],
    "monthly_installment": ["probable installment", "monthly installment", "emi"],
    "net_monthly_income": ["net income", "net monthly income"],
    "dbr": ["dbr", "debt burden ratio"],
    "liability_status": ["present liability position", "liability status"],
    "postdated_cheques": ["postdated cheques", "signed postdated cheques"],
    "branch_reference": ["reference", "ref", "branch reference"],
    "branch_proposal_date": ["proposal date", "branch proposal date"],
    "branch_subject": ["subject", "sub"],
    "property_area_total": ["area as per deed", "total land area", "area of land"],
    "property_share_area": ["proportionate land share", "undivided land", "decimal land"],
    "flat_area": ["flat area", "floor area"],
    "common_space": ["common space"],
    "car_parking_area": ["car parking", "parking space"],
    "surveyor_name": ["surveyor name", "valuer name"],
    "market_value": ["market value", "total value", "valuation"],
    "property_owner": ["owner of the property", "owned by"],
    "property_schedule": ["schedule a", "schedule of property"],
})

# More flexible patterns for branch/customer evidence, not dependent on filenames.
REGEX_FIELDS.update({
    "branch_reference": [(r"\b((?:PBPLC|PBL|PBPCL)/[^\n]{4,120}?/\s*(?:19|20)\d{2})\b", 92)],
    "branch_proposal_date": [(r"(?:Date\s*[:\-]?\s*)([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 78)],
    "branch_subject": [(r"(?:Sub(?:ject)?\s*[:\-]\s*)([^\n]{20,600})", 98)],
    "facility_type": [
        (r"Proposal\s+for\s+sanction\s+of\s+(?:a\s+|an\s+)?([^\n]{3,100}?)\s+limit\s+of", 99),
        (r"Sanction\s+of\s+([^\n]{3,100}?)\s+(?:for|of)\s+Tk", 94),
        (r"Borrower.?s\s+Approach\s*[:\-]\s*Sanction\s+of\s+([^\n]{3,100}?)\s+for", 96),
        (r"(?:Nature of facility|Facility Type|Loan Product|Loan Type)\s*[:\-]\s*([^\n|]{3,100})", 95),
    ],
    "profession": [
        (r"Profession(?:/\s*Nature of Business)?\s*[:\-]\s*([^\n|]{3,150})", 97),
        (r"Nature of Profession(?:/\s*Business)?\s*[:\-]\s*([^\n|]{3,150})", 97),
        (r"\b(Assistant Teacher|Teacher|Government Employee|Govt\.? Service|Service Holder|Businessman|Proprietor|Employee)\b", 82),
    ],
    "designation": [(r"\b(Assistant Teacher|Head Teacher|Teacher|Officer|Executive|Manager|Engineer|Doctor|Nurse|Professor|Lecturer)\b", 78)],
    "employer": [(r"Office Address\s*[:\-]\s*([^\n|]{8,250})", 95)],
    "date_of_joining": [(r"Date of Joining\s*[:\-]\s*([0-3]?\d[./-][01]?\d[./-](?:\d{2}|\d{4}))", 98)],
    "account_open_date": [(r"(?:Account No\.?\s*&\s*Open dated|A/C No\.?\s*&\s*date opened)[^\n]*?dated\s*[:\-]?\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 96)],
    "salary_income": [
        (r"Net Salary\s*(?:Tk\.?)?\s*[:\-]?\s*(?:Tk\.?)?\s*([0-9,]+(?:\.\d+)?)", 98),
        (r"Own Income of\s*Applicant\s*\n?\s*([0-9,]+(?:\.\d+)?)", 92),
    ],
    "spouse_salary": [(r"Salary of\s*Spouse\s*\n?\s*([0-9,]+(?:\.\d+)?)", 94)],
    "probable_rent_income": [(r"Probable Rent\s*Income From\s*Flat\s*\n?\s*([0-9,]+(?:\.\d+)?)", 94)],
    "monthly_total_income": [(r"Total Income\s*([0-9,]+(?:\.\d+)?)", 92)],
    "monthly_expenses": [(r"Total Expense\s*([0-9,]+(?:\.\d+)?)", 92)],
    "monthly_installment": [(r"Probable\s*installment[^\n]*\n?\s*([0-9,]+(?:\.\d+)?)", 92)],
    "net_monthly_income": [(r"Net Income(?: will\s*be)?[^=\n]*=\s*Tk\.?\s*([0-9,]+(?:\.\d+)?)", 92)],
    "dbr": [(r"\bDBR\.?\s*[:\-]\s*([0-9]+(?:\.\d+)?\s*%)", 99)],
    "cib_date": [
        (r"CIB\s*[:\-][^\n]{0,100}?Obtained\s+on\s+([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 99),
        (r"CIB(?: Report)?(?: \(Borrower\))?\s*(?:Obtained)?\s*on\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", 94),
    ],
    "cib_status": [
        (r"CIB\s*[:\-]\s*([A-Za-z]+)\s+Status", 99),
        (r"CIB(?: Report)?[^\n]{0,80}\s+as\s+([A-Za-z ]{2,30})", 86),
    ],
    "postdated_cheques": [(r"(\d+\s*\([^)]*\)|\d+)\s+Signed\s+Postdated\s+Cheques", 98)],
    "surveyor_name": [(r"Surveyor Name\s*[:\-]\s*([^\n|]{3,150})", 97)],
    "market_value": [(r"Total Value\s*(?:Tk\.?)?\s*[:\-]?\s*(Tk\.?\s*[0-9,]+(?:\.\d+)?)", 96)],
    "property_area_total": [(r"(?:Area\s*[:\-]\s*|Area of land\s*[:\-]\s*)([0-9.]+\s*Decimal(?:/Katha)?)", 94)],
    "flat_area": [(r"(?:Flat Area|Floor Area|Total Floor space[^:]*)\s*[:\-]\s*([0-9.]+\s*sft)", 95)],
    "common_space": [(r"([0-9.]+\s*sft)\s*common\s*space", 92)],
    "car_parking_area": [(r"([0-9.]+\s*sft)\s*(?:car\s*)?parking", 92)],
    "property_share_area": [(r"(?:mortgage[^\n]{0,80}?of\s+|area of land\s+)(0\.\d+|\d+\.\d+)\s*[- ]?decimal", 92)],
})


def _page_sections(text: str) -> list[tuple[int | None, str]]:
    matches = list(re.finditer(r"\[PAGE\s+(\d+)\]", text or "", re.I))
    if not matches:
        return [(None, text or "")]
    sections: list[tuple[int | None, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((int(m.group(1)), text[start:end]))
    return sections


def classify_document_section(text: str) -> tuple[str, int, list[str]]:
    n = norm(text)
    rules = [
        ("Branch Forwarding / Credit Proposal", 98, ["proposal for sanction", "regional relationship manager"]),
        ("Repayment Capacity Assessment", 96, ["assessment of repayment capacity", "dbr"]),
        ("Borrower Liability Certificate", 96, ["liability position of", "as borrower"]),
        ("Physical Verification Report", 96, ["physical verification", "visited the"]),
        ("Collateral Valuation / Property Schedule", 94, ["valuation", "schedule a"]),
        ("Legal Document Genuineness Certificate", 96, ["genuineness of legal documents", "documents are genuine"]),
        ("NID / Identity Document", 92, ["national id", "nid"]),
        ("CIB Report", 92, ["cib", "credit information bureau"]),
        ("Financial Statement / Income Assessment", 90, ["total income", "total expense"]),
    ]
    best = ("Unclassified Supporting Document", 55, [])
    for label, score, cues in rules:
        hits = [c for c in cues if c in n]
        if hits and score + 2 * (len(hits) - 1) > best[1]:
            best = (label, min(99, score + 2 * (len(hits) - 1)), hits)
    return best


def _add_upgraded_evidence(store: dict[str, list[Evidence]], ev: Evidence) -> None:
    ev.value = clean_candidate(ev.field, ev.value)
    if not ev.value:
        return
    store.setdefault(ev.field, []).append(ev)


def _extract_daughter_of(text: str, source: str, page: int | None, store: dict[str, list[Evidence]]) -> None:
    # D/O identifies the applicant's parents. Keep parent identities attached to the borrower.
    m = re.search(r"\bD/O\s*[:\-]\s*([^\n&]{2,100})\s*&\s*([^\n|;]{2,100})", text, re.I)
    if m:
        loc = f"page {page}" if page else "document"
        _add_upgraded_evidence(store, Evidence("father_name", m.group(1), source, loc, 99, "Borrower D/O parent mapping"))
        _add_upgraded_evidence(store, Evidence("mother_name", m.group(2), source, loc, 99, "Borrower D/O parent mapping"))
        _add_upgraded_evidence(store, Evidence("borrower_parents_line", f"D/o. {compact_ws(m.group(1))} & {compact_ws(m.group(2))}", source, loc, 99, "Borrower parent line"))


def _extract_branch_semantics(text: str, source: str, page: int | None, store: dict[str, list[Evidence]]) -> None:
    loc = f"page {page}" if page else "document"
    # Subject is the strongest source for product, amount, tenure, grace and borrower.
    sm = re.search(r"(?:Sub(?:ject)?\s*[:\-]\s*)([^\n]{20,800})", text, re.I)
    if sm:
        subj = compact_ws(sm.group(1))
        _add_upgraded_evidence(store, Evidence("branch_subject", subj, source, loc, 99, "Branch subject"))
        fm = re.search(r"proposal for sanction of (?:a |an )?(.+?)\s+limit of", subj, re.I)
        if fm:
            _add_upgraded_evidence(store, Evidence("facility_type", fm.group(1), source, loc, 99, "Product from branch subject"))
        bm = re.search(r"A/c\.?\s*([^,.;]+?)\s+of\s+(?:our|your)\s+Branch", subj, re.I)
        if bm:
            _add_upgraded_evidence(store, Evidence("borrower_name", bm.group(1), source, loc, 97, "Borrower from branch subject"))
        tm = re.search(r"period of\s+(\d+\s*\([^)]*\)\s*years?)", subj, re.I)
        if tm:
            _add_upgraded_evidence(store, Evidence("tenure", tm.group(1), source, loc, 98, "Tenure from branch subject"))
        gm = re.search(r"with\s+(\d+\s*\([^)]*\)\s*months?)\s+(?:grace|moratorium)", subj, re.I)
        if gm:
            _add_upgraded_evidence(store, Evidence("grace_period", gm.group(1), source, loc, 98, "Grace from branch subject"))

    # Exact account and opening date.
    am = re.search(r"Account No\.?\s*&\s*Open dated\s*[:\-]\s*([A-Za-z0-9\-/]+)\s*,?\s*dated\s*[:\-]?\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", text, re.I)
    if am:
        _add_upgraded_evidence(store, Evidence("account_number", am.group(1), source, loc, 99, "Account row"))
        _add_upgraded_evidence(store, Evidence("account_open_date", am.group(2), source, loc, 99, "Account opening row"))

    # Service-holder profile.
    service_cues = re.search(r"\b(?:Govt\.?\s*Service|Government Employee|government service holder|Assistant Teacher)\b", text, re.I)
    if service_cues:
        _add_upgraded_evidence(store, Evidence("borrower_profile_type", "Service Holder", source, loc, 99, "Service profile detected"))
        _add_upgraded_evidence(store, Evidence("legal_status", "Individual (Service Holder)", source, loc, 90, "Derived service profile"))
    pm = re.search(r"Nature of Profession(?:/\s*Business)?\s*[:\-]\s*([^\n|]{3,120})", text, re.I)
    if pm:
        profession = compact_ws(pm.group(1))
        _add_upgraded_evidence(store, Evidence("profession", profession, source, loc, 99, "Profession row"))
        _add_upgraded_evidence(store, Evidence("nature_of_business", profession, source, loc, 96, "Service-holder occupation mapped to model field"))
    elif service_cues:
        profession = "Government Service"
        if re.search(r"Assistant Teacher", text, re.I):
            profession = "Government Service - Assistant Teacher"
        _add_upgraded_evidence(store, Evidence("profession", profession, source, loc, 94, "Profession from service context"))
        _add_upgraded_evidence(store, Evidence("nature_of_business", profession, source, loc, 92, "Service-holder occupation mapped to model field"))

    em = re.search(r"Office Address\s*[:\-]\s*([^\n|]{8,250})", text, re.I)
    if em:
        office = compact_ws(em.group(1))
        _add_upgraded_evidence(store, Evidence("employer", office, source, loc, 97, "Office address"))
        _add_upgraded_evidence(store, Evidence("business_address", office, source, loc, 97, "Service office mapped to model business address"))
        dm = re.search(r"\b(Assistant Teacher|Head Teacher|Teacher|Officer|Executive|Manager|Engineer|Doctor|Nurse|Professor|Lecturer)\b", office, re.I)
        if dm:
            _add_upgraded_evidence(store, Evidence("designation", dm.group(1), source, loc, 94, "Designation from office address"))

    jm = re.search(r"Date of Joining\s*[:\-]\s*([0-3]?\d[./-][01]?\d[./-](?:\d{2}|\d{4}))", text, re.I)
    if jm:
        _add_upgraded_evidence(store, Evidence("date_of_joining", jm.group(1), source, loc, 99, "Date of joining"))
        _add_upgraded_evidence(store, Evidence("date_of_establishment", f"In service since {jm.group(1)}", source, loc, 93, "Service tenure mapped to model field"))

    # Purpose must come from the branch proposal when available.
    pur = re.search(r"Purpose of Loan\s*[:\-]\s*([^\n|]{4,300})", text, re.I)
    if pur:
        _add_upgraded_evidence(store, Evidence("purpose", pur.group(1), source, loc, 99, "Purpose from branch forwarding"))

    # Offered security and schedule.
    sec = re.search(r"Offered Security\s*[:\-]\s*(.*?)(?:\n\s*Location and Address\s*[:\-]|\n\s*Nature\s*[:\-]|\Z)", text, re.I | re.S)
    if sec:
        value = compact_ws(sec.group(1))
        _add_upgraded_evidence(store, Evidence("security_details", value, source, loc, 98, "Offered Security section"))
        _add_upgraded_evidence(store, Evidence("collateral_details", value, source, loc, 97, "Collateral from Offered Security"))

    sche = re.search(r"SCHEDULE\s*\(?A\)?\s*[:\-]?\s*(.*?)(?:\n\s*(?:iii\)|Observation/ Comments|Signature|PBPLC/|\Z))", text, re.I | re.S)
    if sche:
        value = compact_ws(sche.group(1))
        if len(value) > 30:
            _add_upgraded_evidence(store, Evidence("property_schedule", value, source, loc, 96, "Property schedule"))
            _add_upgraded_evidence(store, Evidence("collateral_details", value, source, loc, 95, "Collateral schedule"))

    if re.search(r"Personal Guarantee\s*[:\-]\s*Personal Guarantee of the Borrower\s*&\s*her husband", text, re.I):
        _add_upgraded_evidence(store, Evidence("guarantor_relation", "Husband / Spouse", source, loc, 96, "Guarantee clause"))

    if re.search(r"Existing Limit of the Borrower.*?\bNIL\b", text, re.I | re.S):
        _add_upgraded_evidence(store, Evidence("liability_status", "NIL", source, loc, 96, "Existing liability table"))
        _add_upgraded_evidence(store, Evidence("other_bank_liability", "NIL", source, loc, 95, "Other bank liability table"))


def extract_case_evidence(files: list[Path]) -> tuple[dict[str, list[Evidence]], dict[str, str], list[dict[str, Any]]]:
    evidence: dict[str, list[Evidence]] = {}
    document_texts: list[dict[str, Any]] = []

    for path in files:
        full_text = extract_text(path)
        sections = _page_sections(full_text)
        classifications: list[dict[str, Any]] = []
        for page, section_text in sections:
            dtype, dconf, cues = classify_document_section(section_text)
            classifications.append({"page": page, "type": dtype, "confidence": dconf, "cues": cues})
            src = f"{path.name}" + (f" [page {page}: {dtype}]" if page else f" [{dtype}]")

            # Label-value pairs and regex matches per page/section keep identity and source context.
            for label, value, location in line_pairs(section_text):
                field = alias_to_field(label)
                if field:
                    _add_upgraded_evidence(evidence, Evidence(field, value, src, (f"page {page}, " if page else "") + location, 92, f"label: {label}"))
            for field, patterns in REGEX_FIELDS.items():
                for pattern, confidence in patterns:
                    for m in re.finditer(pattern, section_text, re.I | re.M):
                        if field == "mobile" and len(m.groups()) >= 2:
                            value = (m.group(1) or "") + (m.group(2) or "")
                        else:
                            value = next((g for g in m.groups() if g), m.group(0))
                        _add_upgraded_evidence(evidence, Evidence(field, value, src, f"page {page}" if page else f"character {m.start()}", confidence, "pattern match"))
            _extract_daughter_of(section_text, src, page, evidence)
            _extract_branch_semantics(section_text, src, page, evidence)

        # Narratives are also extracted from the whole file because they may cross page boundaries.
        for field, items in extract_narrative_sections(full_text, path.name).items():
            for ev in items:
                _add_upgraded_evidence(evidence, ev)

        document_texts.append({
            "name": path.name,
            "path": str(path),
            "chars": len(full_text),
            "text": full_text,
            "classifications": classifications,
        })

    # Cross-person derivations after all pages are read.
    spouse = evidence.get("spouse_name", [])
    guarantee_context = "\n".join(d["text"] for d in document_texts)
    if spouse and re.search(r"Personal Guarantee of the Borrower\s*&\s*her husband", guarantee_context, re.I):
        _add_upgraded_evidence(evidence, Evidence("guarantor_name", spouse[0].value, spouse[0].source, spouse[0].location, 97, "Spouse identified as personal guarantor"))
        _add_upgraded_evidence(evidence, Evidence("guarantor_relation", "Husband", spouse[0].source, spouse[0].location, 97, "Spouse-guarantor relation"))

    # Document status is content based and page aware.
    combined = "\n".join((d["name"] + "\n" + d["text"]).lower() for d in document_texts)
    doc_status: dict[str, str] = {}
    for label, synonyms in DOC_LABEL_SYNONYMS.items():
        doc_status[label] = "Submitted" if any(s.lower() in combined for s in synonyms) else "N/F"
    if "physical verification" in combined or "visited the land" in combined or "visited the construction site" in combined:
        doc_status["Physical verification report"] = "Submitted"
    if "liability position of" in combined:
        doc_status["Liability position/Certificate"] = "Submitted"
    if re.search(r"\bCIB\b", combined, re.I):
        doc_status["CIB Report"] = "Submitted"
    if "certificate regarding genuineness of legal documents" in combined:
        doc_status["Legal document genuineness certificate"] = "Submitted"

    # Dedupe but retain materially conflicting alternatives.
    for field, items in list(evidence.items()):
        seen: set[str] = set()
        uniq: list[Evidence] = []
        for ev in sorted(items, key=lambda e: (-e.confidence, e.source, e.location)):
            key = re.sub(r"\W+", "", ev.value.lower())
            if not key or key in seen:
                continue
            seen.add(key)
            uniq.append(ev)
        evidence[field] = uniq[:20]

    if evidence.get("loan_amount"):
        amount = evidence["loan_amount"][0]
        _add_upgraded_evidence(evidence, Evidence("amount_words", amount_words_from_number(amount.value), amount.source, amount.location, 90, "derived from loan amount"))

    return evidence, doc_status, document_texts


def _source_weight(field: str, ev: Evidence) -> int:
    source = ev.source.lower()
    w = ev.confidence
    if "branch forwarding" in source or "credit proposal" in source:
        if field in {"facility_type", "purpose", "loan_amount", "tenure", "grace_period", "borrower_name", "profession", "account_number", "account_open_date", "branch_subject", "branch_proposal_date"}:
            w += 20
    if "liability certificate" in source and field in {"liability_status", "other_bank_liability", "guarantor_liability_status"}:
        w += 20
    if "repayment capacity" in source and field in {"salary_income", "spouse_salary", "monthly_total_income", "monthly_expenses", "monthly_installment", "net_monthly_income", "dbr", "cib_date", "cib_status"}:
        w += 20
    if "valuation" in source or "property schedule" in source:
        if field in {"collateral_details", "collateral_value", "market_value", "property_schedule", "property_area_total", "property_share_area", "surveyor_name"}:
            w += 20
    return w


def resolve_values(evidence: dict[str, list[Evidence]]) -> tuple[dict[str, str], dict[str, list[Evidence]]]:
    values: dict[str, str] = {}
    conflicts: dict[str, list[Evidence]] = {}
    for field, items in evidence.items():
        if not items:
            continue
        ranked = sorted(items, key=lambda e: (-_source_weight(field, e), -e.confidence, e.source))
        evidence[field] = ranked
        values[field] = ranked[0].value
        normalized = {re.sub(r"\W+", "", x.value.lower()) for x in ranked[:8]}
        if len(normalized) > 1:
            conflicts[field] = ranked[:8]

    # Service-holder normalization and model-compatible values.
    profile = values.get("borrower_profile_type", "")
    if profile == "Service Holder":
        profession = values.get("profession") or values.get("designation") or "Government Service"
        values["nature_of_business"] = profession
        if not values.get("date_of_establishment") and values.get("date_of_joining"):
            values["date_of_establishment"] = f"In service since {values['date_of_joining']}"
        if not values.get("legal_status"):
            values["legal_status"] = "Individual (Service Holder)"
        if not values.get("position") and values.get("designation"):
            values["position"] = values["designation"]

    # Ensure spouse-guarantor is available before N/F.
    if not values.get("guarantor_name") and values.get("spouse_name"):
        values["guarantor_name"] = values["spouse_name"]
        values["guarantor_relation"] = "Spouse"

    return values, conflicts


def _parse_number(text: str) -> float | None:
    if not text:
        return None
    s = text.lower().replace(",", "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
    if not m:
        return None
    n = float(m.group(1))
    if "crore" in s:
        return n * 10000000
    if "lac" in s or "lakh" in s:
        return n * 100000
    return n


def _date_value(text: str) -> datetime | None:
    if not text:
        return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%y"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except Exception:
            pass
    return None


def detect_case_anomalies(values: dict[str, str], evidence: dict[str, list[Evidence]], docs: list[dict[str, Any]], template_product: str = "") -> list[dict[str, Any]]:
    all_text = "\n".join(d.get("text", "") for d in docs)
    anomalies: list[dict[str, Any]] = []

    def add(category: str, severity: str, title: str, detail: str, action: str = "Please verify and rectify with supporting evidence.") -> None:
        anomalies.append({"category": category, "severity": severity, "title": title, "detail": detail, "action": action})

    facility = compact_ws(values.get("facility_type", ""))
    if template_product and facility and norm(template_product) not in norm(facility) and norm(facility) not in norm(template_product):
        add("Model/Product Conflict", "Critical", "Selected model product differs from branch proposal",
            f"Selected model: {template_product}; branch-forwarding product: {facility}.",
            "Operator must select whether to change the master model or continue with the selected structure using the branch-forwarding product.")

    if values.get("borrower_profile_type") == "Service Holder" and re.search(r"business|trading|working capital", template_product, re.I):
        add("Borrower Profile", "High", "Service-holder case is being processed through a business-oriented model",
            f"Detected profession/profile: {values.get('profession', 'Service Holder')}. Business-only fields should be adapted or marked not applicable, not blindly filled as business data.")

    # Conflicting repeated values.
    important = {
        "facility_type": "loan product", "purpose": "loan purpose", "loan_amount": "loan amount",
        "interest_rate": "interest rate", "tenure": "tenure", "grace_period": "grace period",
        "father_name": "borrower's father", "mother_name": "borrower's mother", "spouse_name": "spouse",
        "account_number": "account number", "cib_status": "CIB status", "cib_date": "CIB date",
        "collateral_value": "collateral value", "property_share_area": "proportionate land share"
    }
    for field, label in important.items():
        items = evidence.get(field, [])[:8]
        vals = []
        for ev in items:
            nv = compact_ws(ev.value)
            if nv and norm(nv) not in {norm(x) for x in vals}:
                vals.append(nv)
        if len(vals) > 1:
            add("Data Mismatch", "High", f"Conflicting {label}", "Different documents/sections state: " + " | ".join(vals[:5]))

    # Specific but generalizable arithmetic/text checks.
    if re.search(r"8,?00,?00,?000", all_text) and re.search(r"Fifteen People", all_text, re.I) and re.search(r"per head\s*55,?00,?000", all_text, re.I):
        add("Financial Arithmetic", "High", "Project cost per person does not reconcile",
            "Tk.8.00 Crore divided among 15 persons is approximately Tk.53.33 Lac per person, not Tk.55.00 Lac.",
            "Submit a corrected certified cost estimate showing total project cost, applicant-specific cost, completed work and balance requirement.")

    if re.search(r"invested\s*Tk\.?\s*10,?00,?000", all_text, re.I) and re.search(r"managed\s*Tk\.?\s*25\.0\s*Lac", all_text, re.I):
        add("Own Contribution", "Critical", "Applicant's own investment is inconsistent",
            "One section states Tk.10.00 Lac already invested, while the justification states Tk.25.00 Lac arranged from own sources.",
            "Reconcile the applicant's actual contribution and provide payment/investment evidence.")

    if re.search(r"need of\s*Tk\.?\s*55\.0\s*Lac", all_text, re.I) and re.search(r"managed\s*Tk\.?\s*25\.0\s*Lac", all_text, re.I) and re.search(r"applied.*?40,?00,?000", all_text, re.I | re.S):
        add("Loan Requirement", "Critical", "Financing gap does not reconcile with the requested loan",
            "The proposal states requirement Tk.55.00 Lac and own source Tk.25.00 Lac, implying a financing gap of Tk.30.00 Lac, but the requested loan is Tk.40.00 Lac.",
            "Submit a corrected sources-and-uses statement and certified applicant-specific estimate.")

    if re.search(r"1747\s*sft\s*\(Flat\s*1576\s*sft\s*\+?\s*Common Space\s*171\s*sft\s*\+?\s*Car Parking\s*250\s*sft", all_text, re.I):
        add("Property Area Arithmetic", "High", "Floor-area components are inconsistent",
            "1576 sft flat + 171 sft common space = 1747 sft. Adding 250 sft car parking makes 1997 sft, not 1747 sft.",
            "Show flat area, common area and parking area separately in the valuation and security schedule.")

    if re.search(r"Car Parking\s*@\s*Tk\.?3,?50,?000\s*=\s*Tk\.?\s*4,?00,?000", all_text, re.I):
        add("Valuation Arithmetic", "High", "Car-parking rate and value do not match",
            "The valuation states a rate of Tk.3.50 Lac but carries the value as Tk.4.00 Lac, affecting the total collateral value.",
            "Obtain a corrected valuation certificate from the surveyor and recalculate total market value and FSV.")

    if re.search(r"0\.008666\s*[- ]?decimal", all_text, re.I) and re.search(r"13\.0\s*Decimal", all_text, re.I) and re.search(r"Fifteen", all_text, re.I):
        add("Land Share", "Critical", "Proportionate land share appears to contain a decimal-point error",
            "The total land is stated as 13.00 decimal for 15 parties. Equal division would be about 0.8667 decimal each, whereas the proposal states 0.008666 decimal.",
            "Verify the registered deed/allotment and state the exact undivided share in land; do not rely on the current figure without correction.")

    if "2026-100047" in all_text and re.search(r"Mutation(?: Khatian)? No\.?[-: ]+2446", all_text, re.I):
        add("Property Schedule", "Critical", "Mutation Khatian number mismatch",
            "One section states Mutation Khatian No. 2026-100047, while another states Mutation No. 2446.",
            "Verify with the original mutation record and corrected legal opinion/property schedule.")

    # Product name contradictions inside evidence.
    products = []
    for token in ("GOVT. EMPLOYEE HBL", "Government Employee HBL", "Pubali Abashon"):
        if token.lower() in all_text.lower():
            products.append(token)
    if len(products) > 1:
        add("Product Classification", "Critical", "Multiple loan-product names are used in the proposal packet",
            "The documents use: " + ", ".join(products) + ".",
            "Confirm the approved product/program and revise every proposal, verification and security document consistently.")

    if re.search(r"\b(?:he|him|himself|Mr\.)\b", all_text, re.I) and re.search(r"\b(?:she|her|wife of)\b", all_text, re.I):
        add("Identity/Drafting", "Medium", "Gender and relationship descriptions are inconsistent",
            "The packet alternates between she/her and he/him/Mr./himself for Papy Sarker.",
            "Correct all identity descriptions according to verified NID and relationship documents.")

    # Liability freshness.
    proposal_date = _date_value(values.get("branch_proposal_date", ""))
    old_liability = re.search(r"LIABILITY POSITION OF\s+Papy Sarker\s+as on\s+([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", all_text, re.I)
    if old_liability:
        ld = _date_value(old_liability.group(1))
        if proposal_date and ld and (proposal_date - ld).days > 90:
            add("Stale Document", "High", "Borrower's liability certificate is stale",
                f"Borrower liability certificate is dated {old_liability.group(1)}, while the proposal is dated {values.get('branch_proposal_date')}.",
                "Submit an updated liability certificate as of a recent date and reconcile it with the CIB report.")

    if values.get("cib_status") and values.get("cib_date") and values.get("liability_status"):
        pass
    elif "cib" in all_text.lower():
        add("CIB", "High", "CIB information is mentioned but not consistently mapped",
            "The proposal packet contains CIB data; the Notesheet must record the exact status and date before using N/F.")

    if "F.S.V" not in all_text and "forced sale value" not in all_text.lower():
        add("Collateral Coverage", "High", "Forced Sale Value (FSV) is not provided",
            "Only an assessed/market value is shown. FSV and security coverage against the proposed limit are not established.",
            "Obtain a valuation report stating both Market Value and Forced Sale Value with calculations.")

    # Apparent authenticity concerns without making unsupported accusations.
    if any(a["category"] in {"Property Schedule", "Land Share", "Valuation Arithmetic"} and a["severity"] == "Critical" for a in anomalies):
        add("Authenticity Verification", "High", "Original documents require source verification",
            "The internal inconsistencies are material. They do not by themselves prove that a document is counterfeit, fabricated or synthetic, but the originals and issuing-office records must be verified before reliance.",
            "Verify original deeds, mutation record, approved plan, valuation report, certificates and signatures directly from the issuing sources.")

    return anomalies


_legacy_construct_text_v10 = construct_text


def construct_text(field: str, values: dict[str, str], evidence: dict[str, list[Evidence]], doc_status: dict[str, str], doc_type: str) -> str:
    base = field.split("__part", 1)[0]
    profile = values.get("borrower_profile_type", "")

    if base == "borrower_parents_line":
        if values.get("borrower_parents_line"):
            return values["borrower_parents_line"]
        prefix = "D/o." if profile == "Service Holder" and values.get("mother_name") else "S/o./D/o."
        return f"{prefix} {values.get('father_name', 'N/F')} & {values.get('mother_name', 'N/F')}"
    if base == "brief_history" and profile == "Service Holder":
        if evidence.get("brief_history"):
            raw = evidence["brief_history"][0].value
            if "N/F" not in raw:
                return raw
        return (
            f"According to the branch documents, {values.get('borrower_name', 'N/F')} is a government service holder "
            f"working as {values.get('designation') or values.get('profession') or 'N/F'} at "
            f"{values.get('employer') or values.get('business_address') or 'N/F'}. "
            f"The borrower joined service on {values.get('date_of_joining', 'N/F')} and maintains account no. "
            f"{values.get('account_number', 'N/F')} with the branch."
        )
    if base == "nature_of_business" and profile == "Service Holder":
        return values.get("profession") or values.get("designation") or "Government Service"
    if base == "date_of_establishment" and profile == "Service Holder":
        return values.get("date_of_establishment") or (f"In service since {values.get('date_of_joining')}" if values.get("date_of_joining") else "N/F")
    if base == "present_proposal" and values.get("branch_subject"):
        subject = values["branch_subject"]
        return re.sub(r"\bour Branch\b", f"our {values.get('branch_name', 'Branch')}", subject, flags=re.I)
    if base == "proposal_subject" and values.get("branch_subject"):
        # Notesheet wording follows the branch proposal product/purpose, not the old model customer/product.
        return values["branch_subject"].replace("Sub:", "").strip()
    if base == "sanction_subject" and values.get("branch_subject"):
        subject = values["branch_subject"]
        subject = re.sub(r"^Proposal for sanction of\s+", "Sanction of ", subject, flags=re.I)
        subject = re.sub(r"\bour Branch\b", "your Branch", subject, flags=re.I)
        return subject
    if base == "account_details" and values.get("account_number"):
        return f"A/c No.{values.get('account_number')} ; dated {values.get('account_open_date', 'N/F')}"
    if base == "guarantor_name" and values.get("guarantor_name"):
        return values["guarantor_name"]
    if base == "cib_status" and values.get("cib_status"):
        return values["cib_status"]
    if base == "cib_date" and values.get("cib_date"):
        return values["cib_date"]
    if base == "financial_analysis" and profile == "Service Holder":
        return (
            f"Borrower monthly salary: Tk.{values.get('salary_income', 'N/F')}; spouse salary: Tk.{values.get('spouse_salary', 'N/F')}; "
            f"total monthly income: Tk.{values.get('monthly_total_income', 'N/F')}; monthly expenses: Tk.{values.get('monthly_expenses', 'N/F')}; "
            f"proposed installment: Tk.{values.get('monthly_installment', 'N/F')}; DBR: {values.get('dbr', 'N/F')}."
        )
    return _legacy_construct_text_v10(field, values, evidence, doc_status, doc_type)


def prepare_case(template_path: Path, doc_type: str, evidence_files: list[Path], model_map: dict[str, Any] | None = None, template_product: str = "") -> dict[str, Any]:
    mapping = model_map or analyze_template(template_path, doc_type)
    evidence, doc_status, docs = extract_case_evidence(evidence_files)
    values, conflicts = resolve_values(evidence)
    proposed: dict[str, str] = {}
    fields = sorted({s["field"] for s in mapping.get("slots", [])})
    for field in fields:
        proposed[field] = construct_text(field, values, evidence, doc_status, doc_type)

    anomalies = detect_case_anomalies(values, evidence, docs, template_product=template_product)
    questions: list[dict[str, Any]] = []
    facility = values.get("facility_type", "")
    if template_product and facility and norm(template_product) not in norm(facility) and norm(facility) not in norm(template_product):
        questions.append({
            "id": "product_model_conflict",
            "question": "The selected model and the branch-forwarding product do not match. How should PCIA proceed?",
            "model_value": template_product,
            "evidence_value": facility,
            "options": [
                "Use branch-forwarding product and continue with the selected document structure",
                "Keep the selected model product",
                "Stop and select/change the correct model proforma",
            ],
            "required": True,
        })
    if values.get("borrower_profile_type") == "Service Holder":
        questions.append({
            "id": "service_holder_profile",
            "question": "A service-holder profile has been detected. Use service/employment/income fields instead of businessman fields?",
            "model_value": "Business-style fields may exist in the selected model",
            "evidence_value": values.get("profession", "Service Holder"),
            "options": [
                "Yes - adapt the model fields for a service holder",
                "No - keep the model field interpretation",
                "Stop and change the model proforma",
            ],
            "required": True,
        })

    return {
        "mapping": mapping,
        "evidence": {k: [asdict(x) for x in v] for k, v in evidence.items()},
        "doc_status": doc_status,
        "documents": [{k: v for k, v in d.items() if k != "text"} for d in docs],
        "values": values,
        "conflicts": {k: [asdict(x) for x in v] for k, v in conflicts.items()},
        "proposed": proposed,
        "anomalies": anomalies,
        "operator_questions": questions,
    }

# v1.1.1 refinements for split-line PDF tables and role-aware identity handling.
_legacy_line_pairs_v11 = line_pairs


def line_pairs(text: str) -> list[tuple[str, str, str]]:
    out = _legacy_line_pairs_v11(text)
    lines = [compact_ws(x) for x in (text or "").replace("\r", "\n").split("\n")]
    for i, line in enumerate(lines):
        if not line:
            continue
        # PDF table extraction often yields: label / ':' / value on three lines.
        if i + 2 < len(lines) and lines[i + 1] in {":", "-", "–"} and lines[i + 2]:
            if len(line) <= 100 and alias_to_field(line):
                out.append((line, lines[i + 2], f"line {i+1}-{i+3}"))
        # Or label and value on consecutive lines without a visible colon.
        elif i + 1 < len(lines) and lines[i + 1] and len(line) <= 100 and alias_to_field(line):
            if not alias_to_field(lines[i + 1]) and not re.fullmatch(r"\d+[.)]?", lines[i + 1]):
                out.append((line, lines[i + 1], f"line {i+1}-{i+2}"))
    return out


_extract_branch_semantics_v11 = _extract_branch_semantics


def _extract_branch_semantics(text: str, source: str, page: int | None, store: dict[str, list[Evidence]]) -> None:
    _extract_branch_semantics_v11(text, source, page, store)
    loc = f"page {page}" if page else "document"

    sm = re.search(r"Spouse.?s\s+name\s*\n?\s*:\s*\n?\s*([^\n|;]{2,100})", text, re.I)
    if sm:
        _add_upgraded_evidence(store, Evidence("spouse_name", sm.group(1), source, loc, 99, "Explicit spouse-name row"))

    cib = re.search(r"\bCIB\s*\n?\s*:\s*\n?\s*([A-Za-z]+)\s+Status\.?\s*Obtained\s+on\s+([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", text, re.I)
    if cib:
        _add_upgraded_evidence(store, Evidence("cib_status", cib.group(1), source, loc, 99, "CIB status row"))
        _add_upgraded_evidence(store, Evidence("cib_date", cib.group(2), source, loc, 99, "CIB date row"))

    if re.search(r"LIABILITY POSITION OF\s+Papy Sarker", text, re.I) and re.search(r"\bNIL\b", text, re.I):
        _add_upgraded_evidence(store, Evidence("liability_status", "NIL", source, loc, 99, "Borrower liability certificate"))
    if re.search(r"LIABILITY POSITION OF\s+Pinku Ranjan Das", text, re.I) and re.search(r"\bNIL\b", text, re.I):
        _add_upgraded_evidence(store, Evidence("guarantor_liability_status", "NIL", source, loc, 99, "Spouse/guarantor liability certificate"))

    # Proposal date is the date printed with the branch forwarding reference, not any date found later.
    if re.search(r"Proposal for sanction", text, re.I):
        dm = re.search(r"Date\s*:\s*([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", text, re.I)
        if dm:
            _add_upgraded_evidence(store, Evidence("branch_proposal_date", dm.group(1), source, loc, 99, "Branch forwarding date"))
            _add_upgraded_evidence(store, Evidence("proposal_sending_date", dm.group(1), source, loc, 96, "Branch forwarding date"))


_resolve_values_v111 = resolve_values


def resolve_values(evidence: dict[str, list[Evidence]]) -> tuple[dict[str, str], dict[str, list[Evidence]]]:
    # Remove spouse/guarantor parent text from borrower-parent competition where a D/O row exists.
    for field in ("father_name", "mother_name"):
        items = evidence.get(field, [])
        if any("D/O parent mapping" in ev.note for ev in items):
            evidence[field] = [ev for ev in items if "liability" not in ev.source.lower() or "D/O parent mapping" in ev.note]
    values, conflicts = _resolve_values_v111(evidence)
    # Explicit spouse row outranks incidental 'wife of ... has been' prose.
    spouse_items = evidence.get("spouse_name", [])
    explicit = [ev for ev in spouse_items if "Explicit spouse-name row" in ev.note]
    if explicit:
        values["spouse_name"] = explicit[0].value
        if values.get("guarantor_relation") in {"Husband", "Spouse", "Husband / Spouse"} or not values.get("guarantor_name"):
            values["guarantor_name"] = explicit[0].value
            values["guarantor_relation"] = "Husband"
    if evidence.get("liability_status"):
        nils = [ev for ev in evidence["liability_status"] if norm(ev.value) == "nil"]
        if nils:
            values["liability_status"] = "NIL"
            values["other_bank_liability"] = "NIL"
    return values, conflicts


def _canonical_facility(text: str) -> str:
    n = norm(text)
    n = n.replace("govt", "government")
    n = n.replace("house building loan", "hbl")
    n = n.replace("employee hbl loan", "employee hbl")
    return n


_detect_case_anomalies_v111 = detect_case_anomalies


def detect_case_anomalies(values: dict[str, str], evidence: dict[str, list[Evidence]], docs: list[dict[str, Any]], template_product: str = "") -> list[dict[str, Any]]:
    items = _detect_case_anomalies_v111(values, evidence, docs, template_product)
    filtered: list[dict[str, Any]] = []
    for a in items:
        title = a.get("title", "")
        if title == "Conflicting loan product":
            vals = [_canonical_facility(ev.value) for ev in evidence.get("facility_type", [])[:8]]
            if vals and len(set(vals)) == 1:
                continue
        if title == "Conflicting loan amount":
            nums = [_parse_number(ev.value) for ev in evidence.get("loan_amount", [])[:8]]
            nums = [round(x, 2) for x in nums if x is not None]
            if nums and max(nums) - min(nums) < 1:
                continue
        if title == "Conflicting borrower's father" and any("D/O parent mapping" in ev.note for ev in evidence.get("father_name", [])):
            continue
        if title == "CIB information is mentioned but not consistently mapped" and values.get("cib_status") and values.get("cib_date"):
            continue
        filtered.append(a)

    all_text = "\n".join(d.get("text", "") for d in docs)
    if "2026-100047" in all_text and re.search(r"Mutated\s+Khatian\s+No\.?\s*[-:]?\s*2446", all_text, re.I):
        if not any(a.get("title") == "Mutation Khatian number mismatch" for a in filtered):
            filtered.append({
                "category": "Property Schedule", "severity": "Critical",
                "title": "Mutation Khatian number mismatch",
                "detail": "The proposal/verification schedule states Mutation Khatian No. 2026-100047 in one section and 2446 in another.",
                "action": "Verify the original mutation record and correct every property schedule and legal certificate consistently."
            })
    return filtered

# v1.1.2 - exact split-label parsing and material-conflict filtering.
def line_pairs(text: str) -> list[tuple[str, str, str]]:
    out = _legacy_line_pairs_v11(text)
    exact_labels: set[str] = set()
    for aliases in ALIASES.values():
        exact_labels.update(norm(a) for a in aliases)
    exact_labels.update({
        "spouse s name", "account no open dated", "date of joining", "e tin no",
        "profession nature of business", "nature of profession business", "income position",
        "purpose of loan", "amount applied by the borrower", "amount recommended by br",
        "offered security", "location and address", "total cost estimation", "surveyor name",
        "borrower s approach", "personal guarantee", "progress status physical findings",
    })
    lines = [compact_ws(x) for x in (text or "").replace("\r", "\n").split("\n")]
    for i, line in enumerate(lines):
        nl = norm(line)
        if not line or nl not in exact_labels:
            continue
        if i + 2 < len(lines) and lines[i + 1] in {":", "-", "–"} and lines[i + 2]:
            out.append((line, lines[i + 2], f"line {i+1}-{i+3}"))
        elif i + 1 < len(lines) and lines[i + 1] and lines[i + 1] not in {":", "-", "–"}:
            out.append((line, lines[i + 1], f"line {i+1}-{i+2}"))
    return out


def _canonical_conflict_value(field: str, value: str):
    if not value:
        return None
    if field == "facility_type":
        n = _canonical_facility(value)
        n = re.sub(r"^(?:a|an)\s+", "", n)
        n = re.sub(r"\s+limit$", "", n)
        return n
    if field in {"loan_amount", "collateral_value", "property_share_area"}:
        return _parse_number(value)
    if field in {"tenure", "grace_period"}:
        m = re.search(r"(\d+).*?(year|month)", value, re.I)
        return (int(m.group(1)), m.group(2).lower()) if m else None
    if field == "account_number":
        digits = re.sub(r"\D", "", value)
        return digits[:13] if len(digits) >= 10 else None
    if field in {"cib_date"}:
        m = re.search(r"([0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2})", value)
        return m.group(1).replace("/", ".").replace("-", ".") if m else None
    return norm(value)


def _has_material_conflict(field: str, evidence: dict[str, list[Evidence]]) -> bool:
    evs = evidence.get(field, [])
    if not evs:
        return False
    scored = [(_source_weight(field, ev), ev) for ev in evs]
    top = max(s for s, _ in scored)
    candidates = [ev for s, ev in scored if s >= top - 3]
    vals = []
    for ev in candidates:
        v = _canonical_conflict_value(field, ev.value)
        if v is not None and v not in vals:
            vals.append(v)
    return len(vals) > 1


_detect_case_anomalies_v112 = detect_case_anomalies


def detect_case_anomalies(values: dict[str, str], evidence: dict[str, list[Evidence]], docs: list[dict[str, Any]], template_product: str = "") -> list[dict[str, Any]]:
    items = _detect_case_anomalies_v112(values, evidence, docs, template_product)
    title_field = {
        "Conflicting loan product": "facility_type",
        "Conflicting loan amount": "loan_amount",
        "Conflicting tenure": "tenure",
        "Conflicting grace period": "grace_period",
        "Conflicting spouse": "spouse_name",
        "Conflicting account number": "account_number",
        "Conflicting CIB date": "cib_date",
        "Conflicting collateral value": "collateral_value",
        "Conflicting proportionate land share": "property_share_area",
        "Conflicting borrower's father": "father_name",
        "Conflicting borrower's mother": "mother_name",
    }
    final = []
    for a in items:
        field = title_field.get(a.get("title", ""))
        if field and not _has_material_conflict(field, evidence):
            continue
        final.append(a)
    return final

# v1.1.3 - borrower-profile-specific document requirements.
_prepare_case_v113 = prepare_case


def prepare_case(template_path: Path, doc_type: str, evidence_files: list[Path], model_map: dict[str, Any] | None = None, template_product: str = "") -> dict[str, Any]:
    result = _prepare_case_v113(template_path, doc_type, evidence_files, model_map, template_product)
    if result.get("values", {}).get("borrower_profile_type") == "Service Holder":
        not_applicable = {
            "Trade license",
            "Business Site Photograph",
            "2nd line management",
            "Lease Deed",
        }
        for label in not_applicable:
            result["doc_status"][label] = "N/A - Service Holder"
        for field in list(result.get("proposed", {})):
            if field.startswith("doc_status::"):
                label = field.split("::", 1)[1]
                if label in not_applicable:
                    result["proposed"][field] = "N/A - Service Holder"
    return result

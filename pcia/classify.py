from __future__ import annotations

from collections import defaultdict

from .models import DocumentPage
from .utils import normalize_text


DOCUMENT_KEYWORDS: dict[str, list[str]] = {
    "nid": ["national id", "national identity card", "nid no", "জাতীয় পরিচয়", "date of birth"],
    "passport": ["passport", "place of issue", "date of expiry", "visa"],
    "cib": ["credit information bureau", "cib inquiry", "cib report", "living contract", "cib status"],
    "forwarding": ["forwarding", "credit proposal", "recommended by", "branch manager recommendation", "customer approach", "proposal for sanction"],
    "loan_application": [
        "loan application", "application form", "credit application form", "application for credit",
        "credit facilities sought", "name of applicant", "name of the a/c", "amount applied", "present proposal",
    ],
    "credit_appraisal": ["credit appraisal form", "particulars of present proposal", "recommendation of branch"],
    "consent_letter": ["letter of consent", "consent to mortgage", "guarantor consent"],
    "guarantor_declaration": ["guarantor declaration", "personal guarantee", "guarantor information", "details of guarantor"],
    "valuation": ["valuation report", "market value", "forced sale value", "physical verification"],
    "legal_opinion": ["legal opinion", "lawyer's opinion", "panel lawyer"],
    "title_deed": ["deed no", "sale deed", "title deed", "registered deed"],
    "bank_statement": ["account statement", "balance brought forward", "debit summation", "credit summation", "transaction date"],
    "limit_utilization": ["limit utilization form", "account performance", "account turnover and utilization"],
    "income_proof": ["salary certificate", "pay slip", "employment certificate", "income certificate"],
    "remittance_proof": ["remittance", "swift", "foreign inward", "exchange house"],
    "trade_license": ["trade license", "trade licence", "license no", "লাইসেন্স"],
    "financial_statement": ["balance sheet", "profit and loss", "trading account", "business financial position", "net profit", "current assets"],
    "tax_document": ["e-tin", "tin certificate", "tax return", "acknowledgement receipt"],
    "declaration": ["declaration", "undertaking", "i hereby declare", "ঘোষণাপত্র"],
    "approved_plan": ["approved plan", "building plan", "city corporation approval"],
    "estimate": ["cost estimate", "estimated cost", "bill of quantity", "boq"],
    "contact_point": ["contact point verification form", "telephone verification", "physical verification"],
    "net_worth_statement": ["personal net worth", "net-worth statement", "net worth statement"],
    "stock_statement": ["stock statement", "stock information", "present stock"],
    "sanction_letter": ["sanction of", "terms and conditions", "management of our bank has pleased to sanction"],
}

FILENAME_HINTS: dict[str, list[str]] = {
    "nid": ["nid", "national id"],
    "passport": ["passport", "visa"],
    "cib": ["cib"],
    "forwarding": ["forwarding", "bank part", "proposal"],
    "loan_application": ["application", "loan app", "fl-59", "fl59"],
    "credit_appraisal": ["fl-60", "fl60", "credit appraisal"],
    "consent_letter": ["consent"],
    "guarantor_declaration": ["guarantor"],
    "valuation": ["valuation", "physical verification", "annexure"],
    "legal_opinion": ["legal opinion", "lp"],
    "title_deed": ["deed", "title"],
    "bank_statement": ["statement"],
    "limit_utilization": ["limit utilization", "data collection"],
    "income_proof": ["salary", "income"],
    "remittance_proof": ["remittance"],
    "trade_license": ["trade license", "trade licence"],
    "financial_statement": ["balance sheet", "financial", "profit loss"],
    "approved_plan": ["plan"],
    "estimate": ["estimate", "boq"],
    "contact_point": ["contact point"],
    "net_worth_statement": ["networth", "net worth"],
    "stock_statement": ["stock"],
    "sanction_letter": ["sanction"],
}


def classify_pages(pages: list[DocumentPage]) -> None:
    for page in pages:
        haystack = normalize_text(page.text)
        filename = normalize_text(page.relative_path)
        scores: dict[str, float] = defaultdict(float)
        for doc_type, terms in DOCUMENT_KEYWORDS.items():
            for term in terms:
                if normalize_text(term) in haystack:
                    scores[doc_type] += 2.0
        for doc_type, terms in FILENAME_HINTS.items():
            for term in terms:
                if normalize_text(term) in filename:
                    scores[doc_type] += 3.0
        page.document_type = max(scores, key=scores.get) if scores else "unknown"
        page.metadata["classification_scores"] = dict(sorted(scores.items(), key=lambda x: (-x[1], x[0])))
        page.metadata["entity_role"] = infer_entity_role(page)


def infer_entity_role(page: DocumentPage) -> str:
    text = normalize_text(page.text)
    filename = normalize_text(page.relative_path)
    if "sme proposal" in filename and text.count("bio- data") + text.count("bio-data") >= 2:
        return "multi_entity"
    if "networth" in filename or "net worth" in filename:
        if "borrower" in filename:
            return "borrower"
        if "g-1" in filename or "g-02" in filename or "guarantor" in filename:
            return "guarantor"
    if "owner of proprietorship concern" in text or "positions in business/roles owner" in text:
        return "borrower"
    if "type customer id guarantor" in text or "positions in business/roles type customer id guarantor" in text:
        return "guarantor"
    if "guarantor name" in text and "net worth" in text:
        return "guarantor_group"
    if "borrower's name" in text or "name of the a/c" in text or "applicant's name" in text:
        return "case"
    return "unknown"

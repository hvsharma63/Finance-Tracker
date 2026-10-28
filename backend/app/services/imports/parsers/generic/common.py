"""Helpers shared by generic parsers."""

from __future__ import annotations

import re

from app.services.imports.candidates import ExtractedDocument, ParsedStatement
from app.services.imports.metadata import extract_account_hint, extract_balances, extract_period

_CARD_HINTS = re.compile(r"credit card|card statement|minimum amount due|total amount due|payment due date|"
                         r"credit limit|available credit limit", re.I)


def guess_statement_type(doc: ExtractedDocument) -> str:
    return "credit_card" if len(_CARD_HINTS.findall(doc.text[:20000])) >= 2 else "bank"


def apply_text_metadata(ps: ParsedStatement, doc: ExtractedDocument) -> None:
    text = doc.text[:50000]
    start, end = extract_period(text)
    ps.period_start = ps.period_start or start
    ps.period_end = ps.period_end or end
    ps.account_hint = ps.account_hint or extract_account_hint(text)
    if ps.statement_type == "bank":
        o, c = extract_balances(text)
        ps.opening_balance = ps.opening_balance if ps.opening_balance is not None else o
        ps.closing_balance = ps.closing_balance if ps.closing_balance is not None else c
    if ps.rows and (ps.period_start is None or ps.period_end is None):
        dates = [r.txn_date for r in ps.rows if r.txn_date]
        if dates:
            ps.period_start = ps.period_start or min(dates)
            ps.period_end = ps.period_end or max(dates)
            ps.warnings.append("Statement period not found in the document; using first and last transaction dates.")

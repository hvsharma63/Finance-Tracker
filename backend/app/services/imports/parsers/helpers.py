"""Small helpers shared by institution-specific parsers."""

from __future__ import annotations

import re
from decimal import Decimal

from app.core.dates import DateParseError, parse_date
from app.core.money import MoneyParseError, parse_amount
from app.services.imports.candidates import CandidateRow, ParsedStatement
from app.services.imports.normalization import detect_transaction_type, extract_reference
from app.services.imports.parsers.layout_engine import AnchorRow

AMT = r"-?[\d,]+\.\d{2}"


def dec(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        v, _ = parse_amount(text)
        return v
    except MoneyParseError:
        return None


def find_amount(pattern: str, text: str, group: int = 1) -> Decimal | None:
    m = re.search(pattern, text, re.I | re.S)
    return dec(m.group(group)) if m else None


def find_dates(pattern: str, text: str, formats: list[str] | None = None):
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None, None
    try:
        return parse_date(m.group(1), formats), parse_date(m.group(2), formats)
    except DateParseError:
        return None, None


def candidate(idx: int, a: AnchorRow, amount: Decimal | None, *, balance: Decimal | None = None,
              errors: list[str] | None = None, warnings: list[str] | None = None, raw: dict | None = None,
              reference: str | None = None) -> CandidateRow:
    desc = a.description
    return CandidateRow(
        row_index=idx, source_ref=a.source_ref, txn_date=a.txn_date, description=desc,
        reference=reference or extract_reference(desc),
        debit=-amount if amount is not None and amount < 0 else None,
        credit=amount if amount is not None and amount > 0 else None,
        amount=amount, balance=balance, transaction_type=detect_transaction_type(desc),
        raw={"line": a.line_text, **{k: " ".join(w.text for w in v) for k, v in a.amounts.items()},
             **{k: " ".join(v) for k, v in a.extra.items()}, **(raw or {})},
        errors=list(errors or []), warnings=list(warnings or []),
    )


def cross_check(ps: ParsedStatement, label: str, expected: Decimal | None, actual: Decimal) -> None:
    """Compare a statement summary figure with the sum of extracted rows; never alters rows."""
    if expected is None:
        return
    if expected != actual:
        ps.warnings.append(f"{label}: statement summary shows {expected}, extracted rows total {actual} "
                           f"(difference {actual - expected}). Some rows may be missing or misread.")
    else:
        ps.extra.setdefault("summary_checks", []).append(f"{label} = {expected} ✓")


def card_balance(value: Decimal | None, marker: str | None, ps: ParsedStatement, label: str) -> Decimal | None:
    """Card summary figures are amounts owed. Return holder-perspective balance (owed => negative)."""
    if value is None:
        return None
    m = (marker or "").upper()
    if m.startswith("CR"):
        return abs(value)
    if not m and value > 0:
        ps.warnings.append(f"{label} has no Dr/Cr marker; treated as an amount owed.")
    return -value

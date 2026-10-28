"""Best-effort statement metadata from document text (period, account hint, balances)."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from app.core.dates import DateParseError, parse_date
from app.core.money import MoneyParseError, parse_amount

_DATE = r"(\d{1,2}[/\-. ](?:\d{1,2}|[A-Za-z]{3,9})[/\-. ,]{1,2}\d{2,4}|\d{4}-\d{2}-\d{2})"
_PERIOD = re.compile(
    rf"(?:statement\s+(?:period|from|for)|period|from|for the period)\s*[:\-]?\s*(?:from\s*)?{_DATE}\s*"
    rf"(?:to|till|-|–|upto|through)\s*{_DATE}",
    re.I,
)
_ACCOUNT = re.compile(
    r"(?:a/?c(?:count)?\s*(?:no|number|#)?\.?|card\s*(?:no|number)\.?)\s*[:\-]?\s*([X*x\d][X*x\d\s\-]{3,24}\d{3,4})",
    re.I,
)
_AMT = r"(-?(?:₹|Rs\.?|INR)?\s?[\d,]+\.\d{2}\s?(?:Dr|Cr|DR|CR)?)"
_OPENING = re.compile(rf"opening\s+balance\s*[:\-]?\s*{_AMT}", re.I)
_CLOSING = re.compile(rf"closing\s+balance\s*[:\-]?\s*{_AMT}", re.I)


def _d(s: str) -> date | None:
    try:
        return parse_date(s.replace(",", " ").strip())
    except DateParseError:
        return None


def _a(s: str) -> Decimal | None:
    try:
        v, direction = parse_amount(s)
    except MoneyParseError:
        return None
    if v is None:
        return None
    return -abs(v) if direction == "DR" else v


def extract_period(text: str) -> tuple[date | None, date | None]:
    m = _PERIOD.search(text)
    if not m:
        return None, None
    return _d(m.group(1)), _d(m.group(2))


def extract_account_hint(text: str) -> str | None:
    m = _ACCOUNT.search(text)
    if not m:
        return None
    digits = re.sub(r"[^0-9]", "", m.group(1))
    return f"XX{digits[-4:]}" if len(digits) >= 4 else None


def extract_balances(text: str) -> tuple[Decimal | None, Decimal | None]:
    o = _OPENING.search(text)
    c = _CLOSING.search(text)
    return (_a(o.group(1)) if o else None), (_a(c.group(1)) if c else None)


def mask_identifier(s: str | None) -> str | None:
    """Never store more than the last four digits of an account or card number."""
    if not s:
        return None
    digits = re.sub(r"[^0-9]", "", s)
    return f"XX{digits[-4:]}" if len(digits) >= 4 else s[:8]

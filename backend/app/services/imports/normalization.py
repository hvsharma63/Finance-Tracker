"""Normalization of descriptions, transaction types, references and merchants."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")

# Order matters: first match wins.
_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("upi", re.compile(r"\bUPI\b|\bUPI[/-]", re.I)),
    ("neft", re.compile(r"\bNEFT\b", re.I)),
    ("rtgs", re.compile(r"\bRTGS\b", re.I)),
    ("imps", re.compile(r"\bIMPS\b|\bMMT\b", re.I)),
    ("atm", re.compile(r"\bATM\b|\bATW\b|\bNWD\b|CASH WDL|CASH WITHDRAWAL|\bEAW\b", re.I)),
    ("card_payment", re.compile(r"CC PAYMENT|CREDIT CARD PAYMENT|CARD PAYMENT|PAYMENT RECEIVED|BBPS.*CARD|AUTOPAY.*CARD|THANK YOU", re.I)),
    ("pos", re.compile(r"\bPOS\b|\bPCD\b|\bECOM\b", re.I)),
    ("ach", re.compile(r"\bACH\b|\bNACH\b|\bECS\b|\bSI\b-|STANDING INSTRUCTION|AUTOPAY", re.I)),
    ("interest", re.compile(r"\bINT\.?\s*(PD|CR|PAID)\b|INTEREST|\bINT\.?COLL", re.I)),
    ("fee", re.compile(r"CHARGE|CHRG|CHGS|\bFEE\b|\bGST\b|ANNUAL FEE|PENALTY|LATE PAYMENT", re.I)),
    ("cheque", re.compile(r"\bCHQ\b|CHEQUE|\bCLG\b|CLEARING", re.I)),
    ("cash_deposit", re.compile(r"CASH DEP|BY CASH|CASH DEPOSIT", re.I)),
    ("reversal", re.compile(r"REVERSAL|\bREV\b|REFUND|CHARGEBACK", re.I)),
]

_UTR = re.compile(r"\b([A-Z]{4}[NRH0-9][0-9A-Z]{10,21})\b")
_RRN = re.compile(r"(?<![0-9])([0-9]{12})(?![0-9])")
_IFSC_LIKE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

_MERCHANT_STOPWORDS = {
    "UPI", "DR", "CR", "P2M", "P2A", "P2P", "PAYMENT", "PAY", "NEFT", "IMPS", "RTGS", "MMT", "POS", "ECOM",
    "TRANSFER", "TO", "FROM", "BY", "TRF", "INB", "MB", "IB", "ACH", "NACH", "D", "C", "REF", "NA",
    "YESB", "ICIC", "HDFC", "SBIN", "UTIB", "KKBK", "PUNB", "BARB", "IDIB", "CNRB", "UBIN", "INDB", "PYTM",
    "AIRP", "IBKL", "FDRL", "AUBL", "ESFB", "RATN", "IDFB", "SENT", "USING", "VIA", "OK", "COLLECT",
}


def clean_text(s: str | None) -> str:
    return _WS.sub(" ", (s or "").replace(" ", " ")).strip()


def join_continuation(prev: str | None, extra: str | None) -> str:
    """Append a wrapped description line. No space is added around '/', '-', '@' separators."""
    a, b = clean_text(prev), clean_text(extra)
    if not a or not b:
        return a or b
    if a[-1] in "/-_@.:" or b[0] in "/-@":
        return a + b
    return f"{a} {b}"


def normalize_description(s: str | None) -> str:
    return clean_text(s)


def match_key(s: str | None) -> str:
    """Aggressive key for comparing descriptions: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def detect_transaction_type(description: str | None) -> str | None:
    d = description or ""
    for name, pat in _TYPE_PATTERNS:
        if pat.search(d):
            return name
    return None


def extract_reference(description: str | None) -> str | None:
    d = (description or "").upper()
    for m in _UTR.finditer(d):
        if not _IFSC_LIKE.match(m.group(1)):
            return m.group(1)
    m = _RRN.search(d)
    return m.group(1) if m else None


def extract_merchant(description: str | None) -> str | None:
    """Best-effort counterparty extraction from Indian narrations. Merchant aliases override this."""
    d = clean_text(description)
    if not d:
        return None
    parts = re.split(r"[/\-|*:]+", d)
    for raw in parts:
        p = raw.strip()
        if "@" in p:  # UPI VPA: use the handle before @ only if nothing better came first
            continue
        token = p.upper()
        if not token or token in _MERCHANT_STOPWORDS:
            continue
        if re.fullmatch(r"[0-9X ]+", token) or _IFSC_LIKE.match(token) or _UTR.fullmatch(token):
            continue
        if len(re.sub(r"[^A-Z]", "", token)) < 3:
            continue
        name = re.sub(r"\s{2,}", " ", p).strip(" .")
        return name[:200].title() if name.isupper() else name[:200]
    for raw in parts:
        if "@" in raw:
            return raw.split("@")[0].strip()[:200] or None
    return None

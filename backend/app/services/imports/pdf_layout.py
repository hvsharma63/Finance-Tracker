"""Positional parsing of statement PDFs (and OCR output) using word coordinates.

Many bank PDFs draw transaction tables without ruling lines, so table detection fails. This
module finds the column header line, records each column's x-span, and assigns every numeric
token to the nearest amount column. Continuation lines extend the previous row's description.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.dates import DateParseError, parse_date
from app.core.money import MoneyParseError, parse_amount
from app.services.imports.candidates import CandidateRow, ExtractedPage, Word
from app.services.imports.layout import group_lines, is_amount, merge_amount_suffixes
from app.services.imports.normalization import (
    clean_text,
    detect_transaction_type,
    extract_reference,
    join_continuation,
)
from app.services.imports.table_mapping import CLOSING_PAT, OPENING_PAT, TOTAL_PAT, header_role

AMOUNT_ROLES = ("debit", "credit", "amount", "balance")
FOOTER_PAT = re.compile(r"page \d+ (of|/) \d+|computer generated|does not require.*signature|"
                        r"^\*+|registered office|customer care|toll free|www\.|end of statement", re.I)


@dataclass
class Column:
    role: str
    x0: float
    x1: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class LayoutHeader:
    columns: list[Column]
    labels: list[str]

    def get(self, role: str) -> Column | None:
        return next((c for c in self.columns if c.role == role), None)

    @property
    def roles(self) -> set[str]:
        return {c.role for c in self.columns}


@dataclass
class LayoutResult:
    rows: list[CandidateRow] = field(default_factory=list)
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    ignored_lines: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    header_labels: list[str] = field(default_factory=list)
    mode: str = "none"  # columns | balance_delta | none


def _detect_header(line: list[Word]) -> LayoutHeader | None:
    cols: list[Column] = []
    labels: list[str] = []
    used = set()
    i = 0
    while i < len(line):
        matched = False
        for span in (3, 2, 1):  # prefer the longest multi-word header ("Withdrawal Amt (INR)")
            j = i + span
            if j > len(line):
                continue
            group = line[i:j]
            if any(group[k + 1].x0 - group[k].x1 > 10 for k in range(len(group) - 1)):
                continue
            role = header_role(" ".join(w.text for w in group))
            if role and role not in used:
                cols.append(Column(role, group[0].x0, group[-1].x1))
                labels.append(" ".join(w.text for w in group))
                used.add(role)
                i = j
                matched = True
                break
        if not matched:
            i += 1
    roles = {c.role for c in cols}
    has_amount = ("debit" in roles and "credit" in roles) or "amount" in roles
    if "date" in roles and has_amount and ("description" in roles or "balance" in roles):
        return LayoutHeader(sorted(cols, key=lambda c: c.x0), labels)
    return None


def _leading_date(line: list[Word]):
    """Return (date, number_of_tokens) if the line starts with a date of 1-3 tokens."""
    for n in (3, 2, 1):
        if len(line) >= n:
            txt = " ".join(w.text for w in line[:n])
            try:
                d = parse_date(txt)
                if d:
                    return d, n
            except DateParseError:
                continue
    return None, 0


def _nearest_amount_column(word: Word, header: LayoutHeader) -> Column | None:
    candidates = [c for c in header.columns if c.role in AMOUNT_ROLES]
    if not candidates:
        return None
    # Amount columns are usually right-aligned: compare right edges as well as centres.
    return min(candidates, key=lambda c: min(abs(word.x1 - c.x1), abs(word.xc - c.xc)))


def _to_amount(text: str, errors: list[str]):
    try:
        return parse_amount(text)
    except MoneyParseError:
        errors.append(f"Could not read amount {text!r}")
        return None, None


def parse_pages(pages: list[ExtractedPage]) -> LayoutResult:
    res = LayoutResult()
    header: LayoutHeader | None = None
    last: CandidateRow | None = None
    last_bottom = 0.0
    idx = 0
    for page in pages:
        lines = [merge_amount_suffixes(ln) for ln in group_lines(page.words)]
        page_header_seen = False
        for li, line in enumerate(lines):
            text = clean_text(" ".join(w.text for w in line))
            ref = f"page:{page.number}:line:{li + 1}"
            h = _detect_header(line)
            if h is not None:
                header, page_header_seen = h, True
                res.header_labels = h.labels
                last = None
                continue
            if header is None:
                continue
            if FOOTER_PAT.search(text):
                res.ignored_lines.append({"ref": ref, "text": text[:200], "reason": "page header/footer"})
                last = None
                continue
            d, ntok = _leading_date(line)
            if d is None:
                amounts = [w for w in line if is_amount(w.text)]
                if OPENING_PAT.search(text) and amounts:
                    v, dr = _to_amount(amounts[-1].text, res.warnings)
                    if v is not None:
                        res.opening_balance = -abs(v) if dr == "DR" else v
                    res.ignored_lines.append({"ref": ref, "text": text[:200], "reason": "opening balance"})
                    continue
                if (CLOSING_PAT.search(text) or TOTAL_PAT.search(text)) and amounts:
                    if CLOSING_PAT.search(text):
                        v, dr = _to_amount(amounts[-1].text, res.warnings)
                        if v is not None:
                            res.closing_balance = -abs(v) if dr == "DR" else v
                    res.ignored_lines.append({"ref": ref, "text": text[:200], "reason": "summary/total"})
                    last = None
                    continue
                desc_col = header.get("description")
                in_desc = desc_col is not None and line[0].x0 >= desc_col.x0 - 15 and not amounts
                close = last is not None and line[0].top - last_bottom < 18
                if last is not None and in_desc and close:
                    extra = " ".join(w.text for w in line)
                    last.description = join_continuation(last.description, extra)
                    last.raw.setdefault("_continuation", []).append(extra)
                    last_bottom = max(w.bottom for w in line)
                else:
                    res.ignored_lines.append({"ref": ref, "text": text[:200], "reason": "no date"})
                continue

            errors: list[str] = []
            warnings: list[str] = []
            rest = line[ntok:]
            posting_date = None
            pd_col = header.get("posting_date")
            if pd_col is not None and rest:
                pd, pn = _leading_date(rest)
                if pd is not None and abs(rest[0].x0 - pd_col.x0) < 40:
                    posting_date, rest = pd, rest[pn:]
            values: dict[str, list[str]] = {}
            desc_words, ref_words = [], []
            ref_col = header.get("reference")
            first_amount_x = min((c.x0 for c in header.columns if c.role in AMOUNT_ROLES), default=1e9)
            for w in rest:
                if is_amount(w.text) and w.x1 >= first_amount_x - 5:
                    col = _nearest_amount_column(w, header)
                    values.setdefault(col.role, []).append(w.text)
                elif ref_col is not None and abs(w.xc - ref_col.xc) < max(25, (ref_col.x1 - ref_col.x0)) and \
                        not (header.get("description") and abs(w.xc - header.get("description").xc) < abs(w.xc - ref_col.xc)):
                    ref_words.append(w.text)
                else:
                    desc_words.append(w.text)
            for role, toks in values.items():
                if len(toks) > 1:
                    errors.append(f"Several values fell into the {role} column: {toks}")
            debit = credit = amount = balance = None
            if "debit" in values:
                v, _ = _to_amount(values["debit"][0], errors)
                debit = abs(v) if v else None
            if "credit" in values:
                v, _ = _to_amount(values["credit"][0], errors)
                credit = abs(v) if v else None
            if "amount" in values:
                v, dr = _to_amount(values["amount"][0], errors)
                if v is not None:
                    if dr == "DR":
                        debit = abs(v)
                    elif dr == "CR":
                        credit = abs(v)
                    else:
                        errors.append("Amount has no Dr/Cr marker; direction unknown — set it manually")
                        warnings.append("Direction unknown")
            if debit is not None and credit is not None:
                errors.append("Row has both a debit and a credit amount")
            elif debit is not None:
                amount = -debit
            elif credit is not None:
                amount = credit
            elif not errors:
                errors.append("No amount found on this line")
            if "balance" in values:
                v, dr = _to_amount(values["balance"][-1], warnings)
                if v is not None:
                    balance = -abs(v) if dr == "DR" else v
            description = clean_text(" ".join(desc_words))
            reference = clean_text(" ".join(ref_words)) or extract_reference(description)
            last = CandidateRow(
                row_index=idx, source_ref=ref, txn_date=d, posting_date=posting_date,
                description=description, reference=reference or None, debit=debit, credit=credit,
                amount=amount, balance=balance, transaction_type=detect_transaction_type(description),
                raw={"line": text, **{f"col_{k}": v for k, v in values.items()}},
                errors=errors, warnings=warnings + (["OCR text"] if page.ocr else []),
            )
            last_bottom = max(w.bottom for w in line)
            res.rows.append(last)
            idx += 1
        if header is not None and not page_header_seen and page.number > 1:
            res.warnings.append(f"Page {page.number}: no column header; reused the previous page's columns.")
    if header is not None:
        res.mode = "columns"
    return res


def parse_balance_delta(pages: list[ExtractedPage], opening: Decimal | None) -> LayoutResult:
    """Fallback for headerless layouts: '<date> <description> <amount> <balance>' lines.

    Direction is inferred from the change in running balance and flagged on every row.
    """
    res = LayoutResult(mode="balance_delta")
    prev_balance = opening
    idx = 0
    for page in pages:
        for li, line in enumerate(merge_amount_suffixes(ln) for ln in group_lines(page.words)):
            text = clean_text(" ".join(w.text for w in line))
            d, ntok = _leading_date(line)
            nums = [w for w in line[ntok:] if is_amount(w.text)]
            if OPENING_PAT.search(text) and nums and d is None:
                v, dr = _to_amount(nums[-1].text, res.warnings)
                if v is not None:
                    res.opening_balance = prev_balance = -abs(v) if dr == "DR" else v
                continue
            if d is None or len(nums) < 2:
                if d is not None:
                    res.ignored_lines.append({"ref": f"page:{page.number}:line:{li + 1}", "text": text[:200],
                                              "reason": "dated line without amount and balance"})
                continue
            errors: list[str] = []
            amt, adir = _to_amount(nums[-2].text, errors)
            bal, bdir = _to_amount(nums[-1].text, errors)
            if bal is not None and bdir == "DR":
                bal = -abs(bal)
            amount = None
            warnings = ["Direction inferred from running-balance change — please verify"]
            if amt is not None:
                if adir in ("DR", "CR"):
                    amount = -abs(amt) if adir == "DR" else abs(amt)
                    warnings = []
                elif prev_balance is not None and bal is not None:
                    delta = bal - prev_balance
                    if delta == abs(amt):
                        amount = abs(amt)
                    elif delta == -abs(amt):
                        amount = -abs(amt)
                    else:
                        errors.append("Amount does not match the balance change; direction unknown")
                else:
                    errors.append("Direction unknown (no previous balance)")
            desc_words = [w.text for w in line[ntok:] if w not in nums[-2:]]
            description = clean_text(" ".join(desc_words))
            res.rows.append(CandidateRow(
                row_index=idx, source_ref=f"page:{page.number}:line:{li + 1}", txn_date=d,
                description=description, reference=extract_reference(description),
                debit=-amount if amount is not None and amount < 0 else None,
                credit=amount if amount is not None and amount > 0 else None,
                amount=amount, balance=bal, transaction_type=detect_transaction_type(description),
                raw={"line": text}, errors=errors, warnings=warnings,
            ))
            prev_balance = bal if bal is not None else prev_balance
            idx += 1
    return res

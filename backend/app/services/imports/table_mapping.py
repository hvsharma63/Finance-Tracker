"""Generic tabular statement interpretation.

Finds the header row, maps columns to roles, and converts rows to CandidateRows. Used by the
generic CSV/Excel/PDF-table parsers and by user-saved parser profiles.

Roles: date, posting_date, description, debit, credit, amount, drcr, balance, reference.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.dates import DateParseError, parse_date
from app.core.money import MoneyParseError, parse_amount
from app.services.imports.candidates import CandidateRow, ExtractedTable
from app.services.imports.normalization import (
    clean_text,
    detect_transaction_type,
    extract_reference,
    join_continuation,
)

ROLES = ("date", "posting_date", "description", "debit", "credit", "amount", "drcr", "balance", "reference")

SYNONYMS: dict[str, list[str]] = {
    "date": ["date", "txn date", "transaction date", "tran date", "trans date", "txn dt", "tran dt",
             "transaction dt", "date of transaction", "trxn date", "entry date"],
    "posting_date": ["value date", "value dt", "posting date", "post date", "posted date", "settlement date"],
    "description": ["narration", "description", "particulars", "details", "transaction details",
                    "remarks", "transaction remarks", "transaction description", "transaction particulars",
                    "description narration", "merchant", "merchant name"],
    "debit": ["debit", "withdrawal", "withdrawals", "withdrawal amt", "withdrawal amount", "debit amount",
              "debit amt", "dr amount", "dr", "debits", "amount debited", "withdrawal inr", "withdrawal amt inr",
              "withdrawal amount inr", "debit inr", "money out", "paid out"],
    "credit": ["credit", "deposit", "deposits", "deposit amt", "deposit amount", "credit amount", "credit amt",
               "cr amount", "cr", "credits", "amount credited", "deposit inr", "deposit amt inr",
               "deposit amount inr", "credit inr", "money in", "paid in"],
    "amount": ["amount", "transaction amount", "amount inr", "amt", "txn amount", "amount rs", "billing amount",
               "amount in rs", "inr amount", "transaction amount inr"],
    "drcr": ["dr cr", "cr dr", "debit credit", "dr cr indicator", "type", "txn type", "transaction type"],
    "balance": ["balance", "closing balance", "running balance", "available balance", "balance inr",
                "balance amount", "balance amt", "closing bal", "bal"],
    "reference": ["ref no", "chq ref no", "cheque no", "chq no", "reference", "reference no", "ref no cheque no",
                  "chq no ref no", "cheque ref no", "utr", "utr no", "transaction id", "ref", "instrument id",
                  "chq ref number", "reference number", "tran id"],
}

OPENING_PAT = re.compile(r"opening balance|balance b/?f|brought forward|b/f balance|^b/f$|balance forward", re.I)
CLOSING_PAT = re.compile(r"closing balance|balance c/?f|carried forward|^c/f$", re.I)
DR_WORDS = {"DR", "D", "DEBIT", "WITHDRAWAL", "W", "DEBITED"}
CR_WORDS = {"CR", "C", "CREDIT", "DEPOSIT", "CREDITED"}
TOTAL_PAT = re.compile(r"^(grand )?totals?\b|^statement summary|^total (debits?|credits?|withdrawals?|deposits?)", re.I)


def norm_header(v: Any) -> str:
    s = str(v or "").lower().replace("\n", " ")
    s = re.sub(r"\(.*?\)", lambda m: " " + m.group(0)[1:-1] + " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(rs|in)\b", lambda m: "rs" if m.group(0) == "rs" else "in", s)
    return re.sub(r"\s+", " ", s).strip()


_SYNONYM_INDEX = {norm_header(syn): role for role, syns in SYNONYMS.items() for syn in syns}


def header_role(cell: Any) -> str | None:
    h = norm_header(cell)
    if not h:
        return None
    if h in _SYNONYM_INDEX:
        return _SYNONYM_INDEX[h]
    for syn, role in sorted(_SYNONYM_INDEX.items(), key=lambda kv: -len(kv[0])):
        if len(syn) >= 5 and (h.startswith(syn + " ") or h.endswith(" " + syn)):
            return role
    return None


def header_signature(headers: list[str]) -> str:
    key = "|".join(norm_header(h) for h in headers if norm_header(h))
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class HeaderMatch:
    table_index: int
    row_index: int
    headers: list[str]
    mapping: dict[str, int]  # role -> column index
    score: float


def auto_map(headers: list[Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for i, h in enumerate(headers):
        role = header_role(h)
        if role and role not in mapping:
            mapping[role] = i
        elif role == "date" and "posting_date" not in mapping:
            mapping["posting_date"] = i
    return mapping


def mapping_is_usable(m: dict[str, int]) -> bool:
    has_amount = ("debit" in m and "credit" in m) or "amount" in m
    return "date" in m and "description" in m and has_amount


def find_header(tables: list[ExtractedTable], scan_rows: int = 60) -> HeaderMatch | None:
    best: HeaderMatch | None = None
    for ti, t in enumerate(tables):
        for ri, row in enumerate(t.rows[:scan_rows]):
            if not row:
                continue
            m = auto_map(row)
            score = len(m) + (3 if mapping_is_usable(m) else 0)
            if mapping_is_usable(m) and (best is None or score > best.score):
                best = HeaderMatch(ti, ri, [clean_text(str(c or "")) for c in row], m, score)
    return best


def candidate_headers(tables: list[ExtractedTable], limit: int = 5) -> list[dict]:
    """Rows that look like headers (mostly text, several non-empty cells), for manual mapping."""
    found = []
    for ti, t in enumerate(tables):
        for ri, row in enumerate(t.rows[:40]):
            cells = [clean_text(str(c)) for c in row if c not in (None, "")]
            if len(cells) >= 3 and sum(1 for c in cells if re.search(r"[A-Za-z]", c)) >= len(cells) - 1:
                found.append({"table_index": ti, "row_index": ri, "headers": [clean_text(str(c or "")) for c in row]})
                break
        if len(found) >= limit:
            break
    return found


def resolve_mapping(headers: list[str], by_name: dict[str, str]) -> dict[str, int]:
    """Convert a role->header-name mapping (as saved in a profile) to role->column index."""
    idx = {norm_header(h): i for i, h in enumerate(headers)}
    out = {}
    for role, name in by_name.items():
        if role in ROLES and name is not None and norm_header(name) in idx:
            out[role] = idx[norm_header(name)]
    return out


@dataclass
class TableParseResult:
    rows: list[CandidateRow] = field(default_factory=list)
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    ignored_lines: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _cell(row: list, idx: int | None):
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _raw_dict(headers: list[str], row: list) -> dict:
    out = {}
    for i, v in enumerate(row):
        key = headers[i] if i < len(headers) and headers[i] else f"col{i + 1}"
        if v is None or v == "":
            continue
        out[key] = v.isoformat() if isinstance(v, datetime) else (str(v) if not isinstance(v, str) else v)
    return out


def _amount(v, label: str, errors: list[str]) -> tuple[Decimal | None, str | None]:
    try:
        return parse_amount(v)
    except MoneyParseError:
        errors.append(f"Could not read {label} amount {v!r}")
        return None, None


def parse_rows(
    tables: list[ExtractedTable],
    header: HeaderMatch,
    mapping: dict[str, int],
    *,
    sign_mode: str = "signed",
    date_format: str | None = None,
    continuation_tables: bool = True,
) -> TableParseResult:
    """Convert table rows below the header into candidate rows.

    sign_mode applies only to a single 'amount' column without Dr/Cr information:
      signed   -> negative = money out (bank style)
      inverted -> positive = money out (typical credit-card exports: purchases positive)
    """
    res = TableParseResult()
    headers = header.headers
    ncols = len(headers)
    fmts = [date_format] if date_format else None

    sources: list[tuple[ExtractedTable, int]] = [(tables[header.table_index], header.row_index + 1)]
    if continuation_tables:
        for t in tables[header.table_index + 1:]:
            if t.rows and abs(len(t.rows[0]) - ncols) <= 0:
                sources.append((t, 0))

    header_norm = [norm_header(h) for h in headers]
    idx = 0
    last: CandidateRow | None = None
    for table, start in sources:
        for ri in range(start, len(table.rows)):
            row = list(table.rows[ri] or [])
            ref = f"{table.source}:row:{ri + 1}"
            texts = [clean_text(str(c)) if c is not None else "" for c in row]
            if not any(texts):
                continue
            if [norm_header(c) for c in row] == header_norm:
                continue  # header repeated on a new page
            date_raw = _cell(row, mapping.get("date"))
            desc_raw = _cell(row, mapping.get("description"))
            joined = " ".join(t for t in texts if t)

            amount_cells = {r: _cell(row, mapping.get(r)) for r in ("debit", "credit", "amount", "balance")}
            has_amount = any(amount_cells[r] is not None for r in ("debit", "credit", "amount"))

            # Opening / closing balance and totals rows are statement metadata, not transactions.
            label = clean_text(str(desc_raw or joined))
            if OPENING_PAT.search(label):
                bal = amount_cells["balance"] or amount_cells["amount"] or amount_cells["credit"] or amount_cells["debit"]
                v, d = _amount(bal, "opening balance", res.warnings) if bal is not None else (None, None)
                if v is not None:
                    res.opening_balance = -abs(v) if d == "DR" else v
                res.ignored_lines.append({"ref": ref, "text": joined[:200], "reason": "opening balance row"})
                continue
            if CLOSING_PAT.search(label) or TOTAL_PAT.search(label):
                if CLOSING_PAT.search(label):
                    bal = amount_cells["balance"] or amount_cells["amount"]
                    v, d = _amount(bal, "closing balance", res.warnings) if bal is not None else (None, None)
                    if v is not None:
                        res.closing_balance = -abs(v) if d == "DR" else v
                res.ignored_lines.append({"ref": ref, "text": joined[:200], "reason": "summary/total row"})
                continue

            if date_raw is None and not has_amount:
                if last is not None and desc_raw:
                    last.description = join_continuation(last.description, str(desc_raw))
                    last.raw.setdefault("_continuation", []).append(str(desc_raw))
                else:
                    res.ignored_lines.append({"ref": ref, "text": joined[:200], "reason": "no date or amount"})
                continue

            errors: list[str] = []
            warnings: list[str] = []
            txn_date = None
            try:
                txn_date = parse_date(date_raw, fmts)
                if txn_date is None:
                    errors.append("Missing transaction date")
            except DateParseError:
                if not has_amount:
                    res.ignored_lines.append({"ref": ref, "text": joined[:200], "reason": "unparseable non-amount row"})
                    continue
                errors.append(f"Could not read date {date_raw!r}")
            posting_date = None
            if "posting_date" in mapping:
                try:
                    posting_date = parse_date(_cell(row, mapping["posting_date"]), fmts)
                except DateParseError:
                    warnings.append("Could not read value/posting date")

            debit = credit = amount = None
            if "debit" in mapping or "credit" in mapping:
                dv, _ = _amount(amount_cells["debit"], "debit", errors)
                cv, _ = _amount(amount_cells["credit"], "credit", errors)
                debit = abs(dv) if dv is not None and dv != 0 else None
                credit = abs(cv) if cv is not None and cv != 0 else None
                if dv is not None and dv < 0 or cv is not None and cv < 0:
                    warnings.append("Negative value inside a debit/credit column; magnitude used")
                if debit is not None and credit is not None:
                    errors.append("Row has both a debit and a credit amount")
                elif debit is not None:
                    amount = -debit
                elif credit is not None:
                    amount = credit
                elif "amount" not in mapping and not errors:
                    errors.append("No debit or credit amount")
            if amount is None and "amount" in mapping and amount_cells["amount"] is not None:
                av, direction = _amount(amount_cells["amount"], "transaction", errors)
                drcr_val = clean_text(str(_cell(row, mapping.get("drcr")) or "")).upper().rstrip(".")
                if drcr_val in DR_WORDS:
                    direction = direction or "DR"
                elif drcr_val in CR_WORDS:
                    direction = direction or "CR"
                elif drcr_val and "drcr" in mapping:
                    warnings.append(f"Unrecognised Dr/Cr indicator {drcr_val!r}")
                if av is not None:
                    if direction == "DR":
                        amount = -abs(av)
                    elif direction == "CR":
                        amount = abs(av)
                    else:
                        amount = -av if sign_mode == "inverted" else av
                        if sign_mode == "inverted":
                            warnings.append("Sign taken as 'positive = money out' (inverted mode)")
                    debit = -amount if amount < 0 else None
                    credit = amount if amount > 0 else None
            if amount is None and not errors:
                errors.append("No amount found")
            if amount is not None and amount == 0:
                warnings.append("Zero amount")

            balance = None
            if amount_cells["balance"] is not None:
                bv, bdir = _amount(amount_cells["balance"], "balance", warnings)
                if bv is not None:
                    balance = -abs(bv) if bdir == "DR" else bv

            description = clean_text(str(desc_raw)) if desc_raw is not None else ""
            if not description:
                warnings.append("Empty description")
            reference = clean_text(str(_cell(row, mapping.get("reference")) or "")) or extract_reference(description)
            if reference and re.fullmatch(r"0+", reference):
                reference = None
            last = CandidateRow(
                row_index=idx,
                source_ref=ref,
                txn_date=txn_date,
                posting_date=posting_date,
                description=description,
                reference=reference or None,
                debit=debit,
                credit=credit,
                amount=amount,
                balance=balance,
                transaction_type=detect_transaction_type(description),
                raw=_raw_dict(headers, row),
                errors=errors,
                warnings=warnings,
            )
            res.rows.append(last)
            idx += 1
    return res

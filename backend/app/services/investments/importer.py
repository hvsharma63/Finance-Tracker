"""Generic tabular import of investment transactions and valuations (CSV/XLSX).

Always run with dry_run=True first to preview; committing is idempotent through fingerprints.
Institution-specific statement parsers (e.g. CAS, broker contract notes) will be added in
parsers/investments once real sample formats are available.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dates import DateParseError, parse_date
from app.core.errors import AppError
from app.core.money import MoneyParseError, parse_amount, to_minor
from app.models import ImportBatch, InvestmentInstrument, InvestmentTransaction, InvestmentValuation
from app.models.investments import INSTRUMENT_TYPES, INVESTMENT_TXN_TYPES
from app.services.imports import extraction, storage
from app.services.imports.table_mapping import norm_header

TXN_SYNONYMS = {
    "date": ["date", "trade date", "transaction date", "txn date", "order date"],
    "identifier": ["isin", "symbol", "scheme code", "identifier", "ticker", "scrip code", "security id"],
    "name": ["name", "instrument", "scheme", "scheme name", "security", "stock", "fund", "company", "security name"],
    "type": ["type", "transaction type", "trade type", "buy sell", "action", "txn type", "side"],
    "quantity": ["quantity", "qty", "units", "shares"],
    "price": ["price", "rate", "nav", "unit price", "trade price", "avg price", "purchase price"],
    "amount": ["amount", "value", "trade value", "net amount", "gross amount", "total"],
    "charges": ["charges", "brokerage", "fees", "stamp duty", "total charges"],
    "instrument_type": ["asset class", "instrument type", "category", "asset type"],
    "split_ratio": ["ratio", "split ratio"],
}
VAL_SYNONYMS = {
    "date": ["date", "nav date", "valuation date", "as on", "price date", "as of"],
    "identifier": TXN_SYNONYMS["identifier"],
    "name": TXN_SYNONYMS["name"],
    "price": ["nav", "price", "close", "closing price", "market price", "ltp", "unit price"],
    "value": ["market value", "current value", "value", "valuation"],
    "quantity": ["units", "quantity", "qty", "balance units", "closing units"],
}
TYPE_WORDS = {
    "buy": "buy", "b": "buy", "purchase": "buy", "sip": "buy", "sip purchase": "buy", "subscription": "buy",
    "sell": "sell", "s": "sell", "sale": "sell", "redemption": "redemption", "redeem": "redemption",
    "dividend": "dividend", "dividend payout": "dividend", "interest": "interest", "reinvest": "reinvestment",
    "dividend reinvestment": "reinvestment", "reinvestment": "reinvestment", "bonus": "bonus", "split": "split",
    "charges": "charge", "charge": "charge", "tax": "tax", "stt": "tax", "maturity": "maturity",
    "switch in": "transfer_in", "switch out": "transfer_out", "transfer in": "transfer_in",
    "transfer out": "transfer_out",
}


def _map(headers: list, synonyms: dict) -> dict[str, int]:
    out = {}
    idx = {syn: role for role, syns in synonyms.items() for syn in syns}
    for i, h in enumerate(headers):
        role = idx.get(norm_header(h))
        if role and role not in out:
            out[role] = i
    return out


def _find(tables, synonyms, required) -> tuple[int, int, dict] | None:
    for ti, t in enumerate(tables):
        for ri, row in enumerate(t.rows[:40]):
            m = _map(row, synonyms)
            if all(r in m for r in required):
                return ti, ri, m
    return None


def _dec(v) -> Decimal | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        d, _ = parse_amount(v)
        return abs(d) if d is not None else None
    except (MoneyParseError, InvalidOperation):
        raise ValueError(f"Not a number: {v!r}")


def _instrument(db: Session, identifier: str | None, name: str | None, itype: str | None, cache: dict,
                create: bool) -> InvestmentInstrument | None:
    key = (identifier or name or "").strip().upper()
    if not key:
        return None
    if key in cache:
        return cache[key]
    inst = db.scalar(select(InvestmentInstrument).where(InvestmentInstrument.identifier == key))
    if inst is None and name:
        inst = db.scalar(select(InvestmentInstrument).where(InvestmentInstrument.name.ilike(name.strip())))
    if inst is None and create:
        t = (itype or "").lower().replace(" ", "_")
        t = {"equity": "stock", "shares": "stock", "mf": "mutual_fund", "fund": "mutual_fund"}.get(t, t)
        if t not in INSTRUMENT_TYPES:
            t = "mutual_fund" if re.match(r"^INF", key) else "stock" if re.match(r"^INE", key) else "other"
        inst = InvestmentInstrument(name=(name or key).strip()[:200], identifier=key[:60], instrument_type=t)
        db.add(inst)
        db.flush()
    cache[key] = inst
    return inst


def _fp(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def import_file(db: Session, data: bytes, filename: str, account_id: int, kind: str, dry_run: bool = True) -> dict:
    """kind = 'transactions' or 'valuations'."""
    doc = extraction.extract(data, filename)
    if doc.file_type == "pdf":
        raise AppError("PDF investment statements need an institution parser; export CSV/Excel or share a sample.")
    syn, required = (TXN_SYNONYMS, ["date", "type"]) if kind == "transactions" else (VAL_SYNONYMS, ["date"])
    found = _find(doc.tables, syn, required)
    if found is None:
        raise AppError(f"Could not find a header row. Expected columns like: {', '.join(syn)}", code="needs_mapping")
    ti, ri, m = found
    if "identifier" not in m and "name" not in m:
        raise AppError("The file needs an ISIN/symbol or instrument name column", code="needs_mapping")
    rows_out, errors, created, skipped = [], [], 0, 0
    cache: dict = {}
    batch = None
    if not dry_run:
        ref, _ = storage.store(data, doc.file_type)
        batch = ImportBatch(account_id=account_id, filename=filename[:200], file_hash=storage.sha256(data),
                            file_type=doc.file_type, file_size=len(data), storage_reference=ref, status="committed",
                            parser_name=f"investment_{kind}_table", parser_version="1.0", detected_statement_type="investment")
        db.add(batch)
        db.flush()
    for i, row in enumerate(doc.tables[ti].rows[ri + 1:], start=ri + 2):
        def cell(role, row=row):
            j = m.get(role)
            return row[j] if j is not None and j < len(row) else None
        if not any(c not in (None, "") for c in row):
            continue
        try:
            d = parse_date(cell("date"))
            if d is None:
                raise ValueError("missing date")
            ident = str(cell("identifier") or "").strip() or None
            name = str(cell("name") or "").strip() or None
            if kind == "transactions":
                raw_type = norm_header(cell("type"))
                ttype = TYPE_WORDS.get(raw_type, raw_type if raw_type in INVESTMENT_TXN_TYPES else None)
                if ttype is None:
                    raise ValueError(f"unknown transaction type {cell('type')!r}")
                qty, price = _dec(cell("quantity")), _dec(cell("price"))
                amount = _dec(cell("amount"))
                if amount is None and qty is not None and price is not None:
                    amount = (qty * price).quantize(Decimal("0.01"))
                charges = _dec(cell("charges")) or Decimal(0)
                ratio = _dec(cell("split_ratio"))
                if ttype in ("buy", "sell", "redemption", "reinvestment") and (qty is None or amount is None):
                    raise ValueError("buy/sell rows need quantity and amount (or price)")
                rec = {"row": i, "date": d.isoformat(), "identifier": ident, "name": name, "type": ttype,
                       "quantity": str(qty) if qty is not None else None, "unit_price": str(price) if price is not None else None,
                       "gross_amount_minor": to_minor(amount or 0), "charges_minor": to_minor(charges)}
                fp = _fp(account_id, d, (ident or name or "").upper(), ttype, qty, rec["gross_amount_minor"])
                exists = db.scalar(select(InvestmentTransaction.id).where(InvestmentTransaction.fingerprint == fp))
                rec["duplicate"] = exists is not None
                if not dry_run and not exists:
                    inst = _instrument(db, ident, name, str(cell("instrument_type") or ""), cache, True)
                    db.add(InvestmentTransaction(
                        account_id=account_id, instrument_id=inst.id, transaction_date=d, transaction_type=ttype,
                        quantity=qty, unit_price=price, gross_amount_minor=rec["gross_amount_minor"],
                        charges_minor=rec["charges_minor"], split_ratio=ratio, fingerprint=fp,
                        import_batch_id=batch.id))
                    created += 1
                elif exists:
                    skipped += 1
            else:
                price, value, qty = _dec(cell("price")), _dec(cell("value")), _dec(cell("quantity"))
                if price is None and value is None:
                    raise ValueError("needs a price/NAV or a market value")
                rec = {"row": i, "date": d.isoformat(), "identifier": ident, "name": name,
                       "unit_price": str(price) if price is not None else None,
                       "total_value_minor": to_minor(value) if value is not None else None,
                       "quantity": str(qty) if qty is not None else None}
                if not dry_run:
                    inst = _instrument(db, ident, name, None, cache, False)
                    if inst is None:
                        raise ValueError("instrument not found — import its transactions first")
                    dup = db.scalar(select(InvestmentValuation.id).where(
                        InvestmentValuation.instrument_id == inst.id, InvestmentValuation.valuation_date == d,
                        InvestmentValuation.unit_price == price, InvestmentValuation.total_value_minor == rec["total_value_minor"]))
                    if dup:
                        skipped += 1
                    else:
                        db.add(InvestmentValuation(instrument_id=inst.id, account_id=account_id, valuation_date=d,
                                                   quantity=qty, unit_price=price, total_value_minor=rec["total_value_minor"],
                                                   source="user_import", import_batch_id=batch.id,
                                                   notes=f"Imported from {filename[:100]}"))
                        created += 1
            rows_out.append(rec)
        except (ValueError, DateParseError) as e:
            errors.append({"row": i, "error": str(e), "values": [str(c) for c in row if c not in (None, "")][:10]})
    if batch is not None:
        batch.row_counts = {"extracted": len(rows_out) + len(errors), "accepted": created, "rejected": len(errors),
                            "duplicates_skipped": skipped}
    db.flush()
    return {"dry_run": dry_run, "kind": kind, "columns": {k: str(doc.tables[ti].rows[ri][v]) for k, v in m.items()},
            "rows": rows_out[:1000], "row_count": len(rows_out), "errors": errors, "created": created,
            "skipped_duplicates": skipped, "import_batch_id": batch.id if batch else None}

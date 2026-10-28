"""Duplicate detection for staged import rows against the ledger.

exact    — same account, date, amount, normalized description, running balance and occurrence
           ordinal. Excluded from commit by default (overlapping / repeated statements).
possible — same account and amount, date within the configured window, not exactly equal.
           Kept for import but flagged for review; nothing is dropped silently.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImportRow, Transaction
from app.services.imports.normalization import match_key


def fingerprint(account_id: int, txn_date, amount_minor: int, description: str | None,
                balance_minor: int | None, ordinal: int) -> str:
    key = f"{account_id}|{txn_date}|{amount_minor}|{match_key(description)}|{'' if balance_minor is None else balance_minor}|{ordinal}"
    return hashlib.sha256(key.encode()).hexdigest()


def assign_fingerprints(account_id: int, rows: list[ImportRow]) -> None:
    seen: dict[tuple, int] = defaultdict(int)
    for r in sorted(rows, key=lambda r: r.row_index):
        if r.txn_date is None or r.amount_minor is None:
            r.fingerprint = None
            continue
        base = (r.txn_date, r.amount_minor, match_key(r.description), r.balance_minor)
        r.fingerprint = fingerprint(account_id, r.txn_date, r.amount_minor, r.description, r.balance_minor, seen[base])
        seen[base] += 1


def detect_duplicates(db: Session, account_id: int, rows: list[ImportRow], window_days: int = 2,
                      exclude_batch_id: int | None = None) -> dict:
    assign_fingerprints(account_id, rows)
    dated = [r for r in rows if r.txn_date is not None and r.amount_minor is not None]
    for r in rows:
        r.duplicate_status, r.duplicate_of_transaction_id = "none", None
    try:
        return _detect(db, account_id, dated, window_days, exclude_batch_id)
    finally:
        for r in rows:
            r.include = r.include_override if r.include_override is not None else r.duplicate_status != "exact"


def _detect(db: Session, account_id: int, dated: list[ImportRow], window_days: int,
            exclude_batch_id: int | None) -> dict:
    if not dated:
        return {"exact": 0, "possible": 0}
    lo = min(r.txn_date for r in dated) - timedelta(days=window_days)
    hi = max(r.txn_date for r in dated) + timedelta(days=window_days)
    q = select(Transaction).where(
        Transaction.account_id == account_id,
        Transaction.transaction_date.between(lo, hi),
        Transaction.duplicate_status != "duplicate",
    )
    if exclude_batch_id is not None:
        q = q.where((Transaction.import_batch_id.is_(None)) | (Transaction.import_batch_id != exclude_batch_id))
    existing = list(db.scalars(q))
    by_fp = {t.fingerprint: t for t in existing if t.fingerprint}
    used: set[int] = set()
    exact = possible = 0
    for r in dated:
        t = by_fp.get(r.fingerprint)
        if t is not None and t.id not in used:
            used.add(t.id)
            r.duplicate_status, r.duplicate_of_transaction_id = "exact", t.id
            exact += 1
    for r in dated:
        if r.duplicate_status == "exact":
            continue
        for t in existing:
            if t.id in used or t.amount_minor != r.amount_minor:
                continue
            if abs((t.transaction_date - r.txn_date).days) <= window_days:
                used.add(t.id)
                r.duplicate_status, r.duplicate_of_transaction_id = "possible", t.id
                possible += 1
                break
    return {"exact": exact, "possible": possible}

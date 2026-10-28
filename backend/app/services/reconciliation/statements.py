"""Statement reconciliation: reported opening + signed movements = reported closing.

Never modifies transactions; only records the outcome and the difference.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImportRow, Statement, Transaction


def statement_movements(db: Session, statement: Statement) -> int:
    """Sum of every movement printed on the statement, including rows already in the ledger
    from an overlapping import (exact duplicates)."""
    rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == statement.import_batch_id))
    total = 0
    for r in rows:
        if r.status == "error" and r.transaction_id is None:
            continue
        if r.transaction_id is not None:
            t = db.get(Transaction, r.transaction_id)
            if t is not None and t.duplicate_status != "duplicate":
                total += t.amount_minor
        elif r.duplicate_status == "exact" and r.duplicate_of_transaction_id is not None:
            t = db.get(Transaction, r.duplicate_of_transaction_id)
            total += t.amount_minor if t is not None else (r.amount_minor or 0)
        elif r.include and r.amount_minor is not None:
            total += r.amount_minor
    return total


def reconcile(db: Session, statement: Statement) -> Statement:
    if statement.reported_opening_minor is None:
        statement.calculated_closing_minor = None
        statement.discrepancy_minor = None
        statement.reconciliation_status = "unverifiable"
        return statement
    calc = statement.reported_opening_minor + statement_movements(db, statement)
    statement.calculated_closing_minor = calc
    if statement.reported_closing_minor is None:
        statement.discrepancy_minor = None
        statement.reconciliation_status = "unverifiable"
    else:
        statement.discrepancy_minor = statement.reported_closing_minor - calc
        statement.reconciliation_status = "reconciled" if statement.discrepancy_minor == 0 else "discrepancy"
    return statement

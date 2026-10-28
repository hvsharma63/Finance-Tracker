"""Resolve every transaction into reporting parts. See docs/CONVENTIONS.md.

A transaction may split into several parts: e.g. ₹50,000 out of which ₹30,000 is an approved
transfer and the remaining ₹20,000 follows the transaction's category.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Account, Category, Transaction, TransactionRelationship
from app.models.ledger import MOVEMENT_RELATIONSHIPS

REL_CLASS = {
    "transfer": "transfer",
    "card_payment": "card_payment",
    "investment_contribution": "investment",
    "investment_withdrawal": "investment",
    "loan_payment": "loan_principal",
}
CATEGORY_CLASS = {
    "income": "income", "expense": "expense", "transfer": "transfer", "investment": "investment",
    "loan_principal": "loan_principal", "refund": "refund", "cash_withdrawal": "cash_withdrawal",
    "excluded": "excluded",
}


@dataclass
class Part:
    transaction_id: int
    account_id: int
    date: date
    cls: str
    amount_minor: int  # signed, holder perspective
    category_id: int | None
    merchant: str | None
    description: str


def _sign(x: int) -> int:
    return 1 if x >= 0 else -1


def classify(db: Session, txns: list[Transaction]) -> list[Part]:
    if not txns:
        return []
    ids = [t.id for t in txns]
    cats = {c.id: c for c in db.scalars(select(Category))}
    rels_by_txn: dict[int, list[TransactionRelationship]] = defaultdict(list)
    for chunk_start in range(0, len(ids), 5000):
        chunk = ids[chunk_start:chunk_start + 5000]
        for r in db.scalars(select(TransactionRelationship).where(
                TransactionRelationship.review_status == "approved",
                or_(TransactionRelationship.source_transaction_id.in_(chunk),
                    TransactionRelationship.related_transaction_id.in_(chunk)))):
            if r.source_transaction_id in chunk:
                rels_by_txn[r.source_transaction_id].append(r)
            if r.related_transaction_id in chunk and r.related_transaction_id != r.source_transaction_id:
                rels_by_txn[r.related_transaction_id].append(r)
    refund_sources = {r.source_transaction_id for rs in rels_by_txn.values() for r in rs if r.relationship_type == "refund"}
    source_cat = {t.id: t.category_id for t in db.scalars(select(Transaction).where(Transaction.id.in_(refund_sources)))} \
        if refund_sources else {}

    parts: list[Part] = []
    for t in txns:
        if t.duplicate_status == "duplicate":
            continue
        remaining = t.amount_minor
        base = dict(transaction_id=t.id, account_id=t.account_id, date=t.transaction_date, merchant=t.merchant,
                    description=t.normalized_description)
        for r in rels_by_txn.get(t.id, []):
            if remaining == 0:
                break
            portion = min(abs(r.matched_amount_minor or 0), abs(remaining))
            if portion == 0:
                continue
            signed = _sign(remaining) * portion
            if r.relationship_type in MOVEMENT_RELATIONSHIPS:
                parts.append(Part(cls=REL_CLASS[r.relationship_type], amount_minor=signed, category_id=t.category_id, **base))
                remaining -= signed
            elif r.relationship_type == "refund" and r.related_transaction_id == t.id and t.amount_minor > 0:
                parts.append(Part(cls="refund", amount_minor=signed,
                                  category_id=source_cat.get(r.source_transaction_id) or t.category_id, **base))
                remaining -= signed
        if remaining != 0:
            cat = cats.get(t.category_id) if t.category_id else None
            cls = CATEGORY_CLASS.get(cat.reporting_type, "uncategorized") if cat else "uncategorized"
            parts.append(Part(cls=cls, amount_minor=remaining, category_id=t.category_id, **base))
    return parts


def ledger_transactions(db: Session, start: date | None = None, end: date | None = None,
                        account_ids: list[int] | None = None) -> list[Transaction]:
    q = select(Transaction).where(Transaction.duplicate_status != "duplicate")
    if start:
        q = q.where(Transaction.transaction_date >= start)
    if end:
        q = q.where(Transaction.transaction_date <= end)
    if account_ids:
        q = q.where(Transaction.account_id.in_(account_ids))
    return list(db.scalars(q.order_by(Transaction.transaction_date, Transaction.id)))


def account_map(db: Session) -> dict[int, Account]:
    return {a.id: a for a in db.scalars(select(Account))}

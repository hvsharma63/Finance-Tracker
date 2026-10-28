from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api import serializers as ser
from app.api.deps import paginate, protected_router
from app.core.db import get_db
from app.core.errors import AppError, get_or_404
from app.models import Account, Statement, Transaction, TransactionRelationship
from app.models.ledger import RELATIONSHIP_TYPES
from app.services.ledger.seed import get_setting
from app.services.reconciliation import matching
from app.services.reconciliation.statements import reconcile

router = protected_router(prefix="/reconciliation", tags=["reconciliation"])


def _acct_names(db):
    return {a.id: a.name for a in db.scalars(select(Account))}


@router.get("/relationships")
def list_relationships(status: str = "suggested", relationship_type: str | None = None, transaction_id: int | None = None,
                       page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    q = select(TransactionRelationship).options(selectinload(TransactionRelationship.source),
                                                selectinload(TransactionRelationship.related))
    if status != "all":
        q = q.where(TransactionRelationship.review_status == status)
    if relationship_type:
        q = q.where(TransactionRelationship.relationship_type == relationship_type)
    if transaction_id:
        q = q.where(or_(TransactionRelationship.source_transaction_id == transaction_id,
                        TransactionRelationship.related_transaction_id == transaction_id))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    offset, limit = paginate(page, page_size)
    names = _acct_names(db)
    rows = db.scalars(q.order_by(TransactionRelationship.score.desc().nulls_last(), TransactionRelationship.id)
                      .offset(offset).limit(limit))
    return {"total": total, "items": [ser.relationship(r, account_names=names) for r in rows],
            "matching_window_days": get_setting(db, "matching_window_days", 5)}


@router.post("/suggest")
def run_suggestions(db: Session = Depends(get_db)):
    created = matching.suggest_matches(db)
    db.commit()
    return {"created": len(created)}


class ApproveIn(BaseModel):
    matched_amount_minor: int | None = None


@router.post("/relationships/{rid}/approve")
def approve(rid: int, body: ApproveIn | None = None, db: Session = Depends(get_db)):
    r = matching.approve(db, rid, body.matched_amount_minor if body else None)
    db.commit()
    return ser.relationship(r, account_names=_acct_names(db))


@router.post("/relationships/{rid}/reject")
def reject(rid: int, db: Session = Depends(get_db)):
    r = matching.reject(db, rid)
    db.commit()
    return ser.relationship(r, account_names=_acct_names(db))


@router.post("/relationships/{rid}/undo")
def undo(rid: int, db: Session = Depends(get_db)):
    r = matching.undo(db, rid)
    db.commit()
    return ser.relationship(r, account_names=_acct_names(db))


class ManualLink(BaseModel):
    source_transaction_id: int
    related_transaction_id: int
    relationship_type: str
    matched_amount_minor: int | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/relationships", status_code=201)
def create_link(body: ManualLink, db: Session = Depends(get_db)):
    if body.relationship_type not in RELATIONSHIP_TYPES:
        raise AppError(f"relationship_type must be one of {RELATIONSHIP_TYPES}")
    if body.source_transaction_id == body.related_transaction_id:
        raise AppError("A transaction cannot be linked to itself")
    r = matching.create_manual(db, body.source_transaction_id, body.related_transaction_id, body.relationship_type,
                               body.matched_amount_minor, body.notes)
    db.commit()
    return ser.relationship(r, account_names=_acct_names(db))


@router.get("/candidates/{txn_id}")
def candidates(txn_id: int, db: Session = Depends(get_db)):
    """Possible counterparts for manual linking: opposite sign, other accounts, similar amount and date."""
    t = get_or_404(db, Transaction, txn_id, "Transaction")
    window = int(get_setting(db, "matching_window_days", 5)) * 3
    from datetime import timedelta
    q = select(Transaction).where(
        Transaction.id != t.id, Transaction.duplicate_status != "duplicate",
        Transaction.transaction_date.between(t.transaction_date - timedelta(days=window),
                                             t.transaction_date + timedelta(days=window)),
        func.abs(Transaction.amount_minor).between(int(abs(t.amount_minor) * 0.5), int(abs(t.amount_minor) * 1.5) + 1))
    names = _acct_names(db)
    rows = sorted(db.scalars(q), key=lambda c: (abs(abs(c.amount_minor) - abs(t.amount_minor)),
                                                abs((c.transaction_date - t.transaction_date).days)))
    return [ser.transaction(c, account_names=names) for c in rows[:50]]


@router.get("/unmatched")
def unmatched(account_id: int | None = None, page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    """Transactions that look like transfers/card payments but have no approved match."""
    q = select(Transaction).where(Transaction.reconciliation_status == "unreconciled",
                                  Transaction.duplicate_status != "duplicate",
                                  Transaction.transaction_type.in_(("neft", "imps", "rtgs", "upi", "card_payment", "ach")))
    if account_id:
        q = q.where(Transaction.account_id == account_id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    offset, limit = paginate(page, page_size)
    names = _acct_names(db)
    return {"total": total, "items": [ser.transaction(t, account_names=names) for t in
                                      db.scalars(q.order_by(Transaction.transaction_date.desc()).offset(offset).limit(limit))]}


@router.get("/statements")
def statements(account_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Statement)
    if account_id:
        q = q.where(Statement.account_id == account_id)
    names = _acct_names(db)
    return [ser.statement(s) | {"account_name": names.get(s.account_id)}
            for s in db.scalars(q.order_by(Statement.account_id, Statement.end_date.desc()))]


@router.post("/statements/{sid}/recheck")
def recheck_statement(sid: int, db: Session = Depends(get_db)):
    s = get_or_404(db, Statement, sid, "Statement")
    reconcile(db, s)
    db.commit()
    return ser.statement(s)


class MarkDuplicate(BaseModel):
    original_transaction_id: int
    duplicate_transaction_id: int


@router.post("/mark-duplicate")
def mark_duplicate(body: MarkDuplicate, db: Session = Depends(get_db)):
    """Record that one committed transaction duplicates another. The duplicate stays stored but leaves the ledger."""
    a = get_or_404(db, Transaction, body.original_transaction_id, "Transaction")
    b = get_or_404(db, Transaction, body.duplicate_transaction_id, "Transaction")
    if a.account_id != b.account_id or a.amount_minor != b.amount_minor:
        raise AppError("Duplicates must be in the same account with the same amount")
    r = matching.create_manual(db, a.id, b.id, "duplicate", abs(a.amount_minor))
    db.commit()
    return ser.relationship(r, account_names=_acct_names(db))

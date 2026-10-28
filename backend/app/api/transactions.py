from datetime import date

from fastapi import Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import paginate, protected_router
from app.core.db import get_db
from app.core.errors import AppError, Conflict, get_or_404
from app.models import Account, AuditEvent, Category, Transaction, TransactionRelationship
from app.services.categorization.engine import apply_rules, propose_rule
from app.services.imports.normalization import detect_transaction_type, normalize_description
from app.services.ledger import audit
from app.services.reconciliation.matching import suggest_matches
from app.services.reporting import exports
from app.services.reporting.classification import classify

router = protected_router(prefix="/transactions", tags=["transactions"])

SORTS = {
    "date": Transaction.transaction_date, "amount": Transaction.amount_minor,
    "description": Transaction.normalized_description, "merchant": Transaction.merchant,
    "created": Transaction.created_at,
}


def _filtered(account_id=None, start=None, end=None, category_id=None, uncategorized=None, q=None,
              direction=None, review_status=None, reconciliation_status=None, min_amount=None, max_amount=None,
              import_batch_id=None, tag=None, include_duplicates=False, ids=None):
    stmt = select(Transaction)
    if not include_duplicates:
        stmt = stmt.where(Transaction.duplicate_status != "duplicate")
    if ids:
        stmt = stmt.where(Transaction.id.in_(ids))
    if account_id:
        stmt = stmt.where(Transaction.account_id.in_(account_id))
    if start:
        stmt = stmt.where(Transaction.transaction_date >= start)
    if end:
        stmt = stmt.where(Transaction.transaction_date <= end)
    if category_id:
        stmt = stmt.where(Transaction.category_id.in_(category_id))
    if uncategorized:
        stmt = stmt.where(Transaction.category_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Transaction.normalized_description.ilike(like), Transaction.merchant.ilike(like),
                              Transaction.reference.ilike(like), Transaction.notes.ilike(like)))
    if direction in ("debit", "credit"):
        stmt = stmt.where(Transaction.direction == direction)
    if review_status:
        stmt = stmt.where(Transaction.review_status == review_status)
    if reconciliation_status:
        stmt = stmt.where(Transaction.reconciliation_status == reconciliation_status)
    if min_amount is not None:
        stmt = stmt.where(func.abs(Transaction.amount_minor) >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(func.abs(Transaction.amount_minor) <= max_amount)
    if import_batch_id:
        stmt = stmt.where(Transaction.import_batch_id == import_batch_id)
    if tag:
        stmt = stmt.where(Transaction.tags.contains([tag]))
    return stmt


def _names(db: Session):
    cats = {c.id: c.name for c in db.scalars(select(Category))}
    accts = {a.id: a.name for a in db.scalars(select(Account))}
    return cats, accts


@router.get("")
def list_transactions(
    account_id: list[int] = Query(None), start: date | None = None, end: date | None = None,
    category_id: list[int] = Query(None), uncategorized: bool | None = None, q: str | None = Query(None, max_length=200),
    direction: str | None = None, review_status: str | None = None, reconciliation_status: str | None = None,
    min_amount: int | None = None, max_amount: int | None = None, import_batch_id: int | None = None,
    tag: str | None = None, reporting_class: str | None = None, include_duplicates: bool = False,
    ids: list[int] = Query(None),
    sort: str = "date", order: str = "desc", page: int = 1, page_size: int = 50, db: Session = Depends(get_db),
):
    stmt = _filtered(account_id, start, end, category_id, uncategorized, q, direction, review_status,
                     reconciliation_status, min_amount, max_amount, import_batch_id, tag, include_duplicates, ids)
    col = SORTS.get(sort, Transaction.transaction_date)
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), Transaction.id.desc())
    cats, accts = _names(db)
    if reporting_class:
        # class filter needs classification; done in Python over the filtered set
        all_txns = list(db.scalars(stmt))
        keep = {p.transaction_id for p in classify(db, all_txns) if p.cls == reporting_class}
        all_txns = [t for t in all_txns if t.id in keep]
        offset, limit = paginate(page, page_size)
        return {"total": len(all_txns), "page": page, "page_size": limit,
                "items": [ser.transaction(t, cats, accts) for t in all_txns[offset:offset + limit]]}
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    offset, limit = paginate(page, page_size)
    items = list(db.scalars(stmt.offset(offset).limit(limit)))
    classes = {}
    for p in classify(db, items):
        classes.setdefault(p.transaction_id, []).append({"class": p.cls, "amount_minor": p.amount_minor})
    out = []
    for t in items:
        d = ser.transaction(t, cats, accts)
        d["reporting_parts"] = classes.get(t.id, [])
        out.append(d)
    return {"total": total, "page": page, "page_size": limit, "items": out}


@router.get("/review-queue")
def review_queue(page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    """Uncategorized or unreviewed transactions."""
    stmt = select(Transaction).where(Transaction.duplicate_status != "duplicate",
                                     or_(Transaction.category_id.is_(None), Transaction.review_status == "pending"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    offset, limit = paginate(page, page_size)
    cats, accts = _names(db)
    items = db.scalars(stmt.order_by(Transaction.category_id.is_(None).desc(), Transaction.transaction_date.desc())
                       .offset(offset).limit(limit))
    return {"total": total, "items": [ser.transaction(t, cats, accts) for t in items]}


@router.get("/export")
def export_transactions(fmt: str = Query("csv", pattern="^(csv|xlsx)$"), account_id: list[int] = Query(None),
                        start: date | None = None, end: date | None = None, q: str | None = None,
                        category_id: list[int] = Query(None), db: Session = Depends(get_db)):
    stmt = _filtered(account_id, start, end, category_id, None, q).order_by(Transaction.transaction_date, Transaction.id)
    cats, accts = _names(db)
    txns = list(db.scalars(stmt))
    classes = {}
    for p in classify(db, txns):
        classes.setdefault(p.transaction_id, []).append(p.cls)
    cols = ["id", "date", "posting_date", "account", "description", "original_description", "merchant", "amount",
            "currency", "direction", "category", "reporting_class", "type", "reference", "tags", "notes",
            "reconciliation_status", "source_ref"]
    rows = [[t.id, t.transaction_date, t.posting_date, accts.get(t.account_id), t.normalized_description,
             t.original_description, t.merchant, exports.rupees(t.amount_minor), t.currency, t.direction,
             cats.get(t.category_id), "+".join(classes.get(t.id, [])), t.transaction_type, t.reference,
             ", ".join(t.tags or []), t.notes, t.reconciliation_status, t.source_row_reference] for t in txns]
    if fmt == "xlsx":
        data = exports.to_xlsx({"Transactions": (cols, rows)})
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = exports.to_csv(cols, [[ser.iso(c) for c in r] for r in rows])
        media = "text/csv; charset=utf-8"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="transactions.{fmt}"'})


@router.get("/{txn_id}")
def get_transaction(txn_id: int, db: Session = Depends(get_db)):
    t = get_or_404(db, Transaction, txn_id, "Transaction")
    cats, accts = _names(db)
    d = ser.transaction(t, cats, accts)
    d["source_data"] = t.source_data
    rels = db.scalars(select(TransactionRelationship).where(
        or_(TransactionRelationship.source_transaction_id == t.id, TransactionRelationship.related_transaction_id == t.id)))
    d["relationships"] = [ser.relationship(r, account_names=accts) for r in rels]
    d["reporting_parts"] = [{"class": p.cls, "amount_minor": p.amount_minor} for p in classify(db, [t])]
    d["history"] = [{"at": ser.iso(e.occurred_at), "action": e.action, "details": e.details}
                    for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "transaction",
                                                                 AuditEvent.entity_id == t.id).order_by(AuditEvent.id))]
    return d


class TxnPatch(BaseModel):
    category_id: int | None = None
    notes: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    merchant: str | None = Field(default=None, max_length=200)
    normalized_description: str | None = Field(default=None, max_length=2000)
    review_status: str | None = Field(default=None, pattern="^(pending|reviewed)$")
    transaction_date: date | None = None
    amount_minor: int | None = None


@router.patch("/{txn_id}")
def update_transaction(txn_id: int, body: TxnPatch, db: Session = Depends(get_db)):
    t = get_or_404(db, Transaction, txn_id, "Transaction")
    data = body.model_dump(exclude_unset=True)
    if "category_id" in data and data["category_id"] is not None:
        get_or_404(db, Category, data["category_id"], "Category")
    if "amount_minor" in data:
        if data["amount_minor"] is None or data["amount_minor"] == 0:
            raise AppError("Amount must be non-zero")
        approved = db.scalar(select(func.count()).select_from(TransactionRelationship).where(
            TransactionRelationship.review_status == "approved",
            or_(TransactionRelationship.source_transaction_id == t.id,
                TransactionRelationship.related_transaction_id == t.id)))
        if approved:
            raise Conflict("Undo this transaction's approved matches before changing its amount")
    before = {k: ser.iso(getattr(t, k)) for k in data}
    for k, v in data.items():
        if k == "tags":
            v = sorted({x.strip()[:40] for x in (v or []) if x.strip()})
        setattr(t, k, v)
    if "category_id" in data:
        t.category_source = "user" if data["category_id"] is not None else "none"
        t.rule_id = None
        t.review_status = "reviewed" if data["category_id"] is not None else t.review_status
    if "amount_minor" in data:
        t.direction = "debit" if t.amount_minor < 0 else "credit"
    if "normalized_description" in data:
        t.normalized_description = normalize_description(t.normalized_description)
    audit.record(db, "transaction", t.id, "updated",
                 {"before": before, "after": {k: ser.iso(getattr(t, k)) for k in data}})
    db.commit()
    cats, accts = _names(db)
    out = ser.transaction(t, cats, accts)
    if "category_id" in data and data["category_id"] is not None:
        out["rule_suggestion"] = propose_rule(t, data["category_id"]) | {
            "name": f"{t.merchant or (t.normalized_description or '')[:30]} → {cats.get(data['category_id'])}"}
    return out


class BulkCategorize(BaseModel):
    transaction_ids: list[int] = Field(min_length=1, max_length=5000)
    category_id: int | None
    mark_reviewed: bool = True


@router.post("/bulk-categorize")
def bulk_categorize(body: BulkCategorize, db: Session = Depends(get_db)):
    if body.category_id is not None:
        get_or_404(db, Category, body.category_id, "Category")
    txns = list(db.scalars(select(Transaction).where(Transaction.id.in_(body.transaction_ids))))
    for t in txns:
        before = t.category_id
        t.category_id = body.category_id
        t.category_source = "user" if body.category_id is not None else "none"
        t.rule_id = None
        if body.mark_reviewed:
            t.review_status = "reviewed"
        audit.record(db, "transaction", t.id, "categorized", {"before": before, "after": body.category_id, "bulk": True})
    db.commit()
    return {"updated": len(txns)}


class BulkReview(BaseModel):
    transaction_ids: list[int] = Field(min_length=1, max_length=5000)


@router.post("/bulk-review")
def bulk_review(body: BulkReview, db: Session = Depends(get_db)):
    n = 0
    for t in db.scalars(select(Transaction).where(Transaction.id.in_(body.transaction_ids))):
        t.review_status = "reviewed"
        n += 1
    db.commit()
    return {"updated": n}


class ManualTxn(BaseModel):
    account_id: int
    transaction_date: date
    description: str = Field(min_length=1, max_length=2000)
    amount_minor: int
    category_id: int | None = None
    notes: str | None = None
    tags: list[str] = []


@router.post("", status_code=201)
def create_manual(body: ManualTxn, db: Session = Depends(get_db)):
    """Manually recorded transaction (e.g. cash). Marked is_manual; never part of a statement."""
    a = get_or_404(db, Account, body.account_id, "Account")
    if body.amount_minor == 0:
        raise AppError("Amount must be non-zero")
    desc = normalize_description(body.description)
    t = Transaction(account_id=a.id, transaction_date=body.transaction_date, original_description=desc,
                    original_amount_minor=body.amount_minor, original_date=body.transaction_date,
                    normalized_description=desc, amount_minor=body.amount_minor, currency=a.currency,
                    direction="debit" if body.amount_minor < 0 else "credit",
                    transaction_type=detect_transaction_type(desc), category_id=body.category_id,
                    category_source="user" if body.category_id else "none", notes=body.notes,
                    tags=body.tags, is_manual=True, review_status="reviewed" if body.category_id else "pending",
                    source_data={"manual": True})
    db.add(t)
    db.flush()
    apply_rules(db, [t])
    suggest_matches(db, [t.id])
    audit.record(db, "transaction", t.id, "created_manual", {"amount_minor": t.amount_minor})
    db.commit()
    cats, accts = _names(db)
    return ser.transaction(t, cats, accts)


@router.delete("/{txn_id}")
def delete_manual(txn_id: int, db: Session = Depends(get_db)):
    t = get_or_404(db, Transaction, txn_id, "Transaction")
    if not t.is_manual:
        raise Conflict("Imported transactions are removed by deleting their import batch, not individually. "
                       "Mark a wrongly imported row as a duplicate or exclude it via its category instead.")
    db.execute(TransactionRelationship.__table__.delete().where(or_(
        TransactionRelationship.source_transaction_id == t.id, TransactionRelationship.related_transaction_id == t.id)))
    audit.record(db, "transaction", t.id, "deleted_manual", {"amount_minor": t.amount_minor})
    db.delete(t)
    db.commit()
    return {"deleted": txn_id}

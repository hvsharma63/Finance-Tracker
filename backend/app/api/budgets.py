from datetime import date

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import protected_router
from app.core.db import get_db
from app.core.errors import AppError, Conflict, get_or_404
from app.models import Budget, Category, RecurringTransaction
from app.services.reporting import reports as rpt

router = protected_router(tags=["budgets"])


class BudgetIn(BaseModel):
    category_id: int
    month: date | None = None  # any day in the month; None = default for every month
    amount_minor: int = Field(gt=0)


def _budget(b: Budget) -> dict:
    return {"id": b.id, "category_id": b.category_id, "month": b.month.isoformat()[:7] if b.month else None,
            "amount_minor": b.amount_minor}


@router.get("/budgets")
def list_budgets(db: Session = Depends(get_db)):
    return [_budget(b) for b in db.scalars(select(Budget).order_by(Budget.month.nulls_first(), Budget.category_id))]


@router.post("/budgets", status_code=201)
def create_budget(body: BudgetIn, db: Session = Depends(get_db)):
    cat = get_or_404(db, Category, body.category_id, "Category")
    if cat.reporting_type != "expense":
        raise AppError("Budgets apply to expense categories")
    b = Budget(category_id=body.category_id, month=body.month.replace(day=1) if body.month else None,
               amount_minor=body.amount_minor)
    db.add(b)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A budget for this category and month already exists")
    db.commit()
    return _budget(b)


class BudgetPatch(BaseModel):
    amount_minor: int = Field(gt=0)


@router.patch("/budgets/{bid}")
def update_budget(bid: int, body: BudgetPatch, db: Session = Depends(get_db)):
    b = get_or_404(db, Budget, bid, "Budget")
    b.amount_minor = body.amount_minor
    db.commit()
    return _budget(b)


@router.delete("/budgets/{bid}")
def delete_budget(bid: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Budget, bid, "Budget"))
    db.commit()
    return {"deleted": bid}


@router.get("/budgets/status")
def budget_status(month: date | None = None, db: Session = Depends(get_db)):
    """Budget vs actual net spending. A parent-category budget includes its subcategories."""
    today = rpt.today()
    m = (month or today).replace(day=1)
    end = rpt.month_end(m)
    cats = {c.id: c for c in db.scalars(select(Category))}
    budgets: dict[int, Budget] = {}
    for b in db.scalars(select(Budget).where((Budget.month.is_(None)) | (Budget.month == m))):
        if b.category_id not in budgets or b.month is not None:  # month-specific overrides default
            budgets[b.category_id] = b
    actual = {r["category_id"]: r["net_minor"] for r in rpt.category_breakdown(db, m, end)}
    out = []
    for cid, b in budgets.items():
        spent = actual.get(cid, 0) + sum(v for k, v in actual.items() if k and cats.get(k) and cats[k].parent_id == cid)
        days_total = end.day
        days_elapsed = days_total if end < today else (today - m).days + 1 if m <= today else 0
        projected = int(spent * days_total / days_elapsed) if 0 < days_elapsed < days_total else (spent if days_elapsed else None)
        out.append({"budget_id": b.id, "category_id": cid, "category": cats[cid].name if cid in cats else None,
                    "budget_minor": b.amount_minor, "spent_minor": spent, "remaining_minor": b.amount_minor - spent,
                    "percent_used": round(spent * 100 / b.amount_minor, 1), "projected_minor": projected,
                    "is_default": b.month is None})
    return {"month": m.isoformat()[:7], "items": sorted(out, key=lambda r: -r["percent_used"]),
            "note": "Projection is a straight-line extrapolation of spending so far this month."}


class RecurringIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    match_key: str = Field(min_length=1, max_length=200)
    account_id: int | None = None
    category_id: int | None = None
    expected_amount_minor: int = Field(gt=0)
    cadence: str = Field(default="monthly", pattern="^(weekly|monthly|quarterly|yearly)$")
    typical_day: int | None = Field(default=None, ge=1, le=31)
    last_seen_date: date | None = None


def _rec(r: RecurringTransaction) -> dict:
    return {"id": r.id, "name": r.name, "match_key": r.match_key, "account_id": r.account_id,
            "category_id": r.category_id, "expected_amount_minor": r.expected_amount_minor, "cadence": r.cadence,
            "typical_day": r.typical_day, "active": r.active,
            "last_seen_date": r.last_seen_date.isoformat() if r.last_seen_date else None}


@router.get("/recurring")
def list_recurring(db: Session = Depends(get_db)):
    return [_rec(r) for r in db.scalars(select(RecurringTransaction).order_by(RecurringTransaction.name))]


@router.post("/recurring", status_code=201)
def confirm_recurring(body: RecurringIn, db: Session = Depends(get_db)):
    """Confirm a detected recurring payment. Creates a definition only — never ledger transactions."""
    r = RecurringTransaction(**body.model_dump())
    db.add(r)
    db.commit()
    return _rec(r)


@router.delete("/recurring/{rid}")
def delete_recurring(rid: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, RecurringTransaction, rid, "Recurring definition"))
    db.commit()
    return {"deleted": rid}

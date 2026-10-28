from datetime import date

from fastapi import Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import protected_router
from app.core.db import get_db
from app.core.errors import AppError, Conflict, get_or_404
from app.models import Account, ImportBatch, InvestmentTransaction, Statement, Transaction
from app.models.ledger import ACCOUNT_TYPES, LIABILITY_TYPES
from app.services.imports.metadata import mask_identifier
from app.services.ledger import audit
from app.services.ledger.balances import account_balance, coverage_gaps

router = protected_router(prefix="/accounts", tags=["accounts"])


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    institution: str | None = Field(default=None, max_length=120)
    account_type: str
    custom_type_label: str | None = Field(default=None, max_length=60)
    is_liability: bool | None = None
    currency: str = Field(default="INR", min_length=3, max_length=3)
    masked_identifier: str | None = Field(default=None, max_length=30)
    opening_balance_minor: int | None = None
    opening_date: date | None = None
    opening_verification: str | None = None
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool = True

    @field_validator("account_type")
    @classmethod
    def _type(cls, v):
        if v not in ACCOUNT_TYPES:
            raise ValueError(f"account_type must be one of {ACCOUNT_TYPES}")
        return v

    @field_validator("opening_verification")
    @classmethod
    def _ver(cls, v):
        if v is not None and v not in ("unknown", "unverified", "verified"):
            raise ValueError("invalid opening_verification")
        return v


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    institution: str | None = None
    custom_type_label: str | None = None
    masked_identifier: str | None = None
    opening_balance_minor: int | None = None
    opening_date: date | None = None
    opening_verification: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    clear_opening_balance: bool = False


def _apply(a: Account, data: dict) -> None:
    if "masked_identifier" in data:
        data["masked_identifier"] = mask_identifier(data["masked_identifier"])
    for k, v in data.items():
        setattr(a, k, v)


@router.get("")
def list_accounts(include_inactive: bool = Query(True), db: Session = Depends(get_db)):
    q = select(Account).order_by(Account.is_active.desc(), Account.account_type, Account.name)
    if not include_inactive:
        q = q.where(Account.is_active.is_(True))
    return [ser.account(a, account_balance(db, a)) for a in db.scalars(q)]


@router.post("", status_code=201)
def create_account(body: AccountIn, db: Session = Depends(get_db)):
    data = body.model_dump()
    if data["is_liability"] is None:
        data["is_liability"] = data["account_type"] in LIABILITY_TYPES
    if data["opening_balance_minor"] is not None:
        data["opening_source"] = "user"
        data["opening_verification"] = data["opening_verification"] or "unverified"
    else:
        data["opening_verification"] = "unknown"
    a = Account()
    _apply(a, data)
    a.currency = a.currency.upper()
    db.add(a)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"An account named {body.name!r} already exists")
    audit.record(db, "account", a.id, "created", {"name": a.name, "type": a.account_type})
    db.commit()
    return ser.account(a, account_balance(db, a))


@router.get("/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db)):
    a = get_or_404(db, Account, account_id, "Account")
    d = ser.account(a, account_balance(db, a))
    d["coverage_gaps"] = [{"from": g[0].isoformat(), "to": g[1].isoformat()} for g in coverage_gaps(db, a.id)]
    d["statements"] = [ser.statement(s) for s in db.scalars(
        select(Statement).where(Statement.account_id == a.id).order_by(Statement.end_date.desc()))]
    return d


@router.patch("/{account_id}")
def update_account(account_id: int, body: AccountPatch, db: Session = Depends(get_db)):
    a = get_or_404(db, Account, account_id, "Account")
    data = body.model_dump(exclude_unset=True)
    clear = data.pop("clear_opening_balance", False)
    if clear:
        a.opening_balance_minor, a.opening_date, a.opening_source, a.opening_verification = None, None, None, "unknown"
    if "opening_balance_minor" in data or "opening_date" in data:
        data["opening_source"] = "user"
        if "opening_verification" not in data and a.opening_verification == "unknown":
            data["opening_verification"] = "unverified"
    if data.get("opening_verification") == "verified" and (data.get("opening_balance_minor", a.opening_balance_minor) is None):
        raise AppError("Set an opening balance before marking it verified")
    before = {k: ser.iso(getattr(a, k)) for k in data}
    _apply(a, data)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("An account with that name already exists")
    audit.record(db, "account", a.id, "updated", {"before": before, "after": {k: ser.iso(v) for k, v in data.items()}})
    db.commit()
    return ser.account(a, account_balance(db, a))


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    """Delete only an empty account; accounts with history must be deactivated instead."""
    a = get_or_404(db, Account, account_id, "Account")
    used = (db.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id == a.id)) or 0) + \
           (db.scalar(select(func.count()).select_from(ImportBatch).where(
               ImportBatch.account_id == a.id, ImportBatch.status.in_(("committed", "preview")))) or 0) + \
           (db.scalar(select(func.count()).select_from(InvestmentTransaction).where(
               InvestmentTransaction.account_id == a.id)) or 0)
    if used:
        raise Conflict("This account has transactions or imports. Delete those imports first, or deactivate the account.")
    db.execute(ImportBatch.__table__.update().where(ImportBatch.account_id == a.id).values(account_id=None))
    db.delete(a)
    audit.record(db, "account", account_id, "deleted", {"name": a.name})
    db.commit()
    return {"deleted": account_id}

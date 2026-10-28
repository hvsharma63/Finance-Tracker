from datetime import date
from decimal import Decimal

from fastapi import Depends, File, Form, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api import serializers as ser
from app.api.deps import protected_router
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError, Conflict, get_or_404
from app.models import (
    Account,
    FixedDeposit,
    InvestmentInstrument,
    InvestmentTransaction,
    InvestmentValuation,
    Transaction,
)
from app.models.investments import INSTRUMENT_TYPES, INVESTMENT_TXN_TYPES
from app.services.investments.holdings import compute_holdings, portfolio_summary, rebuild_lots
from app.services.investments.importer import import_file
from app.services.ledger import audit
from app.services.ledger.seed import category_by_path

router = protected_router(prefix="/investments", tags=["investments"])


class InstrumentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    instrument_type: str
    identifier: str = Field(min_length=1, max_length=60)
    symbol: str | None = None
    currency: str = "INR"
    issuer: str | None = None
    notes: str | None = None

    @field_validator("instrument_type")
    @classmethod
    def _t(cls, v):
        if v not in INSTRUMENT_TYPES:
            raise ValueError(f"instrument_type must be one of {INSTRUMENT_TYPES}")
        return v


@router.get("/instruments")
def list_instruments(db: Session = Depends(get_db)):
    return [ser.instrument(i) for i in db.scalars(select(InvestmentInstrument).order_by(InvestmentInstrument.name))]


@router.post("/instruments", status_code=201)
def create_instrument(body: InstrumentIn, db: Session = Depends(get_db)):
    i = InvestmentInstrument(**(body.model_dump() | {"identifier": body.identifier.strip().upper()}))
    db.add(i)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("An instrument with that identifier already exists")
    db.commit()
    return ser.instrument(i)


@router.patch("/instruments/{iid}")
def update_instrument(iid: int, body: InstrumentIn, db: Session = Depends(get_db)):
    i = get_or_404(db, InvestmentInstrument, iid, "Instrument")
    for k, v in body.model_dump().items():
        setattr(i, k, v)
    db.commit()
    return ser.instrument(i)


class InvTxnIn(BaseModel):
    account_id: int
    instrument_id: int | None = None
    transaction_date: date
    transaction_type: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    gross_amount_minor: int = Field(default=0, ge=0)
    charges_minor: int = Field(default=0, ge=0)
    split_ratio: Decimal | None = None
    source_transaction_id: int | None = None
    notes: str | None = None

    @field_validator("transaction_type")
    @classmethod
    def _t(cls, v):
        if v not in INVESTMENT_TXN_TYPES:
            raise ValueError(f"transaction_type must be one of {INVESTMENT_TXN_TYPES}")
        return v


def _validate_inv(body: InvTxnIn, db: Session):
    a = get_or_404(db, Account, body.account_id, "Account")
    if body.instrument_id:
        get_or_404(db, InvestmentInstrument, body.instrument_id, "Instrument")
    elif body.transaction_type not in ("charge", "tax", "contribution", "withdrawal", "interest", "other"):
        raise AppError("This transaction type needs an instrument")
    if body.transaction_type in ("buy", "sell", "redemption", "reinvestment", "bonus") and not body.quantity:
        raise AppError("Quantity is required for this transaction type")
    if body.quantity is not None and body.quantity < 0:
        raise AppError("Quantity must be positive; the transaction type sets the direction")
    if body.transaction_type == "split" and not body.split_ratio:
        raise AppError("Splits need split_ratio (new units per old unit)")
    if body.source_transaction_id:
        t = get_or_404(db, Transaction, body.source_transaction_id, "Transaction")
        if t.category_id is None and t.amount_minor < 0:
            cat = category_by_path(db, "Financial movements", "Investment purchases")
            if cat:
                t.category_id, t.category_source = cat.id, "rule"
    return a


@router.get("/transactions")
def list_inv_txns(account_id: int | None = None, instrument_id: int | None = None, db: Session = Depends(get_db)):
    q = select(InvestmentTransaction).options(selectinload(InvestmentTransaction.instrument))
    if account_id:
        q = q.where(InvestmentTransaction.account_id == account_id)
    if instrument_id:
        q = q.where(InvestmentTransaction.instrument_id == instrument_id)
    return [ser.investment_txn(t) for t in db.scalars(q.order_by(InvestmentTransaction.transaction_date.desc(),
                                                                 InvestmentTransaction.id.desc()))]


@router.post("/transactions", status_code=201)
def create_inv_txn(body: InvTxnIn, db: Session = Depends(get_db)):
    _validate_inv(body, db)
    t = InvestmentTransaction(**body.model_dump())
    db.add(t)
    db.flush()
    if t.instrument_id:
        rebuild_lots(db, t.account_id, t.instrument_id)
    audit.record(db, "investment_transaction", t.id, "created", {"type": t.transaction_type})
    db.commit()
    db.refresh(t)
    return ser.investment_txn(t)


@router.delete("/transactions/{tid}")
def delete_inv_txn(tid: int, db: Session = Depends(get_db)):
    t = get_or_404(db, InvestmentTransaction, tid, "Investment transaction")
    acct, inst = t.account_id, t.instrument_id
    db.delete(t)
    db.flush()
    if inst:
        rebuild_lots(db, acct, inst)
    audit.record(db, "investment_transaction", tid, "deleted")
    db.commit()
    return {"deleted": tid}


class ValuationIn(BaseModel):
    instrument_id: int
    account_id: int | None = None
    valuation_date: date
    unit_price: Decimal | None = Field(default=None, ge=0)
    total_value_minor: int | None = Field(default=None, ge=0)
    quantity: Decimal | None = None
    source: str = Field(default="manual", pattern="^(manual|statement|user_import)$")
    notes: str | None = Field(default=None, max_length=2000)


@router.get("/valuations")
def list_valuations(instrument_id: int | None = None, db: Session = Depends(get_db)):
    q = select(InvestmentValuation)
    if instrument_id:
        q = q.where(InvestmentValuation.instrument_id == instrument_id)
    return [ser.valuation(v) for v in db.scalars(q.order_by(InvestmentValuation.valuation_date.desc()))]


@router.post("/valuations", status_code=201)
def create_valuation(body: ValuationIn, db: Session = Depends(get_db)):
    get_or_404(db, InvestmentInstrument, body.instrument_id, "Instrument")
    if body.unit_price is None and body.total_value_minor is None:
        raise AppError("Provide a unit price or a total value")
    if body.source == "manual" and not body.notes:
        raise AppError("Manual valuations need a source note (e.g. 'AMC website NAV 28-Oct-2026')")
    v = InvestmentValuation(**body.model_dump())
    db.add(v)
    db.flush()
    audit.record(db, "valuation", v.id, "created", {"instrument_id": v.instrument_id, "date": str(v.valuation_date)})
    db.commit()
    return ser.valuation(v)


@router.delete("/valuations/{vid}")
def delete_valuation(vid: int, db: Session = Depends(get_db)):
    v = get_or_404(db, InvestmentValuation, vid, "Valuation")
    db.delete(v)
    db.commit()
    return {"deleted": vid}


@router.get("/holdings")
def holdings(as_of: date | None = None, account_id: int | None = None, db: Session = Depends(get_db)):
    return [h.to_dict() for h in compute_holdings(db, as_of, [account_id] if account_id else None)]


@router.get("/portfolio")
def portfolio(as_of: date | None = None, db: Session = Depends(get_db)):
    return portfolio_summary(db, as_of)


@router.post("/import")
async def import_investments(file: UploadFile = File(...), account_id: int = Form(...),
                             kind: str = Form("transactions"), dry_run: bool = Form(True), db: Session = Depends(get_db)):
    if kind not in ("transactions", "valuations"):
        raise AppError("kind must be transactions or valuations")
    get_or_404(db, Account, account_id, "Account")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError("File too large", status_code=413)
    result = import_file(db, data, file.filename or "investments.csv", account_id, kind, dry_run)
    if dry_run:
        db.rollback()
    else:
        for (acct, inst) in {(t.account_id, t.instrument_id) for t in db.scalars(select(InvestmentTransaction).where(
                InvestmentTransaction.import_batch_id == result["import_batch_id"]))}:
            rebuild_lots(db, acct, inst)
        db.commit()
    return result


# ------------------------------------------------------------------ fixed deposits

class FDIn(BaseModel):
    account_id: int
    principal_minor: int = Field(gt=0)
    opening_date: date
    maturity_date: date | None = None
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    compounding: str | None = Field(default=None, pattern="^(monthly|quarterly|half_yearly|yearly|simple)$")
    reported_maturity_value_minor: int | None = None
    reported_value_minor: int | None = None
    valuation_date: date | None = None
    status: str = Field(default="active", pattern="^(active|matured|closed)$")
    notes: str | None = None


def _fd(f: FixedDeposit) -> dict:
    return {k: ser.iso(getattr(f, k)) for k in ("id", "account_id", "principal_minor", "opening_date", "maturity_date",
                                                "interest_rate", "compounding", "reported_maturity_value_minor",
                                                "reported_value_minor", "valuation_date", "status", "notes")}


@router.get("/fixed-deposits")
def list_fds(db: Session = Depends(get_db)):
    return [_fd(f) for f in db.scalars(select(FixedDeposit).order_by(FixedDeposit.maturity_date))]


@router.post("/fixed-deposits", status_code=201)
def create_fd(body: FDIn, db: Session = Depends(get_db)):
    a = get_or_404(db, Account, body.account_id, "Account")
    if a.account_type != "fixed_deposit":
        raise AppError("Fixed deposit details must be attached to an account of type fixed_deposit")
    if body.reported_value_minor is not None and body.valuation_date is None:
        raise AppError("A reported value needs its valuation date")
    f = FixedDeposit(**body.model_dump())
    db.add(f)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("This account already has fixed deposit details")
    db.commit()
    return _fd(f)


@router.patch("/fixed-deposits/{fid}")
def update_fd(fid: int, body: FDIn, db: Session = Depends(get_db)):
    f = get_or_404(db, FixedDeposit, fid, "Fixed deposit")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(f, k, v)
    db.commit()
    return _fd(f)


@router.delete("/fixed-deposits/{fid}")
def delete_fd(fid: int, db: Session = Depends(get_db)):
    f = get_or_404(db, FixedDeposit, fid, "Fixed deposit")
    db.delete(f)
    db.commit()
    return {"deleted": fid}

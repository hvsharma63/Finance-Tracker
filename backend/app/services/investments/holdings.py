"""Holdings, weighted-average cost basis, realized gains and valuations.

Cost basis method: weighted average cost (WAC) per (account, instrument).
  buy / reinvestment / transfer_in : qty += q; cost += gross + charges
  sell / redemption / transfer_out : avg = cost/qty; cost -= avg*q; realized += gross - charges - avg*q
  split                            : qty *= ratio (cost unchanged)
  bonus                            : qty += q at zero cost
  maturity                         : closes the position like a full redemption
  dividend / interest              : income (no change to cost or quantity)
  charge / tax                     : recorded as costs of holding
Values come only from dated valuations. Missing valuation => value unknown (never cost).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FixedDeposit, InvestmentInstrument, InvestmentLot, InvestmentTransaction, InvestmentValuation

ZERO = Decimal(0)
ACQUIRE = {"buy", "reinvestment", "transfer_in", "contribution"}
DISPOSE = {"sell", "redemption", "transfer_out", "withdrawal"}


def qty_str(d: Decimal | None) -> str | None:
    """Plain decimal text without exponent or trailing zeros (40, 198.039)."""
    if d is None:
        return None
    s = format(d.normalize(), "f")
    return s if s not in ("-0", "") else "0"


def _r(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass
class Holding:
    account_id: int
    instrument_id: int
    instrument_name: str
    instrument_type: str
    identifier: str
    quantity: Decimal = ZERO
    cost_basis_minor: int = 0
    invested_minor: int = 0  # gross principal paid in (incl. charges)
    withdrawn_minor: int = 0  # gross proceeds received
    realized_gain_minor: int = 0
    dividends_minor: int = 0
    interest_minor: int = 0
    charges_minor: int = 0
    taxes_minor: int = 0
    first_date: date | None = None
    last_date: date | None = None
    valuation_date: date | None = None
    valuation_source: str | None = None
    unit_price: Decimal | None = None
    value_minor: int | None = None  # None = unknown
    warnings: list[str] = field(default_factory=list)

    @property
    def average_cost(self) -> Decimal | None:
        return (Decimal(self.cost_basis_minor) / self.quantity / 100) if self.quantity > 0 else None

    @property
    def unrealized_gain_minor(self) -> int | None:
        return None if self.value_minor is None else self.value_minor - self.cost_basis_minor

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id, "instrument_id": self.instrument_id,
            "instrument_name": self.instrument_name, "instrument_type": self.instrument_type,
            "identifier": self.identifier, "quantity": qty_str(self.quantity) or "0",
            "average_cost": str(self.average_cost.quantize(Decimal("0.0001"))) if self.average_cost is not None else None,
            "cost_basis_minor": self.cost_basis_minor, "invested_minor": self.invested_minor,
            "withdrawn_minor": self.withdrawn_minor, "realized_gain_minor": self.realized_gain_minor,
            "dividends_minor": self.dividends_minor, "interest_minor": self.interest_minor,
            "charges_minor": self.charges_minor, "taxes_minor": self.taxes_minor,
            "value_minor": self.value_minor, "value_known": self.value_minor is not None,
            "unrealized_gain_minor": self.unrealized_gain_minor,
            "valuation_date": self.valuation_date.isoformat() if self.valuation_date else None,
            "valuation_source": self.valuation_source,
            "unit_price": str(self.unit_price) if self.unit_price is not None else None,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "warnings": self.warnings,
        }


def compute_holdings(db: Session, as_of: date | None = None, account_ids: list[int] | None = None,
                     include_closed: bool = False) -> list[Holding]:
    q = select(InvestmentTransaction).where(InvestmentTransaction.instrument_id.is_not(None))
    if as_of:
        q = q.where(InvestmentTransaction.transaction_date <= as_of)
    if account_ids:
        q = q.where(InvestmentTransaction.account_id.in_(account_ids))
    txns = list(db.scalars(q.order_by(InvestmentTransaction.transaction_date, InvestmentTransaction.id)))
    instruments = {i.id: i for i in db.scalars(select(InvestmentInstrument))}
    holdings: dict[tuple[int, int], Holding] = {}
    for t in txns:
        key = (t.account_id, t.instrument_id)
        inst = instruments[t.instrument_id]
        h = holdings.get(key)
        if h is None:
            h = holdings[key] = Holding(t.account_id, inst.id, inst.name, inst.instrument_type, inst.identifier)
        apply_transaction(h, t)
    vals = latest_valuations(db, as_of)
    out = []
    for h in holdings.values():
        if h.quantity == 0 and not include_closed:
            continue
        v = vals.get((h.account_id, h.instrument_id)) or vals.get((None, h.instrument_id))
        if v is not None and h.quantity > 0:
            h.valuation_date, h.valuation_source = v.valuation_date, v.source
            if v.unit_price is not None:
                h.unit_price = v.unit_price
                h.value_minor = _r(h.quantity * v.unit_price * 100)
            elif v.total_value_minor is not None and v.quantity is not None and v.quantity > 0:
                h.unit_price = Decimal(v.total_value_minor) / 100 / v.quantity
                h.value_minor = _r(h.quantity * Decimal(v.total_value_minor) / v.quantity)
            elif v.total_value_minor is not None:
                h.value_minor = v.total_value_minor
                h.warnings.append("Valuation is a total without quantity; assumed to cover the whole holding.")
            if v.quantity is not None and v.quantity != h.quantity:
                h.warnings.append(f"Valuation quantity {qty_str(v.quantity)} differs from computed quantity "
                                  f"{qty_str(h.quantity)} — check for missing transactions.")
        elif h.quantity > 0:
            h.warnings.append("No valuation available: current value unknown.")
        out.append(h)
    return sorted(out, key=lambda h: (h.account_id, h.instrument_name))


def apply_transaction(h: Holding, t: InvestmentTransaction) -> None:
    qty = t.quantity or ZERO
    h.first_date = h.first_date or t.transaction_date
    h.last_date = t.transaction_date
    tt = t.transaction_type
    if tt in ACQUIRE:
        h.quantity += qty
        h.cost_basis_minor += t.gross_amount_minor + t.charges_minor
        h.invested_minor += t.gross_amount_minor + t.charges_minor
        h.charges_minor += t.charges_minor
    elif tt in DISPOSE or tt == "maturity":
        if tt == "maturity" and not qty:
            qty = h.quantity
        if qty > h.quantity:
            h.warnings.append(f"{t.transaction_date}: disposal of {qty} exceeds held quantity {h.quantity}.")
            qty = h.quantity
        if h.quantity > 0:
            removed = _r(Decimal(h.cost_basis_minor) * qty / h.quantity)
        else:
            removed = 0
        proceeds = t.gross_amount_minor - t.charges_minor
        h.realized_gain_minor += proceeds - removed
        h.cost_basis_minor -= removed
        h.quantity -= qty
        h.withdrawn_minor += proceeds
        h.charges_minor += t.charges_minor
        if h.quantity == 0:
            h.cost_basis_minor = 0
    elif tt == "split":
        if t.split_ratio:
            h.quantity = h.quantity * t.split_ratio
        else:
            h.warnings.append(f"{t.transaction_date}: split without ratio ignored.")
    elif tt == "bonus":
        h.quantity += qty
    elif tt == "dividend":
        h.dividends_minor += t.gross_amount_minor - t.charges_minor
    elif tt == "interest":
        h.interest_minor += t.gross_amount_minor - t.charges_minor
    elif tt == "charge":
        h.charges_minor += t.gross_amount_minor + t.charges_minor
    elif tt == "tax":
        h.taxes_minor += t.gross_amount_minor + t.charges_minor


def latest_valuations(db: Session, as_of: date | None = None) -> dict[tuple[int | None, int], InvestmentValuation]:
    q = select(InvestmentValuation)
    if as_of:
        q = q.where(InvestmentValuation.valuation_date <= as_of)
    out: dict[tuple[int | None, int], InvestmentValuation] = {}
    for v in db.scalars(q.order_by(InvestmentValuation.valuation_date, InvestmentValuation.id)):
        out[(v.account_id, v.instrument_id)] = v
    return out


def rebuild_lots(db: Session, account_id: int, instrument_id: int) -> None:
    """Rebuild informational FIFO lots for one holding (reporting still uses WAC)."""
    db.execute(InvestmentLot.__table__.delete().where(InvestmentLot.account_id == account_id,
                                                      InvestmentLot.instrument_id == instrument_id))
    txns = db.scalars(select(InvestmentTransaction).where(
        InvestmentTransaction.account_id == account_id, InvestmentTransaction.instrument_id == instrument_id)
        .order_by(InvestmentTransaction.transaction_date, InvestmentTransaction.id))
    lots: list[InvestmentLot] = []
    for t in txns:
        q = t.quantity or ZERO
        if t.transaction_type in ACQUIRE or t.transaction_type == "bonus":
            cost = 0 if t.transaction_type == "bonus" else t.gross_amount_minor + t.charges_minor
            lot = InvestmentLot(account_id=account_id, instrument_id=instrument_id, acquisition_date=t.transaction_date,
                                original_quantity=q, remaining_quantity=q, cost_basis_minor=cost,
                                source_investment_transaction_id=t.id)
            lots.append(lot)
        elif t.transaction_type == "split" and t.split_ratio:
            for lot in lots:
                lot.original_quantity *= t.split_ratio
                lot.remaining_quantity *= t.split_ratio
        elif t.transaction_type in DISPOSE or t.transaction_type == "maturity":
            left = q if q else sum((lot.remaining_quantity for lot in lots), ZERO)
            for lot in lots:
                take = min(lot.remaining_quantity, left)
                lot.remaining_quantity -= take
                left -= take
                if left <= 0:
                    break
    for lot in lots:
        db.add(lot)


def portfolio_summary(db: Session, as_of: date | None = None) -> dict:
    hs = compute_holdings(db, as_of)
    closed = [h for h in compute_holdings(db, as_of, include_closed=True) if h.quantity == 0]
    known = [h for h in hs if h.value_minor is not None]
    unknown = [h for h in hs if h.value_minor is None]
    by_type: dict[str, dict] = defaultdict(lambda: {"value_minor": 0, "cost_basis_minor": 0, "unknown_count": 0})
    for h in hs:
        b = by_type[h.instrument_type]
        b["cost_basis_minor"] += h.cost_basis_minor
        if h.value_minor is None:
            b["unknown_count"] += 1
        else:
            b["value_minor"] += h.value_minor
    fds = fixed_deposit_summary(db, as_of)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "holdings": [h.to_dict() for h in hs],
        "closed_positions": [h.to_dict() for h in closed],
        "total_cost_basis_minor": sum(h.cost_basis_minor for h in hs),
        "known_value_minor": sum(h.value_minor for h in known),
        "known_value_cost_basis_minor": sum(h.cost_basis_minor for h in known),
        "unvalued_cost_basis_minor": sum(h.cost_basis_minor for h in unknown),
        "unvalued_count": len(unknown),
        "unrealized_gain_minor": sum(h.unrealized_gain_minor for h in known) if known else None,
        "realized_gain_minor": sum(h.realized_gain_minor for h in hs + closed),
        "dividends_minor": sum(h.dividends_minor for h in hs + closed),
        "interest_minor": sum(h.interest_minor for h in hs + closed),
        "invested_minor": sum(h.invested_minor for h in hs + closed),
        "withdrawn_minor": sum(h.withdrawn_minor for h in hs + closed),
        "allocation": [{"instrument_type": k, **v} for k, v in sorted(by_type.items())],
        "fixed_deposits": fds,
        "value_complete": not unknown,
        "notes": ["Values use the latest imported or manually entered valuation. Holdings without a valuation "
                  "are shown at cost basis separately and are NOT market values."],
    }


def fixed_deposit_summary(db: Session, as_of: date | None = None) -> list[dict]:
    from app.models import Account, Transaction
    from app.services.reporting.classification import classify

    out = []
    for fd in db.scalars(select(FixedDeposit)):
        acct = db.get(Account, fd.account_id)
        interest_txns = list(db.scalars(select(Transaction).where(Transaction.account_id == fd.account_id)))
        credited = sum(p.amount_minor for p in classify(db, interest_txns) if p.cls == "income" and p.amount_minor > 0)
        value = fd.reported_value_minor
        out.append({
            "id": fd.id, "account_id": fd.account_id, "account_name": acct.name if acct else None,
            "institution": acct.institution if acct else None, "principal_minor": fd.principal_minor,
            "opening_date": fd.opening_date.isoformat(), "maturity_date": fd.maturity_date.isoformat() if fd.maturity_date else None,
            "interest_rate": str(fd.interest_rate) if fd.interest_rate is not None else None,
            "reported_maturity_value_minor": fd.reported_maturity_value_minor,
            "reported_value_minor": value, "valuation_date": fd.valuation_date.isoformat() if fd.valuation_date else None,
            "credited_interest_minor": credited, "status": fd.status,
            "projected_interest_minor": (fd.reported_maturity_value_minor - fd.principal_minor)
            if fd.reported_maturity_value_minor is not None else None,
            "projection_note": "Projected interest is the bank-reported maturity value minus principal; not yet earned.",
        })
    return out

from datetime import date, timedelta

from fastapi import Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import protected_router
from app.core.db import get_db
from app.core.errors import AppError
from app.models import Account, ImportBatch, Statement
from app.models.ledger import CASH_TYPES
from app.services.investments.holdings import portfolio_summary
from app.services.ledger.balances import account_balance
from app.services.reporting import exports
from app.services.reporting import reports as rpt

router = protected_router(prefix="/reports", tags=["reports"])


def _range(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or rpt.today()
    start = start or rpt.month_start(end)
    if start > end:
        raise AppError("start must be on or before end")
    return start, end


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    today = rpt.today()
    m0 = rpt.month_start(today)
    year_start = rpt.month_start(m0 - timedelta(days=330))
    accounts = list(db.scalars(select(Account).where(Account.is_active.is_(True)).order_by(Account.name)))
    balances = []
    stale_days = 45
    for a in accounts:
        b = account_balance(db, a)
        balances.append({
            "account_id": a.id, "name": a.name, "account_type": a.account_type, "institution": a.institution,
            "calculated_balance_minor": b.calculated_balance_minor, "balance_status": b.balance_status,
            "last_statement_date": b.last_statement_date.isoformat() if b.last_statement_date else None,
            "last_statement_balance_minor": b.last_statement_balance_minor,
            "coverage_end": b.coverage_end.isoformat() if b.coverage_end else None,
            "reconciliation_status": b.reconciliation_status,
            "is_stale": b.coverage_end is None or (today - b.coverage_end).days > stale_days,
        })
    nw = rpt.net_worth(db)
    portfolio = portfolio_summary(db)
    current = rpt.summary(db, m0, today)
    # last complete month is more meaningful when the current month has little data
    prev_end = m0 - timedelta(days=1)
    previous = rpt.summary(db, rpt.month_start(prev_end), prev_end)
    has_data = db.scalar(select(ImportBatch.id).where(ImportBatch.status == "committed").limit(1)) is not None
    latest_stmt = db.scalar(select(Statement.end_date).order_by(Statement.end_date.desc()).limit(1))
    return {
        "today": today.isoformat(),
        "has_data": has_data,
        "latest_statement_date": latest_stmt.isoformat() if latest_stmt else None,
        "balances": balances,
        "cards": {
            "cash_minor": nw["groups"].get("cash", 0),
            "credit_card_outstanding_minor": -nw["groups"].get("credit_cards", 0),
            "loans_minor": -nw["groups"].get("loans", 0),
            "other_liabilities_minor": -nw["groups"].get("other_liabilities", 0),
            "investments_valued_minor": nw["groups"].get("investments_valued", 0),
            "investments_unvalued_cost_minor": nw["groups"].get("investments_at_cost_unvalued", 0),
            "fixed_deposits_minor": nw["groups"].get("fixed_deposits", 0),
            "total_assets_minor": nw["total_assets_minor"],
            "total_liabilities_minor": nw["total_liabilities_minor"],
            "net_worth_minor": nw["net_worth_minor"],
            "net_worth_is_estimate": nw["is_estimate"],
            "unknown_balance_accounts": [ln["name"] for ln in nw["accounts"] if ln["balance_minor"] is None],
        },
        "current_month": current,
        "previous_month": previous,
        "monthly": rpt.monthly_series(db, year_start, today),
        "categories_current_month": rpt.category_breakdown(db, m0, today)[:12],
        "categories_previous_month": rpt.category_breakdown(db, rpt.month_start(prev_end), prev_end)[:12],
        "net_worth_series": rpt.net_worth_series(db, 12),
        "balance_series": rpt.account_balance_series(db, 12),
        "allocation": portfolio["allocation"],
        "portfolio": {k: portfolio[k] for k in ("total_cost_basis_minor", "known_value_minor", "unvalued_cost_basis_minor",
                                                 "unvalued_count", "unrealized_gain_minor", "value_complete")},
        "cash_account_ids": [a.id for a in accounts if a.account_type in CASH_TYPES],
    }


@router.get("/summary")
def summary(start: date | None = None, end: date | None = None, account_id: list[int] = Query(None),
            db: Session = Depends(get_db)):
    s, e = _range(start, end)
    return rpt.summary(db, s, e, account_id)


@router.get("/monthly")
def monthly(start: date | None = None, end: date | None = None, account_id: list[int] = Query(None),
            db: Session = Depends(get_db)):
    e = end or rpt.today()
    s = start or rpt.month_start(e - timedelta(days=330))
    return rpt.monthly_series(db, s, e, account_id)


@router.get("/categories")
def categories(start: date | None = None, end: date | None = None, kind: str = Query("expense", pattern="^(expense|income)$"),
               account_id: list[int] = Query(None), db: Session = Depends(get_db)):
    s, e = _range(start, end)
    return rpt.category_breakdown(db, s, e, account_id, kind)


@router.get("/merchants")
def merchants(start: date | None = None, end: date | None = None, account_id: list[int] = Query(None),
              db: Session = Depends(get_db)):
    s, e = _range(start, end)
    return rpt.merchant_breakdown(db, s, e, account_id)


@router.get("/largest")
def largest(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    s, e = _range(start, end)
    return rpt.largest_transactions(db, s, e)


@router.get("/unusual")
def unusual(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    s, e = _range(start, end)
    return rpt.unusual_spending(db, s, e)


@router.get("/cash-flow")
def cash_flow(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    s, e = _range(start, end)
    return rpt.cash_flow(db, s, e)


@router.get("/net-worth")
def net_worth(as_of: date | None = None, db: Session = Depends(get_db)):
    return rpt.net_worth(db, as_of)


@router.get("/net-worth/series")
def net_worth_series(months: int = Query(12, ge=1, le=120), db: Session = Depends(get_db)):
    return rpt.net_worth_series(db, months)


@router.get("/accounts")
def accounts(db: Session = Depends(get_db)):
    return rpt.accounts_report(db)


@router.get("/recurring-candidates")
def recurring(db: Session = Depends(get_db)):
    return rpt.recurring_candidates(db)


REPORT_KINDS = ("summary", "monthly", "categories", "income", "merchants", "cash-flow", "net-worth", "accounts", "largest")


@router.get("/export/{kind}")
def export(kind: str, fmt: str = Query("csv", pattern="^(csv|xlsx)$"), start: date | None = None,
           end: date | None = None, db: Session = Depends(get_db)):
    if kind not in REPORT_KINDS:
        raise AppError(f"Unknown report {kind}")
    s, e = _range(start, end)
    if kind == "summary":
        rows = [rpt.summary(db, s, e)]
        rows[0]["coverage_warnings"] = "; ".join(rows[0]["coverage_warnings"])
    elif kind == "monthly":
        rows = rpt.monthly_series(db, start or rpt.month_start(e - timedelta(days=330)), e)
    elif kind == "categories":
        rows = rpt.category_breakdown(db, s, e)
    elif kind == "income":
        rows = rpt.category_breakdown(db, s, e, kind="income")
    elif kind == "merchants":
        rows = rpt.merchant_breakdown(db, s, e, limit=1000)
    elif kind == "cash-flow":
        rows = [rpt.cash_flow(db, s, e)]
    elif kind == "net-worth":
        rows = rpt.net_worth(db, end)["accounts"]
    elif kind == "accounts":
        rows = rpt.accounts_report(db)
    else:
        rows = rpt.largest_transactions(db, s, e, limit=200)
    cols, data = exports.dicts_to_table(rows)
    name = f"{kind}_{s.isoformat()}_{e.isoformat()}"
    if fmt == "xlsx":
        return Response(exports.to_xlsx({kind: (cols, data)}),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return Response(exports.to_csv(cols, [[str(c) if c is not None else "" for c in r] for r in data]),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})

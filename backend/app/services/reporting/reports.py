"""Report calculations. All figures derive from the ledger via classification.classify()."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Account, Category, FixedDeposit, Statement, Transaction
from app.models.ledger import CASH_TYPES, INVESTMENT_TYPES, LIABILITY_TYPES
from app.services.investments.holdings import compute_holdings
from app.services.ledger.balances import account_balance, balance_as_of
from app.services.reporting.classification import Part, account_map, classify, ledger_transactions


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def months_between(start: date, end: date) -> list[date]:
    out, m = [], month_start(start)
    while m <= end:
        out.append(m)
        m = month_end(m) + timedelta(days=1)
    return out


def _cat_names(db: Session) -> dict[int, tuple[str, str | None]]:
    cats = {c.id: c for c in db.scalars(select(Category))}
    return {cid: (c.name, cats[c.parent_id].name if c.parent_id and c.parent_id in cats else None) for cid, c in cats.items()}


def totals_from_parts(parts: list[Part], accounts: dict[int, Account]) -> dict:
    t = defaultdict(int)
    for p in parts:
        acct = accounts[p.account_id]
        in_investment_acct = acct.account_type in INVESTMENT_TYPES
        if p.cls == "income":
            t["income"] += p.amount_minor
        elif p.cls == "expense":
            t["expenses"] += -p.amount_minor
        elif p.cls == "refund":
            t["refunds"] += p.amount_minor
        elif p.cls == "investment" and not in_investment_acct:
            if p.amount_minor < 0:
                t["investment_contributions"] += -p.amount_minor
            else:
                t["investment_withdrawals"] += p.amount_minor
        elif p.cls == "transfer":
            t["transfers_out" if p.amount_minor < 0 else "transfers_in"] += abs(p.amount_minor)
        elif p.cls == "card_payment":
            if acct.account_type == "credit_card":
                t["card_repayments_received"] += p.amount_minor
            else:
                t["card_repayments_paid"] += -p.amount_minor
        elif p.cls == "loan_principal":
            t["loan_principal_net"] += p.amount_minor
        elif p.cls == "cash_withdrawal":
            t["cash_withdrawals"] += -p.amount_minor
        elif p.cls == "uncategorized":
            t["uncategorized_in" if p.amount_minor > 0 else "uncategorized_out"] += abs(p.amount_minor)
            t["uncategorized_count"] += 1
    t["net_spending"] = t["expenses"] - t["refunds"]
    t["net_savings"] = t["income"] - t["net_spending"]
    keys = ["income", "expenses", "refunds", "net_spending", "net_savings", "investment_contributions",
            "investment_withdrawals", "transfers_out", "transfers_in", "card_repayments_paid",
            "card_repayments_received", "loan_principal_net", "cash_withdrawals", "uncategorized_in",
            "uncategorized_out", "uncategorized_count"]
    return {k: t.get(k, 0) for k in keys}


def coverage_warnings(db: Session, start: date, end: date, parts: list[Part], accounts: dict[int, Account]) -> list[str]:
    out = []
    card_accounts = [a for a in accounts.values() if a.account_type == "credit_card"]
    pays_card = [p for p in parts if accounts[p.account_id].account_type not in LIABILITY_TYPES and
                 (p.cls == "card_payment" or (p.cls == "transfer" and p.amount_minor < 0 and
                                              "card" in (p.description or "").lower()))]
    if pays_card and not card_accounts:
        out.append("Credit-card repayments were found but no credit-card account exists: card purchases are not "
                   "included in spending, so spending coverage is incomplete.")
    for a in card_accounts:
        covered = db.scalar(select(Statement.id).where(Statement.account_id == a.id, Statement.start_date <= end,
                                                       Statement.end_date >= start).limit(1))
        if covered is None:
            out.append(f"No statement imported for {a.name} in this period: its spending is missing.")
    for a in accounts.values():
        if not a.is_active or a.account_type not in CASH_TYPES:
            continue
        covered = db.scalar(select(Statement.id).where(Statement.account_id == a.id, Statement.end_date >= start,
                                                       Statement.start_date <= end).limit(1))
        has_txn = db.scalar(select(Transaction.id).where(Transaction.account_id == a.id,
                                                         Transaction.transaction_date.between(start, end)).limit(1))
        if covered is None and has_txn is None:
            out.append(f"No data for {a.name} in this period.")
    return out


def summary(db: Session, start: date, end: date, account_ids: list[int] | None = None) -> dict:
    accounts = account_map(db)
    parts = classify(db, ledger_transactions(db, start, end, account_ids))
    totals = totals_from_parts(parts, accounts)
    return {"start": start.isoformat(), "end": end.isoformat(), **totals,
            "coverage_warnings": coverage_warnings(db, start, end, parts, accounts) if not account_ids else []}


def monthly_series(db: Session, start: date, end: date, account_ids: list[int] | None = None) -> list[dict]:
    accounts = account_map(db)
    parts = classify(db, ledger_transactions(db, start, end, account_ids))
    by_month: dict[date, list[Part]] = defaultdict(list)
    for p in parts:
        by_month[month_start(p.date)].append(p)
    out = []
    for m in months_between(start, end):
        tot = totals_from_parts(by_month.get(m, []), accounts)
        card = [p for p in by_month.get(m, []) if accounts[p.account_id].account_type == "credit_card"]
        out.append({"month": m.isoformat()[:7], **tot,
                    "card_spending": sum(-p.amount_minor for p in card if p.cls == "expense"),
                    "card_repayments": sum(p.amount_minor for p in card if p.cls in ("card_payment", "transfer") and p.amount_minor > 0)})
    return out


def category_breakdown(db: Session, start: date, end: date, account_ids: list[int] | None = None,
                       kind: str = "expense") -> list[dict]:
    """Net spending per category (expenses minus refunds attributed to that category), or income per category."""
    names = _cat_names(db)
    parts = classify(db, ledger_transactions(db, start, end, account_ids))
    agg: dict[int | None, dict] = defaultdict(lambda: {"gross_minor": 0, "refunds_minor": 0, "count": 0})
    for p in parts:
        if kind == "expense" and p.cls in ("expense", "refund"):
            a = agg[p.category_id]
            if p.cls == "expense":
                a["gross_minor"] += -p.amount_minor
                a["count"] += 1
            else:
                a["refunds_minor"] += p.amount_minor
        elif kind == "income" and p.cls == "income":
            a = agg[p.category_id]
            a["gross_minor"] += p.amount_minor
            a["count"] += 1
    out = []
    for cid, a in agg.items():
        name, parent = names.get(cid, ("Uncategorized", None)) if cid else ("Uncategorized", None)
        out.append({"category_id": cid, "category": name, "parent": parent, **a,
                    "net_minor": a["gross_minor"] - a["refunds_minor"]})
    return sorted(out, key=lambda r: -r["net_minor"])


def merchant_breakdown(db: Session, start: date, end: date, account_ids: list[int] | None = None, limit: int = 50) -> list[dict]:
    parts = classify(db, ledger_transactions(db, start, end, account_ids))
    agg: dict[str, dict] = defaultdict(lambda: {"net_minor": 0, "count": 0})
    for p in parts:
        if p.cls in ("expense", "refund"):
            key = p.merchant or "(unknown merchant)"
            agg[key]["net_minor"] += -p.amount_minor
            agg[key]["count"] += 1
    rows = [{"merchant": k, **v} for k, v in agg.items()]
    return sorted(rows, key=lambda r: -r["net_minor"])[:limit]


def largest_transactions(db: Session, start: date, end: date, account_ids=None, limit: int = 20) -> list[dict]:
    parts = [p for p in classify(db, ledger_transactions(db, start, end, account_ids)) if p.cls == "expense"]
    parts.sort(key=lambda p: p.amount_minor)
    return [{"transaction_id": p.transaction_id, "date": p.date.isoformat(), "description": p.description,
             "merchant": p.merchant, "amount_minor": -p.amount_minor, "account_id": p.account_id} for p in parts[:limit]]


def unusual_spending(db: Session, start: date, end: date, lookback_days: int = 365) -> list[dict]:
    """Expenses far above the merchant's/category's typical amount (median + 3×MAD, at least 2× median)."""
    hist = classify(db, ledger_transactions(db, start - timedelta(days=lookback_days), end))
    by_key: dict[str, list[int]] = defaultdict(list)
    for p in hist:
        if p.cls == "expense" and p.date < start:
            by_key[p.merchant or f"cat:{p.category_id}"].append(-p.amount_minor)
    out = []
    for p in hist:
        if p.cls != "expense" or p.date < start:
            continue
        key = p.merchant or f"cat:{p.category_id}"
        past = by_key.get(key, [])
        if len(past) < 3:
            continue
        med = statistics.median(past)
        mad = statistics.median([abs(x - med) for x in past]) or med * 0.1
        amt = -p.amount_minor
        if amt > med + 3 * mad and amt >= 2 * med:
            out.append({"transaction_id": p.transaction_id, "date": p.date.isoformat(), "description": p.description,
                        "merchant": p.merchant, "amount_minor": amt, "typical_minor": int(med),
                        "reason": f"{amt / med:.1f}× the typical amount for this merchant/category"})
    return sorted(out, key=lambda r: -r["amount_minor"])


def cash_flow(db: Session, start: date, end: date) -> dict:
    """Cash (savings/current/cash accounts) movement statement for the period."""
    accounts = account_map(db)
    cash_ids = [a.id for a in accounts.values() if a.account_type in CASH_TYPES]
    parts = classify(db, ledger_transactions(db, start, end, cash_ids))
    groups = defaultdict(int)
    for p in parts:
        groups[p.cls] += p.amount_minor
    opening = closing = 0
    unknown = []
    for aid in cash_ids:
        a = accounts[aid]
        o = balance_as_of(db, a, start - timedelta(days=1))
        c = balance_as_of(db, a, end)
        if o is None or c is None:
            unknown.append(a.name)
            continue
        opening += o
        closing += c
    movements = sum(p.amount_minor for p in parts)
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "opening_cash_minor": opening if not unknown else None,
        "income_minor": groups["income"],
        "expenses_minor": groups["expense"],
        "refunds_minor": groups["refund"],
        "transfers_minor": groups["transfer"],
        "card_repayments_minor": groups["card_payment"],
        "investment_flows_minor": groups["investment"],
        "loan_flows_minor": groups["loan_principal"],
        "cash_withdrawals_minor": groups["cash_withdrawal"],
        "uncategorized_minor": groups["uncategorized"],
        "excluded_minor": groups["excluded"],
        "net_movement_minor": movements,
        "closing_cash_minor": closing if not unknown else None,
        "accounts_with_unknown_opening": unknown,
        "check": None if unknown else (opening + movements == closing),
    }


def recurring_candidates(db: Session, min_occurrences: int = 3) -> list[dict]:
    """Merchants/descriptions charged at a regular interval with similar amounts. Suggestions only."""
    from app.services.imports.normalization import match_key

    txns = ledger_transactions(db, today() - timedelta(days=400), None)
    groups: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in txns:
        if t.amount_minor >= 0:
            continue
        key = match_key(t.merchant) or match_key(t.normalized_description)[:24]
        groups[(t.account_id, key)].append(t)
    out = []
    for (acct, key), ts in groups.items():
        if len(ts) < min_occurrences or not key:
            continue
        ts.sort(key=lambda t: t.transaction_date)
        gaps = [(b.transaction_date - a.transaction_date).days for a, b in zip(ts, ts[1:], strict=False)]
        med_gap = statistics.median(gaps)
        cadence = "monthly" if 26 <= med_gap <= 35 else "weekly" if 6 <= med_gap <= 8 else \
            "yearly" if 350 <= med_gap <= 380 else "quarterly" if 85 <= med_gap <= 95 else None
        if cadence is None:
            continue
        amounts = [abs(t.amount_minor) for t in ts]
        med_amt = statistics.median(amounts)
        if max(abs(a - med_amt) for a in amounts) > med_amt * 0.15:
            continue
        out.append({"account_id": acct, "match_key": key, "name": ts[-1].merchant or ts[-1].normalized_description[:60],
                    "cadence": cadence, "occurrences": len(ts), "typical_amount_minor": int(med_amt),
                    "typical_day": int(statistics.median([t.transaction_date.day for t in ts])),
                    "last_date": ts[-1].transaction_date.isoformat(), "category_id": ts[-1].category_id,
                    "transaction_ids": [t.id for t in ts]})
    return sorted(out, key=lambda r: -r["typical_amount_minor"])


# ------------------------------------------------------------------- balances & net worth

def _fd_value(db: Session, a: Account, as_of: date | None) -> tuple[int | None, str]:
    fd = db.scalar(select(FixedDeposit).where(FixedDeposit.account_id == a.id))
    if fd is not None and fd.reported_value_minor is not None and (as_of is None or (fd.valuation_date or fd.opening_date) <= as_of):
        return fd.reported_value_minor, "reported"
    bal = balance_as_of(db, a, as_of)
    has_txn = db.scalar(select(Transaction.id).where(Transaction.account_id == a.id).limit(1)) is not None
    if bal is not None and has_txn:
        return bal, "ledger"
    if fd is not None and (as_of is None or fd.opening_date <= as_of):
        return fd.principal_minor, "principal"
    return None, "unknown"


def net_worth(db: Session, as_of: date | None = None) -> dict:
    accounts = [a for a in db.scalars(select(Account).order_by(Account.name))]
    holdings = compute_holdings(db, as_of)
    hold_by_acct: dict[int, list] = defaultdict(list)
    for h in holdings:
        hold_by_acct[h.account_id].append(h)
    lines = []
    groups = defaultdict(int)
    estimated = False
    for a in accounts:
        if not a.is_active and as_of is None and not hold_by_acct.get(a.id):
            bal_check = balance_as_of(db, a, as_of)
            if not bal_check:
                continue
        if a.account_type == "fixed_deposit":
            val, basis = _fd_value(db, a, as_of)
            group = "fixed_deposits"
        else:
            val, basis = balance_as_of(db, a, as_of), "ledger"
            group = ("credit_cards" if a.account_type == "credit_card" else
                     "loans" if a.account_type == "loan" else
                     "other_liabilities" if a.account_type in LIABILITY_TYPES else
                     "investment_cash" if a.account_type in INVESTMENT_TYPES else
                     "cash" if a.account_type in CASH_TYPES else "other_assets")
        if val is None:
            estimated = True
            basis = "unknown"
        else:
            groups[group] += val
            if basis == "principal" or (basis == "ledger" and a.opening_verification != "verified"):
                estimated = estimated or basis == "principal"
        lines.append({"account_id": a.id, "name": a.name, "account_type": a.account_type, "group": group,
                      "balance_minor": val, "basis": basis})
        for h in hold_by_acct.get(a.id, []):
            if h.value_minor is not None:
                groups["investments_valued"] += h.value_minor
            else:
                groups["investments_at_cost_unvalued"] += h.cost_basis_minor
                estimated = True
    assets = sum(v for k, v in groups.items() if k in ("cash", "fixed_deposits", "investment_cash", "other_assets",
                                                         "investments_valued", "investments_at_cost_unvalued"))
    liabilities = -sum(v for k, v in groups.items() if k in ("credit_cards", "loans", "other_liabilities"))
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "groups": dict(groups),
        "total_assets_minor": assets,
        "total_liabilities_minor": liabilities,
        "net_worth_minor": assets - liabilities,
        "is_estimate": estimated,
        "accounts": lines,
        "notes": [
            "Liabilities are shown as positive amounts owed.",
            "investments_at_cost_unvalued = holdings with no valuation, included at cost basis. This is NOT a market value.",
            "Accounts with an unknown opening balance are excluded and make the total an estimate.",
        ],
    }


def net_worth_series(db: Session, months: int = 12) -> list[dict]:
    end = today()
    out = []
    for m in months_between(month_start(end) - timedelta(days=31 * (months - 1)), end):
        me = min(month_end(m), end)
        nw = net_worth(db, me)
        out.append({"month": m.isoformat()[:7], "date": me.isoformat(), "net_worth_minor": nw["net_worth_minor"],
                    "assets_minor": nw["total_assets_minor"], "liabilities_minor": nw["total_liabilities_minor"],
                    "is_estimate": nw["is_estimate"]})
    return out


def account_balance_series(db: Session, months: int = 12) -> list[dict]:
    end = today()
    accounts = [a for a in db.scalars(select(Account).where(Account.is_active.is_(True)))]
    out = []
    for m in months_between(month_start(end) - timedelta(days=31 * (months - 1)), end):
        me = min(month_end(m), end)
        row = {"month": m.isoformat()[:7]}
        for a in accounts:
            if a.opening_date and a.opening_date > me:
                row[str(a.id)] = None
            else:
                row[str(a.id)] = balance_as_of(db, a, me)
        out.append(row)
    return out


def accounts_report(db: Session) -> list[dict]:
    out = []
    for a in db.scalars(select(Account).order_by(Account.name)):
        b = account_balance(db, a)
        unmatched = db.scalar(select(Transaction.id).where(Transaction.account_id == a.id,
                                                           Transaction.reconciliation_status == "unreconciled").limit(1))
        out.append({"account_id": a.id, "name": a.name, "account_type": a.account_type,
                    "calculated_balance_minor": b.calculated_balance_minor, "balance_status": b.balance_status,
                    "last_statement_date": b.last_statement_date.isoformat() if b.last_statement_date else None,
                    "last_statement_balance_minor": b.last_statement_balance_minor,
                    "reconciliation_status": b.reconciliation_status,
                    "coverage_end": b.coverage_end.isoformat() if b.coverage_end else None,
                    "has_unreconciled": unmatched is not None})
    return out

"""Validation of parsed statements. Reports problems; never alters amounts or signs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal

from app.services.imports.candidates import CandidateRow, ParsedStatement


@dataclass
class ValidationReport:
    row_count: int = 0
    error_rows: int = 0
    warning_rows: int = 0
    total_debits: str = "0"
    total_credits: str = "0"
    net_movement: str = "0"
    opening_balance: str | None = None
    closing_balance_reported: str | None = None
    closing_balance_calculated: str | None = None
    closing_difference: str | None = None
    balance_check: str = "unverifiable"  # passed | failed | unverifiable
    running_balance_check: str = "unavailable"  # passed | failed | unavailable
    running_balance_breaks: list[dict] = field(default_factory=list)
    sign_hint: str | None = None
    dates_outside_period: int = 0
    first_date: str | None = None
    last_date: str | None = None
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _s(d: Decimal | None) -> str | None:
    return None if d is None else str(d)


def validate(ps: ParsedStatement, rows: list[CandidateRow] | None = None) -> ValidationReport:
    rows = ps.rows if rows is None else rows
    rep = ValidationReport(row_count=len(rows))
    valid = [r for r in rows if not r.errors and r.amount is not None]
    rep.error_rows = sum(1 for r in rows if r.errors)
    rep.warning_rows = sum(1 for r in rows if r.warnings and not r.errors)
    debits = sum((-r.amount for r in valid if r.amount < 0), Decimal(0))
    credits = sum((r.amount for r in valid if r.amount > 0), Decimal(0))
    net = credits - debits
    rep.total_debits, rep.total_credits, rep.net_movement = str(debits), str(credits), str(net)
    dates = [r.txn_date for r in rows if r.txn_date]
    if dates:
        rep.first_date, rep.last_date = str(min(dates)), str(max(dates))
    if ps.period_start and ps.period_end:
        rep.dates_outside_period = sum(1 for d in dates if d < ps.period_start or d > ps.period_end)
        if rep.dates_outside_period:
            rep.messages.append(f"{rep.dates_outside_period} transaction date(s) fall outside the statement period.")

    # Running balance chain: balance[i] == balance[i-1] + amount[i]
    chain = [r for r in rows if r.balance is not None]
    if len(chain) >= 2 or (chain and ps.opening_balance is not None):
        breaks = []
        inverted_ok = 0
        prev = ps.opening_balance
        for r in rows:
            if r.balance is None or r.amount is None:
                prev = r.balance if r.balance is not None else prev
                continue
            if prev is not None:
                expected = prev + r.amount
                if expected != r.balance:
                    if prev - r.amount == r.balance:
                        inverted_ok += 1
                    breaks.append({"row_index": r.row_index, "source_ref": r.source_ref,
                                   "expected": str(expected), "reported": str(r.balance),
                                   "difference": str(r.balance - expected)})
            prev = r.balance
        rep.running_balance_breaks = breaks[:50]
        rep.running_balance_check = "failed" if breaks else "passed"
        if breaks:
            rep.messages.append(f"Running balance does not chain at {len(breaks)} row(s).")
            if inverted_ok and inverted_ok >= len(breaks) * 0.8:
                rep.sign_hint = "inverted"
                rep.messages.append(
                    "The running balance would chain if amount signs were reversed. Check the sign "
                    "convention (e.g. a credit-card file where purchases are positive). Signs were NOT changed."
                )

    opening = ps.opening_balance
    if opening is None and chain:
        first = next((r for r in rows if r.balance is not None and r.amount is not None), None)
        if first is not None and rows and first is rows[0]:
            opening = first.balance - first.amount
            rep.messages.append("Opening balance derived from the first row's running balance.")
    closing_reported = ps.closing_balance
    if closing_reported is None and chain and rows[-1].balance is not None:
        closing_reported = rows[-1].balance
    rep.opening_balance = _s(opening)
    rep.closing_balance_reported = _s(closing_reported)
    if opening is not None:
        calc = opening + net
        rep.closing_balance_calculated = str(calc)
        if closing_reported is not None:
            diff = closing_reported - calc
            rep.closing_difference = str(diff)
            rep.balance_check = "passed" if diff == 0 else "failed"
            if diff != 0:
                rep.messages.append(
                    f"Opening balance + movements = {calc}, but the statement reports {closing_reported} "
                    f"(difference {diff})."
                )
    if rep.error_rows:
        rep.messages.append(f"{rep.error_rows} row(s) have errors and are excluded until corrected.")
    return rep

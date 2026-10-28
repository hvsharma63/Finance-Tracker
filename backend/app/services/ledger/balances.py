"""Account balance calculation. See docs/CONVENTIONS.md for sign conventions."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, ImportBatch, Statement, Transaction

# Transactions excluded from the ledger total (confirmed duplicates).
LEDGER_FILTER = Transaction.duplicate_status != "duplicate"


@dataclass
class AccountBalance:
    account_id: int
    calculated_balance_minor: int | None
    movements_minor: int
    balance_status: str  # verified | unverified | estimated
    first_transaction_date: date | None
    last_transaction_date: date | None
    coverage_start: date | None
    coverage_end: date | None
    last_statement_date: date | None
    last_statement_balance_minor: int | None
    last_import_at: str | None
    reconciliation_status: str  # reconciled | discrepancy | unverifiable | no_statements
    statement_count: int


def movements_total(db: Session, account_id: int, through: date | None = None) -> int:
    q = select(func.coalesce(func.sum(Transaction.amount_minor), 0)).where(
        Transaction.account_id == account_id, LEDGER_FILTER
    )
    if through is not None:
        q = q.where(Transaction.transaction_date <= through)
    return int(db.scalar(q))


def balance_as_of(db: Session, account: Account, through: date | None = None) -> int | None:
    """Opening balance + movements. None if the opening balance is unknown."""
    if account.opening_balance_minor is None:
        return None
    q = select(func.coalesce(func.sum(Transaction.amount_minor), 0)).where(
        Transaction.account_id == account.id, LEDGER_FILTER
    )
    if account.opening_date is not None:
        q = q.where(Transaction.transaction_date >= account.opening_date)
    if through is not None:
        q = q.where(Transaction.transaction_date <= through)
    return account.opening_balance_minor + int(db.scalar(q))


def account_balance(db: Session, account: Account) -> AccountBalance:
    movements = movements_total(db, account.id)
    first, last = db.execute(
        select(func.min(Transaction.transaction_date), func.max(Transaction.transaction_date)).where(
            Transaction.account_id == account.id, LEDGER_FILTER
        )
    ).one()
    statements = list(
        db.scalars(select(Statement).where(Statement.account_id == account.id).order_by(Statement.end_date))
    )
    last_stmt = statements[-1] if statements else None
    last_import = db.scalar(
        select(func.max(ImportBatch.committed_at)).where(
            ImportBatch.account_id == account.id, ImportBatch.status == "committed"
        )
    )
    calc = balance_as_of(db, account)
    if calc is None:
        status = "estimated"
    elif account.opening_verification == "verified":
        status = "verified"
    else:
        status = "unverified"
    if not statements:
        recon = "no_statements"
    elif any(s.reconciliation_status == "discrepancy" for s in statements):
        recon = "discrepancy"
    elif all(s.reconciliation_status == "reconciled" for s in statements):
        recon = "reconciled"
    else:
        recon = "unverifiable"
    return AccountBalance(
        account_id=account.id,
        calculated_balance_minor=calc,
        movements_minor=movements,
        balance_status=status,
        first_transaction_date=first,
        last_transaction_date=last,
        coverage_start=min((s.start_date for s in statements if s.start_date), default=None),
        coverage_end=max((s.end_date for s in statements if s.end_date), default=None),
        last_statement_date=last_stmt.end_date if last_stmt else None,
        last_statement_balance_minor=last_stmt.reported_closing_minor if last_stmt else None,
        last_import_at=last_import.isoformat() if last_import else None,
        reconciliation_status=recon,
        statement_count=len(statements),
    )


def coverage_gaps(db: Session, account_id: int) -> list[tuple[date, date]]:
    """Date ranges between consecutive statements that no statement covers."""
    stmts = list(
        db.scalars(
            select(Statement)
            .where(Statement.account_id == account_id, Statement.start_date.is_not(None), Statement.end_date.is_not(None))
            .order_by(Statement.start_date)
        )
    )
    gaps = []
    covered_to = None
    for s in stmts:
        if covered_to is not None and s.start_date > covered_to and (s.start_date - covered_to).days > 1:
            gaps.append((covered_to, s.start_date))
        covered_to = max(covered_to, s.end_date) if covered_to else s.end_date
    return gaps

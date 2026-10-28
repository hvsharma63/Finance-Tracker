from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, JSONType, TimestampMixin, utcnow

ACCOUNT_TYPES = (
    "savings", "current", "cash", "credit_card", "fixed_deposit", "brokerage",
    "mutual_fund", "investment_other", "loan", "liability_other", "custom_asset",
)
LIABILITY_TYPES = {"credit_card", "loan", "liability_other"}
INVESTMENT_TYPES = {"brokerage", "mutual_fund", "investment_other", "fixed_deposit"}
CASH_TYPES = {"savings", "current", "cash"}

REPORTING_TYPES = (
    "income", "expense", "transfer", "investment", "loan_principal", "refund",
    "cash_withdrawal", "excluded",
)
RELATIONSHIP_TYPES = (
    "transfer", "card_payment", "refund", "duplicate", "investment_contribution",
    "investment_withdrawal", "loan_payment", "split", "fee", "other",
)
# Relationship types that turn both sides into financial movements (excluded from income/expense)
MOVEMENT_RELATIONSHIPS = {
    "transfer", "card_payment", "investment_contribution", "investment_withdrawal", "loan_payment",
}


def _in(values) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


class Account(IdMixin, TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(f"account_type IN {_in(ACCOUNT_TYPES)}", name="ck_accounts_type"),
        CheckConstraint(
            "opening_verification IN ('unknown','unverified','verified')", name="ck_accounts_verification"
        ),
        UniqueConstraint("name", name="uq_accounts_name"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    custom_type_label: Mapped[str | None] = mapped_column(String(60))
    is_liability: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    masked_identifier: Mapped[str | None] = mapped_column(String(30))
    opening_balance_minor: Mapped[int | None] = mapped_column(BigInteger)
    opening_date: Mapped[date | None] = mapped_column(Date)
    opening_verification: Mapped[str] = mapped_column(String(12), nullable=False, default="unknown")
    # 'user' = entered manually; 'statement' = taken from the earliest imported statement (kept in sync)
    opening_source: Mapped[str | None] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    default_parser: Mapped[str | None] = mapped_column(String(80))


class Category(IdMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(f"reporting_type IN {_in(REPORTING_TYPES)}", name="ck_categories_reporting_type"),
        UniqueConstraint("parent_id", "name", name="uq_categories_parent_name"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    reporting_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    parent = relationship("Category", remote_side="Category.id")


class Statement(IdMixin, TimestampMixin, Base):
    __tablename__ = "statements"
    __table_args__ = (
        CheckConstraint(
            "reconciliation_status IN ('reconciled','discrepancy','unverifiable')", name="ck_statements_recon"
        ),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    import_batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    reported_opening_minor: Mapped[int | None] = mapped_column(BigInteger)
    reported_closing_minor: Mapped[int | None] = mapped_column(BigInteger)
    calculated_closing_minor: Mapped[int | None] = mapped_column(BigInteger)
    discrepancy_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    reconciliation_status: Mapped[str] = mapped_column(String(15), nullable=False, default="unverifiable")
    notes: Mapped[str | None] = mapped_column(Text)


class Transaction(IdMixin, TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("direction IN ('debit','credit')", name="ck_transactions_direction"),
        CheckConstraint("review_status IN ('pending','reviewed')", name="ck_transactions_review"),
        CheckConstraint(
            "duplicate_status IN ('none','confirmed_unique','duplicate')", name="ck_transactions_duplicate"
        ),
        Index("ix_transactions_account_date", "account_id", "transaction_date"),
        Index("ix_transactions_fingerprint", "account_id", "fingerprint"),
        Index("ix_transactions_date", "transaction_date"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    statement_id: Mapped[int | None] = mapped_column(ForeignKey("statements.id", ondelete="RESTRICT"), index=True)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    posting_date: Mapped[date | None] = mapped_column(Date)
    # Values exactly as extracted from the source; never modified after commit.
    original_description: Mapped[str] = mapped_column(Text, nullable=False)
    original_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_data: Mapped[dict | None] = mapped_column(JSONType)
    # Normalized / user-editable values
    normalized_description: Mapped[str] = mapped_column(Text, nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(200), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    transaction_type: Mapped[str | None] = mapped_column(String(30))
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    balance_after_minor: Mapped[int | None] = mapped_column(BigInteger)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    category_source: Mapped[str] = mapped_column(String(10), nullable=False, default="none")  # none|rule|user
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("categorization_rules.id", ondelete="SET NULL"))
    tags: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    reconciliation_status: Mapped[str] = mapped_column(String(15), nullable=False, default="unreconciled")
    duplicate_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_row_reference: Mapped[str | None] = mapped_column(String(120))
    parser_name: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str | None] = mapped_column(String(20))
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    account = relationship("Account")
    category = relationship("Category")


class TransactionRelationship(IdMixin, Base):
    __tablename__ = "transaction_relationships"
    __table_args__ = (
        CheckConstraint(f"relationship_type IN {_in(RELATIONSHIP_TYPES)}", name="ck_rel_type"),
        CheckConstraint(
            "review_status IN ('suggested','approved','rejected','undone')", name="ck_rel_review"
        ),
        CheckConstraint("source_transaction_id <> related_transaction_id", name="ck_rel_not_self"),
        UniqueConstraint(
            "source_transaction_id", "related_transaction_id", "relationship_type", name="uq_rel_pair_type"
        ),
    )

    source_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    related_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(30), nullable=False)
    matched_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    review_status: Mapped[str] = mapped_column(String(10), nullable=False, default="suggested")
    score: Mapped[float | None] = mapped_column(Numeric(6, 3))
    matching_reason: Mapped[dict | None] = mapped_column(JSONType)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source = relationship("Transaction", foreign_keys=[source_transaction_id])
    related = relationship("Transaction", foreign_keys=[related_transaction_id])


class BalanceSnapshot(IdMixin, Base):
    __tablename__ = "balance_snapshots"
    __table_args__ = (
        CheckConstraint(
            "balance_type IN ('statement_opening','statement_closing','manual')", name="ck_snap_type"
        ),
        Index("ix_snap_account_date", "account_id", "balance_date"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    balance_date: Mapped[date] = mapped_column(Date, nullable=False)
    balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_statement_id: Mapped[int | None] = mapped_column(ForeignKey("statements.id", ondelete="CASCADE"))
    confidence_status: Mapped[str] = mapped_column(String(15), nullable=False, default="reported")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CategorizationRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "categorization_rules"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # {"all": [{"field": "description", "op": "contains", "value": "SWIGGY"}, ...]}
    conditions: Mapped[dict] = mapped_column(JSONType, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    set_merchant: Mapped[str | None] = mapped_column(String(200))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category = relationship("Category")


class MerchantAlias(IdMixin, Base):
    __tablename__ = "merchant_aliases"
    __table_args__ = (CheckConstraint("match_type IN ('contains','regex','exact')", name="ck_alias_match"),)

    pattern: Mapped[str] = mapped_column(String(200), nullable=False)
    match_type: Mapped[str] = mapped_column(String(10), nullable=False, default="contains")
    merchant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)


class Budget(IdMixin, TimestampMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", "month", name="uq_budget_category_month"),)

    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    # First day of month; NULL = default budget for every month
    month: Mapped[date | None] = mapped_column(Date)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RecurringTransaction(IdMixin, TimestampMixin, Base):
    __tablename__ = "recurring_transactions"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    match_key: Mapped[str] = mapped_column(String(200), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    expected_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cadence: Mapped[str] = mapped_column(String(10), nullable=False, default="monthly")
    typical_day: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_date: Mapped[date | None] = mapped_column(Date)

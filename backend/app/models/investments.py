from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, Quantity, TimestampMixin

INSTRUMENT_TYPES = ("stock", "etf", "mutual_fund", "bond", "government_security", "fixed_deposit", "other")
INVESTMENT_TXN_TYPES = (
    "buy", "sell", "dividend", "interest", "reinvestment", "charge", "tax", "split", "bonus",
    "redemption", "maturity", "contribution", "withdrawal", "transfer_in", "transfer_out", "other",
)


def _in(values) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


class InvestmentInstrument(IdMixin, TimestampMixin, Base):
    __tablename__ = "investment_instruments"
    __table_args__ = (
        CheckConstraint(f"instrument_type IN {_in(INSTRUMENT_TYPES)}", name="ck_instrument_type"),
        UniqueConstraint("identifier", name="uq_instrument_identifier"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(30), nullable=False)
    identifier: Mapped[str] = mapped_column(String(60), nullable=False)  # ISIN / scheme code / symbol
    symbol: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    issuer: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


class InvestmentTransaction(IdMixin, TimestampMixin, Base):
    """Investment activity. gross_amount_minor and charges_minor are non-negative magnitudes."""

    __tablename__ = "investment_transactions"
    __table_args__ = (
        CheckConstraint(f"transaction_type IN {_in(INVESTMENT_TXN_TYPES)}", name="ck_inv_txn_type"),
        CheckConstraint("gross_amount_minor >= 0 AND charges_minor >= 0", name="ck_inv_txn_nonneg"),
        Index("ix_inv_txn_holding", "account_id", "instrument_id", "transaction_date"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("investment_instruments.id", ondelete="RESTRICT"))
    source_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    source_statement_id: Mapped[int | None] = mapped_column(ForeignKey("statements.id", ondelete="SET NULL"))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    unit_price: Mapped[Decimal | None] = mapped_column(Quantity)
    gross_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    charges_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    split_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))  # new units per old unit
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    notes: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)

    instrument = relationship("InvestmentInstrument")


class InvestmentLot(IdMixin, Base):
    """Acquisition lots (rebuilt from transactions). Informational; reporting uses weighted average cost."""

    __tablename__ = "investment_lots"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("investment_instruments.id", ondelete="CASCADE"), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    original_quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    cost_basis_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_investment_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("investment_transactions.id", ondelete="CASCADE")
    )


class InvestmentValuation(IdMixin, TimestampMixin, Base):
    __tablename__ = "investment_valuations"
    __table_args__ = (
        CheckConstraint("source IN ('statement','user_import','manual')", name="ck_valuation_source"),
        CheckConstraint("unit_price IS NOT NULL OR total_value_minor IS NOT NULL", name="ck_valuation_has_value"),
        Index("ix_valuation_instrument_date", "instrument_id", "valuation_date"),
    )

    instrument_id: Mapped[int] = mapped_column(ForeignKey("investment_instruments.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    unit_price: Mapped[Decimal | None] = mapped_column(Quantity)
    total_value_minor: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(15), nullable=False)
    source_statement_id: Mapped[int | None] = mapped_column(ForeignKey("statements.id", ondelete="SET NULL"))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)


class FixedDeposit(IdMixin, TimestampMixin, Base):
    __tablename__ = "fixed_deposits"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, unique=True)
    principal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    opening_date: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))  # % per annum
    compounding: Mapped[str | None] = mapped_column(String(15))  # quarterly|monthly|yearly|simple
    reported_maturity_value_minor: Mapped[int | None] = mapped_column(BigInteger)
    reported_value_minor: Mapped[int | None] = mapped_column(BigInteger)
    valuation_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")  # active|matured|closed
    notes: Mapped[str | None] = mapped_column(Text)

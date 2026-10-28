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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, JSONType, TimestampMixin, utcnow

BATCH_STATUSES = ("preview", "committed", "failed", "discarded", "deleted")


class ImportBatch(IdMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint("status IN ('preview','committed','failed','discarded','deleted')", name="ck_batch_status"),
        Index("ix_batches_hash", "file_hash"),
    )

    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_reference: Mapped[str | None] = mapped_column(String(255))
    parser_name: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str | None] = mapped_column(String(20))
    parser_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    parser_profile_id: Mapped[int | None] = mapped_column(ForeignKey("parser_profiles.id", ondelete="SET NULL"))
    detected_institution: Mapped[str | None] = mapped_column(String(120))
    detected_statement_type: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="preview")
    row_counts: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    validation: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    statement_meta: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    extraction_info: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    repeat_of_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))
    reprocess_of_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(IdMixin, Base):
    """A staged candidate transaction. Never part of the ledger until committed."""

    __tablename__ = "import_rows"
    __table_args__ = (
        CheckConstraint("status IN ('ok','warning','error')", name="ck_import_row_status"),
        CheckConstraint("duplicate_status IN ('none','exact','possible')", name="ck_import_row_dup"),
        UniqueConstraint("batch_id", "row_index", name="uq_import_row_index"),
    )

    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(120))
    raw: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    txn_date: Mapped[date | None] = mapped_column(Date)
    posting_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(120))
    debit_minor: Mapped[int | None] = mapped_column(BigInteger)
    credit_minor: Mapped[int | None] = mapped_column(BigInteger)
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    balance_minor: Mapped[int | None] = mapped_column(BigInteger)
    transaction_type: Mapped[str | None] = mapped_column(String(30))
    # Effective decision. include_override records an explicit user choice (None = automatic).
    include: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_override: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ok")
    errors: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    duplicate_status: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    duplicate_of_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))


class ParserProfile(IdMixin, TimestampMixin, Base):
    """A user-saved column mapping that behaves like a parser for matching files."""

    __tablename__ = "parser_profiles"
    __table_args__ = (UniqueConstraint("name", name="uq_parser_profile_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(120))
    statement_type: Mapped[str] = mapped_column(String(30), nullable=False, default="bank")
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # {"date": "Txn Date", "description": "Narration", "debit": "Withdrawal", ...}
    column_mapping: Mapped[dict] = mapped_column(JSONType, nullable=False)
    options: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    header_signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    header_columns: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    default_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

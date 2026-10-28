"""Data structures shared by extraction, parsers, validation and the import service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class ExtractedTable:
    rows: list[list[Any]]  # raw cell values (str, float, datetime, None)
    source: str  # e.g. "sheet:Statement" or "page:2:table:1"
    page: int | None = None


@dataclass
class ExtractedPage:
    number: int  # 1-based
    text: str
    words: list[Word] = field(default_factory=list)
    width: float = 0
    ocr: bool = False


@dataclass
class ExtractedDocument:
    filename: str
    file_type: str  # csv | xlsx | xls | pdf
    path: Path | None = None
    text: str = ""
    pages: list[ExtractedPage] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    is_scanned: bool = False
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)

    def info(self) -> dict:
        return {
            "file_type": self.file_type,
            "page_count": len(self.pages),
            "table_count": len(self.tables),
            "is_scanned": self.is_scanned,
            "ocr_used": self.ocr_used,
            "text_chars": len(self.text),
        }


@dataclass
class CandidateRow:
    row_index: int
    source_ref: str | None = None
    txn_date: date | None = None
    posting_date: date | None = None
    description: str | None = None
    reference: str | None = None
    debit: Decimal | None = None  # magnitude of money out (holder perspective)
    credit: Decimal | None = None  # magnitude of money in
    amount: Decimal | None = None  # signed, holder perspective (+ in, - out)
    balance: Decimal | None = None  # running balance after this row, holder perspective
    transaction_type: str | None = None
    raw: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedStatement:
    parser_name: str
    parser_version: str
    statement_type: str = "bank"  # bank | credit_card | investment
    institution: str | None = None
    account_hint: str | None = None  # masked account / card number found in the document
    currency: str = "INR"
    period_start: date | None = None
    period_end: date | None = None
    opening_balance: Decimal | None = None  # holder perspective
    closing_balance: Decimal | None = None  # holder perspective
    rows: list[CandidateRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ignored_lines: list[dict] = field(default_factory=list)  # visible, never silently dropped
    needs_mapping: bool = False
    mapping_used: dict | None = None
    header_columns: list[str] = field(default_factory=list)
    candidate_headers: list[list[str]] = field(default_factory=list)
    layout_signature: str | None = None
    extra: dict = field(default_factory=dict)  # e.g. investment holdings for investment parsers


@dataclass
class ParseOptions:
    column_mapping: dict | None = None  # role -> column header
    sign_mode: str | None = None  # signed | inverted (single amount column)
    statement_type: str | None = None
    date_format: str | None = None
    header_row: int | None = None
    table_index: int | None = None

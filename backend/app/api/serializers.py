"""Model → JSON dict conversion for API responses. Money stays in integer minor units."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.models import (
    Account,
    ImportBatch,
    ImportRow,
    InvestmentInstrument,
    InvestmentTransaction,
    InvestmentValuation,
    Statement,
    Transaction,
    TransactionRelationship,
)
from app.models.ledger import LIABILITY_TYPES
from app.services.ledger.balances import AccountBalance


def iso(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def account(a: Account, bal: AccountBalance | None = None) -> dict:
    d = {
        "id": a.id, "name": a.name, "institution": a.institution, "account_type": a.account_type,
        "custom_type_label": a.custom_type_label, "is_liability": a.account_type in LIABILITY_TYPES or a.is_liability,
        "currency": a.currency, "masked_identifier": a.masked_identifier,
        "opening_balance_minor": a.opening_balance_minor, "opening_date": iso(a.opening_date),
        "opening_verification": a.opening_verification, "opening_source": a.opening_source,
        "is_active": a.is_active, "notes": a.notes, "default_parser": a.default_parser,
        "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
    }
    if bal is not None:
        d.update({
            "calculated_balance_minor": bal.calculated_balance_minor, "movements_minor": bal.movements_minor,
            "balance_status": bal.balance_status, "first_transaction_date": iso(bal.first_transaction_date),
            "last_transaction_date": iso(bal.last_transaction_date), "coverage_start": iso(bal.coverage_start),
            "coverage_end": iso(bal.coverage_end), "last_statement_date": iso(bal.last_statement_date),
            "last_statement_balance_minor": bal.last_statement_balance_minor, "last_import_at": bal.last_import_at,
            "reconciliation_status": bal.reconciliation_status, "statement_count": bal.statement_count,
        })
    return d


def transaction(t: Transaction, category_names: dict | None = None, account_names: dict | None = None) -> dict:
    return {
        "id": t.id, "account_id": t.account_id,
        "account_name": account_names.get(t.account_id) if account_names else None,
        "statement_id": t.statement_id, "import_batch_id": t.import_batch_id,
        "transaction_date": iso(t.transaction_date), "posting_date": iso(t.posting_date),
        "original_description": t.original_description, "normalized_description": t.normalized_description,
        "merchant": t.merchant, "amount_minor": t.amount_minor, "original_amount_minor": t.original_amount_minor,
        "original_date": iso(t.original_date), "currency": t.currency, "direction": t.direction,
        "transaction_type": t.transaction_type, "reference": t.reference, "balance_after_minor": t.balance_after_minor,
        "category_id": t.category_id,
        "category_name": category_names.get(t.category_id) if category_names and t.category_id else None,
        "category_source": t.category_source, "rule_id": t.rule_id, "tags": t.tags or [], "notes": t.notes,
        "review_status": t.review_status, "reconciliation_status": t.reconciliation_status,
        "duplicate_status": t.duplicate_status, "source_row_reference": t.source_row_reference,
        "parser_name": t.parser_name, "parser_version": t.parser_version, "is_manual": t.is_manual,
        "created_at": iso(t.created_at), "updated_at": iso(t.updated_at),
    }


def relationship(r: TransactionRelationship, include_txns: bool = True, account_names: dict | None = None) -> dict:
    d = {
        "id": r.id, "source_transaction_id": r.source_transaction_id,
        "related_transaction_id": r.related_transaction_id, "relationship_type": r.relationship_type,
        "matched_amount_minor": r.matched_amount_minor, "review_status": r.review_status,
        "score": float(r.score) if r.score is not None else None, "matching_reason": r.matching_reason,
        "notes": r.notes, "created_at": iso(r.created_at), "reviewed_at": iso(r.reviewed_at),
        "approved_at": iso(r.approved_at),
    }
    if include_txns:
        d["source"] = transaction(r.source, account_names=account_names) if r.source else None
        d["related"] = transaction(r.related, account_names=account_names) if r.related else None
    return d


def import_row(r: ImportRow) -> dict:
    return {
        "id": r.id, "row_index": r.row_index, "source_ref": r.source_ref, "raw": r.raw,
        "txn_date": iso(r.txn_date), "posting_date": iso(r.posting_date), "description": r.description,
        "reference": r.reference, "debit_minor": r.debit_minor, "credit_minor": r.credit_minor,
        "amount_minor": r.amount_minor, "balance_minor": r.balance_minor, "transaction_type": r.transaction_type,
        "include": r.include, "include_override": r.include_override, "status": r.status, "errors": r.errors,
        "warnings": r.warnings, "duplicate_status": r.duplicate_status,
        "duplicate_of_transaction_id": r.duplicate_of_transaction_id, "user_edited": r.user_edited,
        "transaction_id": r.transaction_id,
    }


def batch(b: ImportBatch) -> dict:
    return {
        "id": b.id, "account_id": b.account_id, "filename": b.filename, "file_hash": b.file_hash,
        "file_type": b.file_type, "file_size": b.file_size, "has_file": bool(b.storage_reference),
        "parser_name": b.parser_name, "parser_version": b.parser_version,
        "parser_confidence": float(b.parser_confidence) if b.parser_confidence is not None else None,
        "parser_profile_id": b.parser_profile_id, "detected_institution": b.detected_institution,
        "detected_statement_type": b.detected_statement_type, "status": b.status, "row_counts": b.row_counts,
        "warnings": b.warnings, "validation": b.validation, "statement_meta": b.statement_meta,
        "extraction_info": b.extraction_info, "repeat_of_batch_id": b.repeat_of_batch_id,
        "reprocess_of_batch_id": b.reprocess_of_batch_id, "error_message": b.error_message,
        "created_at": iso(b.created_at), "committed_at": iso(b.committed_at),
    }


def statement(s: Statement) -> dict:
    return {
        "id": s.id, "account_id": s.account_id, "import_batch_id": s.import_batch_id,
        "start_date": iso(s.start_date), "end_date": iso(s.end_date),
        "reported_opening_minor": s.reported_opening_minor, "reported_closing_minor": s.reported_closing_minor,
        "calculated_closing_minor": s.calculated_closing_minor, "discrepancy_minor": s.discrepancy_minor,
        "currency": s.currency, "reconciliation_status": s.reconciliation_status, "notes": s.notes,
    }


def instrument(i: InvestmentInstrument) -> dict:
    return {"id": i.id, "name": i.name, "instrument_type": i.instrument_type, "identifier": i.identifier,
            "symbol": i.symbol, "currency": i.currency, "issuer": i.issuer, "notes": i.notes}


def investment_txn(t: InvestmentTransaction) -> dict:
    return {
        "id": t.id, "account_id": t.account_id, "instrument_id": t.instrument_id,
        "instrument_name": t.instrument.name if t.instrument else None,
        "source_transaction_id": t.source_transaction_id, "transaction_date": iso(t.transaction_date),
        "transaction_type": t.transaction_type, "quantity": iso(t.quantity), "unit_price": iso(t.unit_price),
        "gross_amount_minor": t.gross_amount_minor, "charges_minor": t.charges_minor,
        "split_ratio": iso(t.split_ratio), "currency": t.currency, "notes": t.notes,
        "import_batch_id": t.import_batch_id,
    }


def valuation(v: InvestmentValuation) -> dict:
    return {"id": v.id, "instrument_id": v.instrument_id, "account_id": v.account_id,
            "valuation_date": iso(v.valuation_date), "quantity": iso(v.quantity), "unit_price": iso(v.unit_price),
            "total_value_minor": v.total_value_minor, "source": v.source, "notes": v.notes,
            "import_batch_id": v.import_batch_id}

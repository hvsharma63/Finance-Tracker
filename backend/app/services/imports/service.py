"""Import pipeline orchestration: upload → preview → corrections → commit / discard / delete / reprocess.

Parsers never write to the ledger. Rows are staged in import_rows; commit happens in one
database transaction so an interrupted import cannot leave half-written records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dates import DateParseError, parse_date
from app.core.errors import AppError, Conflict, NotFound
from app.core.money import MoneyParseError, from_minor, parse_amount, to_minor
from app.models import (
    Account,
    BalanceSnapshot,
    ImportBatch,
    ImportRow,
    ParserProfile,
    Statement,
    Transaction,
    TransactionRelationship,
)
from app.services.categorization.engine import apply_rules
from app.services.imports import extraction, passwords, storage
from app.services.imports.candidates import CandidateRow, ExtractedDocument, ParsedStatement, ParseOptions
from app.services.imports.metadata import mask_identifier
from app.services.imports.normalization import clean_text, detect_transaction_type, normalize_description
from app.services.imports.parser_registry import get_parser, rank_parsers
from app.services.imports.table_mapping import candidate_headers, header_signature
from app.services.imports.validation import validate
from app.services.ledger import audit
from app.services.ledger.seed import get_setting
from app.services.reconciliation.duplicates import detect_duplicates
from app.services.reconciliation.matching import suggest_matches
from app.services.reconciliation.statements import reconcile


@dataclass
class UploadRequest:
    filename: str
    data: bytes
    account_id: int | None = None
    parser_name: str | None = None
    profile_id: int | None = None
    password: str | None = None
    statement_type: str | None = None
    force_ocr: bool = False
    remember_password: bool = True


def _minor(d: Decimal | None, currency: str = "INR") -> int | None:
    return None if d is None else to_minor(d, currency)


def _sanitize_filename(name: str) -> str:
    base = re.split(r"[\\/]", name or "statement")[-1]
    return re.sub(r"[^\w.\- ()]", "_", base)[:200] or "statement"


# ----------------------------------------------------------------------------- parser selection

def _profile_match(db: Session, doc: ExtractedDocument) -> ParserProfile | None:
    profiles = list(db.scalars(select(ParserProfile).where(ParserProfile.enabled.is_(True))))
    if not profiles:
        return None
    sigs = set()
    for t in doc.tables:
        for row in t.rows[:60]:
            if row:
                sigs.add(header_signature([str(c or "") for c in row]))
    return next((p for p in profiles if p.header_signature in sigs), None)


def _run_parser(db: Session, doc: ExtractedDocument, req_parser: str | None, profile_id: int | None,
                options: ParseOptions) -> tuple[ParsedStatement, float, ParserProfile | None, list[dict]]:
    ranked = rank_parsers(doc)
    ranking = [{"parser": r.parser.name, "confidence": round(r.confidence, 3)} for r in ranked]
    profile = db.get(ParserProfile, profile_id) if profile_id else None
    if profile is None and not req_parser and not options.column_mapping:
        best_specific = next((r for r in ranked if not r.parser.is_generic and r.confidence >= 0.5), None)
        if best_specific is None:
            profile = _profile_match(db, doc)
    if profile is not None:
        options.column_mapping = options.column_mapping or profile.column_mapping
        options.sign_mode = options.sign_mode or profile.options.get("sign_mode")
        options.date_format = options.date_format or profile.options.get("date_format")
        options.statement_type = options.statement_type or profile.statement_type
        parser = get_parser("generic_pdf" if doc.file_type == "pdf" else "generic_table")
        ps = parser.parse(doc, options)
        ps.parser_name, ps.parser_version = f"profile:{profile.name}", f"p{profile.version}"
        ps.institution = ps.institution or profile.institution
        return ps, 0.9, profile, ranking
    if req_parser:
        parser = get_parser(req_parser)
        if parser is None:
            raise AppError(f"Unknown parser {req_parser}")
        return parser.parse(doc, options), next((r["confidence"] for r in ranking if r["parser"] == req_parser), 0), None, ranking
    if not ranked:
        raise AppError("No parser supports this file type", code="unsupported_type")
    best = ranked[0]
    return best.parser.parse(doc, options), best.confidence, None, ranking


# ----------------------------------------------------------------------------- staging

def _stage_rows(batch: ImportBatch, ps: ParsedStatement, currency: str) -> list[ImportRow]:
    rows = []
    for c in ps.rows:
        status = "error" if c.errors else ("warning" if c.warnings else "ok")
        rows.append(ImportRow(
            batch_id=batch.id, row_index=c.row_index, source_ref=c.source_ref, raw=_jsonable(c.raw),
            txn_date=c.txn_date, posting_date=c.posting_date, description=c.description, reference=c.reference,
            debit_minor=_minor(c.debit, currency), credit_minor=_minor(c.credit, currency),
            amount_minor=_minor(c.amount, currency), balance_minor=_minor(c.balance, currency),
            transaction_type=c.transaction_type, status=status, errors=list(c.errors), warnings=list(c.warnings),
            include=status != "error",
        ))
    return rows


def _jsonable(d: dict) -> dict:
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[str(k)] = v
        elif isinstance(v, list):
            out[str(k)] = [str(x) for x in v]
        else:
            out[str(k)] = str(v)
    return out


def _rows_as_candidates(rows: list[ImportRow]) -> list[CandidateRow]:
    """Rows that belong to the statement (for validation): everything except user-excluded rows."""
    out = []
    for r in sorted(rows, key=lambda r: r.row_index):
        if r.include_override is False and r.duplicate_status != "exact":
            continue
        amount = from_minor(r.amount_minor) if r.amount_minor is not None else None
        out.append(CandidateRow(
            row_index=r.row_index, source_ref=r.source_ref, txn_date=r.txn_date, description=r.description,
            amount=amount, balance=from_minor(r.balance_minor) if r.balance_minor is not None else None,
            errors=list(r.errors), warnings=list(r.warnings),
        ))
    return out


def _meta_from(ps: ParsedStatement) -> dict:
    return {
        "statement_type": ps.statement_type,
        "institution": ps.institution,
        "account_hint": mask_identifier(ps.account_hint),
        "currency": ps.currency,
        "period_start": ps.period_start.isoformat() if ps.period_start else None,
        "period_end": ps.period_end.isoformat() if ps.period_end else None,
        "opening_balance_minor": _minor(ps.opening_balance),
        "closing_balance_minor": _minor(ps.closing_balance),
        "needs_mapping": ps.needs_mapping,
        "mapping_used": ps.mapping_used,
        "header_columns": ps.header_columns,
        "candidate_headers": ps.candidate_headers[:5],
        "layout_signature": ps.layout_signature,
        "ignored_lines": ps.ignored_lines[:500],
        "ignored_line_count": len(ps.ignored_lines),
        "extra": _jsonable(ps.extra),
    }


def _ps_for_validation(batch: ImportBatch) -> ParsedStatement:
    m = batch.statement_meta or {}
    ps = ParsedStatement(parser_name=batch.parser_name or "", parser_version=batch.parser_version or "")
    ps.period_start = date.fromisoformat(m["period_start"]) if m.get("period_start") else None
    ps.period_end = date.fromisoformat(m["period_end"]) if m.get("period_end") else None
    if m.get("opening_balance_minor") is not None:
        ps.opening_balance = from_minor(m["opening_balance_minor"])
    if m.get("closing_balance_minor") is not None:
        ps.closing_balance = from_minor(m["closing_balance_minor"])
    return ps


def refresh_preview(db: Session, batch: ImportBatch) -> None:
    """Re-run duplicate detection, validation and counts on the staged rows."""
    rows = list(db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.row_index)))
    for r in rows:
        r.status = "error" if r.errors else ("warning" if r.warnings else "ok")
    dup = {"exact": 0, "possible": 0}
    if batch.account_id:
        dup = detect_duplicates(db, batch.account_id, rows, int(get_setting(db, "possible_duplicate_window_days", 2)),
                                exclude_batch_id=batch.id)
    else:
        for r in rows:
            r.include = r.include_override if r.include_override is not None else True
    for r in rows:
        if r.status == "error":
            r.include = False
    rep = validate(_ps_for_validation(batch), _rows_as_candidates(rows))
    batch.validation = rep.to_dict()
    batch.row_counts = {
        "extracted": len(rows),
        "to_import": sum(1 for r in rows if r.include),
        "errors": sum(1 for r in rows if r.status == "error"),
        "warnings": sum(1 for r in rows if r.status == "warning"),
        "exact_duplicates": dup["exact"],
        "possible_duplicates": dup["possible"],
        "excluded_by_user": sum(1 for r in rows if r.include_override is False),
        "ignored_lines": (batch.statement_meta or {}).get("ignored_line_count", 0),
    }
    db.flush()


def _suggest_account(db: Session, ps: ParsedStatement) -> int | None:
    hint = mask_identifier(ps.account_hint)
    if not hint:
        return None
    digits = re.sub(r"\D", "", hint)[-4:]
    if not digits:
        return None
    wanted_type = "credit_card" if ps.statement_type == "credit_card" else None
    matches = []
    for a in db.scalars(select(Account).where(Account.is_active.is_(True))):
        mine = re.sub(r"\D", "", a.masked_identifier or "")[-4:]
        # some issuers print only the last 2 digits; compare the overlapping suffix
        n = min(len(mine), len(digits))
        if n >= 2 and mine[-n:] == digits[-n:]:
            if wanted_type and a.account_type != wanted_type:
                continue
            if ps.institution and a.institution and n < 4 and                     ps.institution.split()[0].lower() not in a.institution.lower():
                continue
            matches.append(a.id)
    return matches[0] if len(matches) == 1 else None


def _layout_warnings(db: Session, batch: ImportBatch, confidence: float) -> list[str]:
    out = []
    if not batch.account_id:
        return out
    prev = db.scalar(
        select(ImportBatch).where(ImportBatch.account_id == batch.account_id, ImportBatch.status == "committed",
                                  ImportBatch.id != batch.id).order_by(ImportBatch.committed_at.desc()).limit(1))
    if prev is None:
        return out
    if prev.parser_name != batch.parser_name:
        out.append(f"This account was previously imported with parser '{prev.parser_name}', but this file "
                   f"was read with '{batch.parser_name}'. The statement format may have changed — review carefully.")
    elif prev.parser_version != batch.parser_version:
        out.append(f"Parser version changed since the last import ({prev.parser_version} → {batch.parser_version}).")
    prev_sig = (prev.statement_meta or {}).get("layout_signature")
    sig = (batch.statement_meta or {}).get("layout_signature")
    if prev_sig and sig and prev_sig != sig and prev.parser_name == batch.parser_name:
        out.append("The column layout differs from the previous statement for this account. Possible format change.")
    if batch.parser_name and not batch.parser_name.startswith("generic") and confidence < 0.6:
        out.append("Low parser confidence: the document only partly matches the expected format.")
    return out


def create_preview(db: Session, req: UploadRequest) -> ImportBatch:
    settings = get_settings()
    if len(req.data) == 0:
        raise AppError("The uploaded file is empty", code="empty_file")
    if len(req.data) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(f"File exceeds the {settings.max_upload_mb} MB limit", code="file_too_large", status_code=413)
    filename = _sanitize_filename(req.filename)
    kind = extraction.sniff_file_type(req.data, filename)
    if req.account_id is not None and db.get(Account, req.account_id) is None:
        raise NotFound(f"Account {req.account_id} not found")
    file_hash = storage.sha256(req.data)
    stored_type = "xls" if kind == "html_table" else kind
    ref, path = storage.store(req.data, stored_type)
    batch = ImportBatch(filename=filename, file_hash=file_hash, file_type=stored_type, file_size=len(req.data),
                        storage_reference=ref, account_id=req.account_id, status="preview")
    repeat = db.scalar(select(ImportBatch).where(ImportBatch.file_hash == file_hash, ImportBatch.status == "committed")
                       .order_by(ImportBatch.id).limit(1))
    db.add(batch)
    db.flush()
    try:
        _parse_into(db, batch, req.data, path, ParseOptions(statement_type=req.statement_type),
                    req.parser_name, req.profile_id, req.password, req.force_ocr, req.remember_password)
    except extraction.ExtractionError as e:
        batch.status = "failed"
        batch.error_message = str(e)
        batch.extraction_info = {"error_code": e.code}
        db.flush()
        audit.record(db, "import_batch", batch.id, "failed", {"code": e.code})
        return batch
    warnings = list(batch.warnings)
    if repeat is not None:
        batch.repeat_of_batch_id = repeat.id
        warnings.insert(0, f"This exact file was already imported (batch #{repeat.id}, {repeat.filename}). "
                           "Rows already in the ledger are marked as duplicates and will not be imported again.")
    batch.warnings = warnings
    audit.record(db, "import_batch", batch.id, "preview_created", {"parser": batch.parser_name})
    return batch


def _extract(db: Session, batch: ImportBatch, data: bytes, path, password: str | None,
             force_ocr: bool) -> tuple[ExtractedDocument, str]:
    """Extract, trying saved PDF passwords when the file is protected and none was given."""
    try:
        doc = extraction.extract(data, batch.filename, path=path, password=password, force_ocr=force_ocr)
        return doc, ("provided" if password and batch.file_type == "pdf" else "none")
    except extraction.ExtractionError as e:
        if e.code != "pdf_password_required" or password:
            raise
    for saved, pw in passwords.candidates(db, batch.account_id):
        try:
            doc = extraction.extract(data, batch.filename, path=path, password=pw, force_ocr=force_ocr)
        except extraction.ExtractionError as e:
            if e.code == "pdf_password_incorrect":
                continue
            raise
        passwords.mark_used(saved, batch.account_id)
        doc.warnings.append(f"Opened with the saved password “{saved.label}”.")
        return doc, f"saved:{saved.id}"
    raise extraction.ExtractionError(
        "This PDF is password-protected and none of the saved passwords opened it. Enter its password.",
        "pdf_password_required")


def _parse_into(db: Session, batch: ImportBatch, data: bytes, path, options: ParseOptions,
                parser_name: str | None, profile_id: int | None, password: str | None, force_ocr: bool,
                remember_password: bool = True) -> None:
    doc, pw_source = _extract(db, batch, data, path, password, force_ocr)
    ps, confidence, profile, ranking = _run_parser(db, doc, parser_name, profile_id, options)
    if pw_source == "provided" and remember_password:
        label = " ".join(x for x in (ps.institution, {"credit_card": "credit card", "bank": "bank account"}
                                     .get(ps.statement_type, ps.statement_type)) if x) or batch.filename
        saved = passwords.save(db, label, password, batch.account_id)
        pw_source = f"saved:{saved.id}"
        doc.warnings.append(f"Password remembered as “{saved.label}” for future statements.")
    batch.parser_name, batch.parser_version = ps.parser_name, ps.parser_version
    batch.parser_confidence = round(confidence, 3)
    batch.parser_profile_id = profile.id if profile else None
    batch.detected_institution = ps.institution
    batch.detected_statement_type = ps.statement_type
    batch.extraction_info = doc.info() | {"parser_ranking": ranking, "password": pw_source}
    if not ps.candidate_headers:
        ps.candidate_headers = [c["headers"] for c in candidate_headers(doc.tables)]
    batch.statement_meta = _meta_from(ps)
    if batch.account_id is None:
        batch.account_id = _suggest_account(db, ps)
        if batch.account_id:
            batch.statement_meta = batch.statement_meta | {"account_suggested": True}
    db.execute(ImportRow.__table__.delete().where(ImportRow.batch_id == batch.id))
    account = db.get(Account, batch.account_id) if batch.account_id else None
    for r in _stage_rows(batch, ps, account.currency if account else ps.currency):
        db.add(r)
    db.flush()
    batch.warnings = list(dict.fromkeys(doc.warnings + ps.warnings + _layout_warnings(db, batch, confidence)))
    if account and account.account_type == "credit_card" and ps.statement_type != "credit_card":
        batch.warnings = batch.warnings + ["Selected account is a credit card but the file looks like a bank "
                                           "statement. Check the sign convention."]
    refresh_preview(db, batch)


def _get_preview_batch(db: Session, batch_id: int) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFound(f"Import batch {batch_id} not found")
    if batch.status != "preview":
        raise Conflict(f"Import batch {batch_id} is {batch.status}; only previews can be changed")
    return batch


def set_account(db: Session, batch_id: int, account_id: int) -> ImportBatch:
    batch = _get_preview_batch(db, batch_id)
    if db.get(Account, account_id) is None:
        raise NotFound(f"Account {account_id} not found")
    batch.account_id = account_id
    refresh_preview(db, batch)
    return batch


def update_statement_meta(db: Session, batch_id: int, changes: dict) -> ImportBatch:
    batch = _get_preview_batch(db, batch_id)
    meta = dict(batch.statement_meta or {})
    for key in ("period_start", "period_end", "opening_balance_minor", "closing_balance_minor"):
        if key in changes:
            meta[key] = changes[key]
    meta["user_edited"] = True
    batch.statement_meta = meta
    refresh_preview(db, batch)
    return batch


def reparse(db: Session, batch_id: int, *, column_mapping: dict | None = None, sign_mode: str | None = None,
            parser_name: str | None = None, statement_type: str | None = None, date_format: str | None = None,
            header_row: int | None = None, table_index: int | None = None, password: str | None = None,
            force_ocr: bool = False) -> ImportBatch:
    """Re-run parsing on the stored file with a manual mapping or another parser."""
    batch = _get_preview_batch(db, batch_id)
    path = storage.resolve(batch.storage_reference)
    data = path.read_bytes()
    opts = ParseOptions(column_mapping=column_mapping, sign_mode=sign_mode, statement_type=statement_type,
                        date_format=date_format, header_row=header_row, table_index=table_index)
    try:
        _parse_into(db, batch, data, path, opts, parser_name, None, password, force_ocr)
    except extraction.ExtractionError as e:
        raise AppError(str(e), code=e.code)
    return batch


def update_row(db: Session, batch_id: int, row_id: int, changes: dict) -> ImportRow:
    """Apply a user correction to a staged row. Original raw values stay in row.raw."""
    batch = _get_preview_batch(db, batch_id)
    row = db.get(ImportRow, row_id)
    if row is None or row.batch_id != batch.id:
        raise NotFound(f"Row {row_id} not found in batch {batch_id}")
    errors: list[str] = []
    edited = False
    if "_original" not in (row.raw or {}) and set(changes) & {"txn_date", "description", "amount", "balance"}:
        row.raw = dict(row.raw or {}) | {"_original": {
            "txn_date": row.txn_date.isoformat() if row.txn_date else None, "description": row.description,
            "amount_minor": row.amount_minor, "balance_minor": row.balance_minor}}
    if "txn_date" in changes:
        try:
            row.txn_date = parse_date(changes["txn_date"])
            edited = True
        except DateParseError:
            raise AppError(f"Invalid date {changes['txn_date']!r}")
    if "description" in changes:
        row.description = clean_text(changes["description"])
        row.transaction_type = detect_transaction_type(row.description)
        edited = True
    if "amount" in changes:
        try:
            v, direction = parse_amount(changes["amount"])
        except MoneyParseError:
            raise AppError(f"Invalid amount {changes['amount']!r}")
        if v is None:
            raise AppError("Amount is required")
        if direction == "DR":
            v = -abs(v)
        elif direction == "CR":
            v = abs(v)
        row.amount_minor = to_minor(v)
        row.debit_minor = -row.amount_minor if row.amount_minor < 0 else None
        row.credit_minor = row.amount_minor if row.amount_minor > 0 else None
        edited = True
    if "balance" in changes:
        try:
            v, d = parse_amount(changes["balance"]) if changes["balance"] not in (None, "") else (None, None)
        except MoneyParseError:
            raise AppError(f"Invalid balance {changes['balance']!r}")
        row.balance_minor = None if v is None else to_minor(-abs(v) if d == "DR" else v)
        edited = True
    if "include" in changes:
        row.include_override = None if changes["include"] is None else bool(changes["include"])
    if edited:
        row.user_edited = True
        if row.txn_date is None:
            errors.append("Missing transaction date")
        if row.amount_minor is None:
            errors.append("Missing amount")
        row.errors = errors
        row.warnings = list(dict.fromkeys(list(row.warnings or []) + ["Corrected by user"]))
    refresh_preview(db, batch)
    return row


def discard(db: Session, batch_id: int, delete_file: bool = True) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFound(f"Import batch {batch_id} not found")
    if batch.status not in ("preview", "failed"):
        raise Conflict("Only previews or failed imports can be discarded; delete committed imports instead")
    db.execute(ImportRow.__table__.delete().where(ImportRow.batch_id == batch.id))
    batch.status = "discarded"
    if delete_file and not _file_shared(db, batch):
        storage.delete(batch.storage_reference)
        batch.storage_reference = None
    audit.record(db, "import_batch", batch.id, "discarded")
    return batch


def _file_shared(db: Session, batch: ImportBatch) -> bool:
    return bool(db.scalar(select(func.count()).select_from(ImportBatch).where(
        ImportBatch.storage_reference == batch.storage_reference, ImportBatch.id != batch.id,
        ImportBatch.status.in_(("preview", "committed")))))


# ----------------------------------------------------------------------------- commit

def refresh_statement_opening(db: Session, account: Account) -> None:
    """Keep an account's statement-derived opening balance equal to its earliest statement."""
    if account.opening_source not in (None, "statement"):
        return
    if account.opening_source is None and account.opening_balance_minor is not None:
        return  # set before tracking began; treat as user-entered
    first = db.scalar(select(Statement).where(Statement.account_id == account.id,
                                              Statement.reported_opening_minor.is_not(None),
                                              Statement.start_date.is_not(None))
                      .order_by(Statement.start_date).limit(1))
    if first is None:
        if account.opening_source == "statement":
            account.opening_balance_minor, account.opening_date, account.opening_source = None, None, None
            account.opening_verification = "unknown"
        return
    account.opening_balance_minor = first.reported_opening_minor
    account.opening_date = first.start_date
    account.opening_source = "statement"
    if account.opening_verification == "unknown":
        account.opening_verification = "unverified"


def commit(db: Session, batch_id: int) -> ImportBatch:
    batch = db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
    if batch is None:
        raise NotFound(f"Import batch {batch_id} not found")
    if batch.status == "committed":
        return batch  # idempotent
    if batch.status != "preview":
        raise Conflict(f"Import batch {batch_id} is {batch.status} and cannot be committed")
    if batch.account_id is None:
        raise AppError("Choose an account before importing", code="account_required")
    account = db.get(Account, batch.account_id)
    refresh_preview(db, batch)  # ledger may have changed since the preview was built
    rows = list(db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.row_index)))
    meta = batch.statement_meta or {}
    to_insert = [r for r in rows if r.include and r.status != "error"]
    if not rows:
        raise AppError("Nothing to import: no transactions were extracted", code="empty_import")

    dates = [r.txn_date for r in rows if r.txn_date]
    stmt = Statement(
        account_id=account.id, import_batch_id=batch.id,
        start_date=date.fromisoformat(meta["period_start"]) if meta.get("period_start") else (min(dates) if dates else None),
        end_date=date.fromisoformat(meta["period_end"]) if meta.get("period_end") else (max(dates) if dates else None),
        reported_opening_minor=meta.get("opening_balance_minor"),
        reported_closing_minor=meta.get("closing_balance_minor"),
        currency=account.currency,
    )
    v = batch.validation or {}
    if stmt.reported_opening_minor is None and v.get("opening_balance") is not None:
        stmt.reported_opening_minor = to_minor(Decimal(v["opening_balance"]))
        stmt.notes = "Opening balance derived from the first running balance."
    if stmt.reported_closing_minor is None and v.get("closing_balance_reported") is not None:
        stmt.reported_closing_minor = to_minor(Decimal(v["closing_balance_reported"]))
    db.add(stmt)
    db.flush()

    new_txns: list[Transaction] = []
    for r in to_insert:
        orig = (r.raw or {}).get("_original") or {}
        t = Transaction(
            account_id=account.id, statement_id=stmt.id, import_batch_id=batch.id,
            transaction_date=r.txn_date, posting_date=r.posting_date,
            original_description=orig.get("description") or r.description or "",
            original_amount_minor=orig["amount_minor"] if orig.get("amount_minor") is not None else r.amount_minor,
            original_date=date.fromisoformat(orig["txn_date"]) if orig.get("txn_date") else r.txn_date,
            source_data={"raw": r.raw, "source_ref": r.source_ref, "user_corrected": r.user_edited},
            normalized_description=normalize_description(r.description), amount_minor=r.amount_minor,
            currency=account.currency, direction="debit" if r.amount_minor < 0 else "credit",
            transaction_type=r.transaction_type, reference=r.reference, balance_after_minor=r.balance_minor,
            fingerprint=r.fingerprint, source_row_reference=r.source_ref,
            parser_name=batch.parser_name, parser_version=batch.parser_version,
            duplicate_status="confirmed_unique" if r.duplicate_status == "possible" else "none",
            tags=[],
        )
        db.add(t)
        new_txns.append(t)
    db.flush()
    for r, t in zip(to_insert, new_txns, strict=False):
        r.transaction_id = t.id
    for kind, val, d in (("statement_opening", stmt.reported_opening_minor, stmt.start_date),
                         ("statement_closing", stmt.reported_closing_minor, stmt.end_date)):
        if val is not None and d is not None:
            db.add(BalanceSnapshot(account_id=account.id, balance_date=d, balance_minor=val, balance_type=kind,
                                   source_statement_id=stmt.id, confidence_status="reported"))
    reconcile(db, stmt)
    refresh_statement_opening(db, account)
    apply_rules(db, new_txns)
    db.flush()
    suggestions = suggest_matches(db, [t.id for t in new_txns]) if new_txns else []
    batch.status = "committed"
    batch.committed_at = datetime.now(timezone.utc)
    batch.row_counts = (batch.row_counts or {}) | {
        "accepted": len(new_txns),
        "rejected": sum(1 for r in rows if r.status == "error"),
        "duplicates_skipped": sum(1 for r in rows if r.duplicate_status == "exact" and not r.include),
        "match_suggestions": len(suggestions),
    }
    if not account.default_parser:
        account.default_parser = batch.parser_name
    audit.record(db, "import_batch", batch.id, "committed",
                 {"account_id": account.id, "accepted": len(new_txns), "statement_id": stmt.id,
                  "reconciliation": stmt.reconciliation_status})
    db.flush()
    return batch


# ----------------------------------------------------------------------------- delete / reprocess

def deletion_impact(db: Session, batch_id: int) -> dict:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFound(f"Import batch {batch_id} not found")
    txn_ids = list(db.scalars(select(Transaction.id).where(Transaction.import_batch_id == batch_id)))
    rels = list(db.scalars(select(TransactionRelationship).where(
        TransactionRelationship.review_status == "approved",
        (TransactionRelationship.source_transaction_id.in_(txn_ids)) |
        (TransactionRelationship.related_transaction_id.in_(txn_ids))))) if txn_ids else []
    edited = db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.import_batch_id == batch_id,
        (Transaction.category_source == "user") | (Transaction.notes.is_not(None)))) if txn_ids else 0
    return {"batch_id": batch_id, "status": batch.status, "transactions": len(txn_ids),
            "approved_relationships": len(rels), "user_edited_transactions": edited or 0}


def delete_batch(db: Session, batch_id: int, *, confirm_linked: bool = False, delete_file: bool = False) -> dict:
    batch = db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
    if batch is None:
        raise NotFound(f"Import batch {batch_id} not found")
    if batch.status != "committed":
        raise Conflict("Only committed imports can be deleted; discard previews instead")
    impact = deletion_impact(db, batch_id)
    if impact["approved_relationships"] and not confirm_linked:
        raise Conflict("This import has approved matches with other transactions. Confirm to delete them too.",
                       details=impact)
    from app.models import InvestmentTransaction

    txn_ids = list(db.scalars(select(Transaction.id).where(Transaction.import_batch_id == batch_id)))
    if txn_ids:
        db.execute(InvestmentTransaction.__table__.update().where(
            InvestmentTransaction.source_transaction_id.in_(txn_ids)).values(source_transaction_id=None))
        db.execute(TransactionRelationship.__table__.delete().where(
            TransactionRelationship.source_transaction_id.in_(txn_ids) |
            TransactionRelationship.related_transaction_id.in_(txn_ids)))
        db.execute(ImportRow.__table__.update().where(ImportRow.duplicate_of_transaction_id.in_(txn_ids))
                   .values(duplicate_of_transaction_id=None))
        db.execute(ImportRow.__table__.update().where(ImportRow.transaction_id.in_(txn_ids)).values(transaction_id=None))
        db.execute(Transaction.__table__.delete().where(Transaction.id.in_(txn_ids)))
    stmt = db.scalar(select(Statement).where(Statement.import_batch_id == batch_id))
    if stmt is not None:
        db.execute(BalanceSnapshot.__table__.delete().where(BalanceSnapshot.source_statement_id == stmt.id))
        db.delete(stmt)
    db.flush()
    batch.status = "deleted"
    account = db.get(Account, batch.account_id)
    if account is not None:
        refresh_statement_opening(db, account)
    if delete_file and not _file_shared(db, batch):
        storage.delete(batch.storage_reference)
        batch.storage_reference = None
    audit.record(db, "import_batch", batch.id, "deleted", impact)
    db.flush()
    return impact


def reprocess(db: Session, batch_id: int, parser_name: str | None = None, password: str | None = None) -> tuple[ImportBatch, dict]:
    """Re-parse a committed import's stored file into a new preview with a change summary.

    Rows already in the ledger appear as exact duplicates; only genuinely new rows import.
    Rows that disappeared are reported for manual review, never deleted automatically.
    """
    old = db.get(ImportBatch, batch_id)
    if old is None:
        raise NotFound(f"Import batch {batch_id} not found")
    if old.status != "committed" or not old.storage_reference:
        raise Conflict("Only committed imports with a stored file can be reprocessed")
    path = storage.resolve(old.storage_reference)
    data = path.read_bytes()
    new = ImportBatch(filename=old.filename, file_hash=old.file_hash, file_type=old.file_type, file_size=old.file_size,
                      storage_reference=old.storage_reference, account_id=old.account_id, status="preview",
                      reprocess_of_batch_id=old.id)
    db.add(new)
    db.flush()
    try:
        _parse_into(db, new, data, path, ParseOptions(), parser_name or None, None, password, False)
    except extraction.ExtractionError as e:
        raise AppError(str(e), code=e.code)
    new_rows = list(db.scalars(select(ImportRow).where(ImportRow.batch_id == new.id)))
    old_txns = list(db.scalars(select(Transaction).where(Transaction.import_batch_id == old.id)))
    matched = {r.duplicate_of_transaction_id for r in new_rows if r.duplicate_status == "exact"}
    summary = {
        "previous_batch_id": old.id,
        "previous_parser": f"{old.parser_name} {old.parser_version}",
        "new_parser": f"{new.parser_name} {new.parser_version}",
        "previous_transactions": len(old_txns),
        "rows_now_extracted": len(new_rows),
        "unchanged": len(matched),
        "new_or_changed_rows": sum(1 for r in new_rows if r.duplicate_status != "exact"),
        "previous_rows_not_found": [
            {"transaction_id": t.id, "date": t.transaction_date.isoformat(), "amount_minor": t.amount_minor,
             "description": t.normalized_description}
            for t in old_txns if t.id not in matched][:200],
    }
    new.warnings = [f"Reprocessing batch #{old.id}. {summary['unchanged']} row(s) unchanged, "
                    f"{summary['new_or_changed_rows']} new or changed, {len(summary['previous_rows_not_found'])} "
                    "previously imported row(s) not found in the new extraction."] + list(new.warnings)
    new.statement_meta = (new.statement_meta or {}) | {"reprocess_summary": summary}
    audit.record(db, "import_batch", new.id, "reprocess_preview", {"of": old.id})
    db.flush()
    return new, summary


def save_profile(db: Session, batch_id: int, name: str, institution: str | None = None) -> ParserProfile:
    """Save the batch's column mapping as a reusable parser profile."""
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFound(f"Import batch {batch_id} not found")
    meta = batch.statement_meta or {}
    mapping = dict(meta.get("mapping_used") or {})
    headers = meta.get("header_columns") or []
    if not mapping or not headers:
        raise AppError("This import has no column mapping to save")
    sign_mode = mapping.pop("_sign_mode", None)
    sig = header_signature(headers)
    existing = db.scalar(select(ParserProfile).where(ParserProfile.name == name))
    profile = existing or ParserProfile(name=name)
    if existing is not None:
        profile.version += 1
    profile.institution = institution
    profile.statement_type = meta.get("statement_type") or "bank"
    profile.file_type = batch.file_type
    profile.column_mapping = mapping
    profile.options = {"sign_mode": sign_mode}
    profile.header_signature = sig
    profile.header_columns = headers
    profile.default_account_id = batch.account_id
    if existing is None:
        db.add(profile)
    db.flush()
    audit.record(db, "parser_profile", profile.id, "saved", {"name": name, "version": profile.version})
    return profile

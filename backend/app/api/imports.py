from datetime import date

from fastapi import Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import paginate, protected_router
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError, get_or_404
from app.models import ImportBatch, ImportRow, ParserProfile
from app.services.imports import service
from app.services.imports.extraction import ExtractionError, tesseract_available
from app.services.imports.parser_registry import all_parsers

router = protected_router(prefix="/imports", tags=["imports"])


def _batch_detail(db: Session, b: ImportBatch, page: int = 1, page_size: int = 500, row_filter: str | None = None) -> dict:
    d = ser.batch(b)
    q = select(ImportRow).where(ImportRow.batch_id == b.id)
    if row_filter == "errors":
        q = q.where(ImportRow.status == "error")
    elif row_filter == "warnings":
        q = q.where(ImportRow.status == "warning")
    elif row_filter == "duplicates":
        q = q.where(ImportRow.duplicate_status != "none")
    elif row_filter == "excluded":
        q = q.where(ImportRow.include.is_(False))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    offset, limit = paginate(page, page_size)
    d["rows"] = [ser.import_row(r) for r in db.scalars(q.order_by(ImportRow.row_index).offset(offset).limit(limit))]
    d["rows_total"] = total
    return d


@router.get("/parsers")
def list_parsers():
    return {"parsers": [p.describe() for p in all_parsers()], "ocr_available": tesseract_available(),
            "max_upload_mb": get_settings().max_upload_mb}


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), account_id: int | None = Form(None), parser_name: str | None = Form(None),
                 profile_id: int | None = Form(None), password: str | None = Form(None),
                 statement_type: str | None = Form(None), force_ocr: bool = Form(False), db: Session = Depends(get_db)):
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(f"File exceeds the {get_settings().max_upload_mb} MB limit", code="file_too_large", status_code=413)
    if statement_type not in (None, "", "bank", "credit_card"):
        raise AppError("statement_type must be bank or credit_card")
    try:
        batch = service.create_preview(db, service.UploadRequest(
            filename=file.filename or "statement", data=data, account_id=account_id, parser_name=parser_name or None,
            profile_id=profile_id, password=password or None, statement_type=statement_type or None, force_ocr=force_ocr))
    except ExtractionError as e:
        raise AppError(str(e), code=e.code)
    db.commit()
    return _batch_detail(db, batch)


@router.get("")
def list_batches(account_id: int | None = None, status: str | None = None, page: int = 1, page_size: int = 50,
                 db: Session = Depends(get_db)):
    q = select(ImportBatch)
    if account_id:
        q = q.where(ImportBatch.account_id == account_id)
    if status:
        q = q.where(ImportBatch.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    offset, limit = paginate(page, page_size)
    return {"total": total, "items": [ser.batch(b) for b in db.scalars(q.order_by(ImportBatch.id.desc()).offset(offset).limit(limit))]}


@router.get("/{batch_id}")
def get_batch(batch_id: int, page: int = 1, page_size: int = 500, rows: str | None = None, db: Session = Depends(get_db)):
    return _batch_detail(db, get_or_404(db, ImportBatch, batch_id, "Import batch"), page, page_size, rows)


class RowPatch(BaseModel):
    txn_date: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    amount: str | None = Field(default=None, max_length=40)
    balance: str | None = Field(default=None, max_length=40)
    include: bool | None = None


@router.patch("/{batch_id}/rows/{row_id}")
def update_row(batch_id: int, row_id: int, body: RowPatch, db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    row = service.update_row(db, batch_id, row_id, changes)
    db.commit()
    return {"row": ser.import_row(row), "batch": ser.batch(db.get(ImportBatch, batch_id))}


class BulkInclude(BaseModel):
    row_ids: list[int]
    include: bool | None


@router.post("/{batch_id}/rows/include")
def bulk_include(batch_id: int, body: BulkInclude, db: Session = Depends(get_db)):
    for rid in body.row_ids:
        service.update_row(db, batch_id, rid, {"include": body.include})
    db.commit()
    return ser.batch(db.get(ImportBatch, batch_id))


class AccountSet(BaseModel):
    account_id: int


@router.post("/{batch_id}/account")
def set_account(batch_id: int, body: AccountSet, db: Session = Depends(get_db)):
    b = service.set_account(db, batch_id, body.account_id)
    db.commit()
    return _batch_detail(db, b)


class MetaPatch(BaseModel):
    period_start: date | None = None
    period_end: date | None = None
    opening_balance_minor: int | None = None
    closing_balance_minor: int | None = None


@router.patch("/{batch_id}/statement")
def update_meta(batch_id: int, body: MetaPatch, db: Session = Depends(get_db)):
    changes = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in body.model_dump(exclude_unset=True).items()}
    b = service.update_statement_meta(db, batch_id, changes)
    db.commit()
    return _batch_detail(db, b)


class Reparse(BaseModel):
    column_mapping: dict[str, str | None] | None = None
    sign_mode: str | None = Field(default=None, pattern="^(signed|inverted)$")
    parser_name: str | None = None
    statement_type: str | None = Field(default=None, pattern="^(bank|credit_card)$")
    date_format: str | None = Field(default=None, max_length=40)
    header_row: int | None = None
    table_index: int | None = None
    password: str | None = None
    force_ocr: bool = False


@router.post("/{batch_id}/reparse")
def reparse(batch_id: int, body: Reparse, db: Session = Depends(get_db)):
    mapping = {k: v for k, v in (body.column_mapping or {}).items() if v} or None
    b = service.reparse(db, batch_id, column_mapping=mapping, sign_mode=body.sign_mode, parser_name=body.parser_name,
                        statement_type=body.statement_type, date_format=body.date_format, header_row=body.header_row,
                        table_index=body.table_index, password=body.password, force_ocr=body.force_ocr)
    db.commit()
    return _batch_detail(db, b)


@router.post("/{batch_id}/commit")
def commit(batch_id: int, db: Session = Depends(get_db)):
    b = service.commit(db, batch_id)
    db.commit()
    return ser.batch(b)


@router.post("/{batch_id}/discard")
def discard(batch_id: int, db: Session = Depends(get_db)):
    b = service.discard(db, batch_id)
    db.commit()
    return ser.batch(b)


@router.get("/{batch_id}/deletion-impact")
def deletion_impact(batch_id: int, db: Session = Depends(get_db)):
    return service.deletion_impact(db, batch_id)


@router.delete("/{batch_id}")
def delete_batch(batch_id: int, confirm_linked: bool = Query(False), delete_file: bool = Query(False),
                 db: Session = Depends(get_db)):
    impact = service.delete_batch(db, batch_id, confirm_linked=confirm_linked, delete_file=delete_file)
    db.commit()
    return impact


class ReprocessIn(BaseModel):
    parser_name: str | None = None
    password: str | None = None


@router.post("/{batch_id}/reprocess", status_code=201)
def reprocess(batch_id: int, body: ReprocessIn, db: Session = Depends(get_db)):
    new, summary = service.reprocess(db, batch_id, body.parser_name, body.password)
    db.commit()
    return _batch_detail(db, new) | {"change_summary": summary}


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    institution: str | None = Field(default=None, max_length=120)


@router.post("/{batch_id}/save-profile", status_code=201)
def save_profile(batch_id: int, body: ProfileIn, db: Session = Depends(get_db)):
    p = service.save_profile(db, batch_id, body.name, body.institution)
    db.commit()
    return _profile(p)


def _profile(p: ParserProfile) -> dict:
    return {"id": p.id, "name": p.name, "institution": p.institution, "statement_type": p.statement_type,
            "file_type": p.file_type, "column_mapping": p.column_mapping, "options": p.options,
            "header_columns": p.header_columns, "version": p.version, "enabled": p.enabled,
            "default_account_id": p.default_account_id, "updated_at": ser.iso(p.updated_at)}


profiles_router = protected_router(prefix="/parser-profiles", tags=["imports"])


@profiles_router.get("")
def list_profiles(db: Session = Depends(get_db)):
    return [_profile(p) for p in db.scalars(select(ParserProfile).order_by(ParserProfile.name))]


class ProfilePatch(BaseModel):
    enabled: bool | None = None
    institution: str | None = None


@profiles_router.patch("/{pid}")
def update_profile(pid: int, body: ProfilePatch, db: Session = Depends(get_db)):
    p = get_or_404(db, ParserProfile, pid, "Parser profile")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return _profile(p)


@profiles_router.delete("/{pid}")
def delete_profile(pid: int, db: Session = Depends(get_db)):
    p = get_or_404(db, ParserProfile, pid, "Parser profile")
    db.execute(ImportBatch.__table__.update().where(ImportBatch.parser_profile_id == pid).values(parser_profile_id=None))
    db.delete(p)
    db.commit()
    return {"deleted": pid}

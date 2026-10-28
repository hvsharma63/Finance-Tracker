from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import protected_router
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError
from app.models import AppSetting, AuditEvent, BackupRecord
from app.services.backup import service as backup
from app.services.imports.extraction import tesseract_available
from app.services.ledger.seed import DEFAULT_SETTINGS

router = protected_router(tags=["settings"])

EDITABLE = {
    "matching_window_days": (int, 0, 60),
    "matching_amount_tolerance_minor": (int, 0, 100000),
    "possible_duplicate_window_days": (int, 0, 10),
}


@router.get("/settings")
def get_settings_view(db: Session = Depends(get_db)):
    s = get_settings()
    stored = {x.key: x.value for x in db.scalars(select(AppSetting))}
    return {
        "values": {k: stored.get(k, v) for k, v in DEFAULT_SETTINGS.items()},
        "editable": list(EDITABLE),
        "system": {
            "auth_enabled": s.auth_enabled, "ocr_enabled": s.ocr_enabled, "ocr_available": tesseract_available(),
            "storage_dir": str(s.resolved_storage_dir()), "backup_dir": str(s.resolved_backup_dir()),
            "max_upload_mb": s.max_upload_mb, "timezone": s.timezone, "base_currency": s.base_currency,
            "document_retention_days": s.document_retention_days,
            "external_services": "none — no bank, market-data, AI or telemetry connections are made",
            "encryption_at_rest": "not provided by the application; use disk encryption (BitLocker) — see docs/SECURITY.md",
        },
    }


class SettingsPatch(BaseModel):
    values: dict


@router.patch("/settings")
def update_settings(body: SettingsPatch, db: Session = Depends(get_db)):
    for k, v in body.values.items():
        if k not in EDITABLE:
            raise AppError(f"Setting {k} is not editable")
        typ, lo, hi = EDITABLE[k]
        if not isinstance(v, typ) or not lo <= v <= hi:
            raise AppError(f"{k} must be {typ.__name__} between {lo} and {hi}")
        row = db.get(AppSetting, k)
        if row is None:
            db.add(AppSetting(key=k, value=v))
        else:
            row.value = v
    db.add(AuditEvent(entity_type="settings", action="updated", details=body.values))
    db.commit()
    return get_settings_view(db)


@router.get("/audit")
def audit_log(entity_type: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    q = select(AuditEvent)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    return [{"id": e.id, "at": e.occurred_at.isoformat(), "entity_type": e.entity_type, "entity_id": e.entity_id,
             "action": e.action, "details": e.details}
            for e in db.scalars(q.order_by(AuditEvent.id.desc()).limit(min(limit, 1000)))]


# ------------------------------------------------------------------ backups

@router.get("/backups")
def list_backups(db: Session = Depends(get_db)):
    history = [{"id": r.id, "at": r.created_at.isoformat(), "kind": r.kind, "filename": r.filename,
                "status": r.status, "size_bytes": r.size_bytes, "details": r.details, "error": r.error_message}
               for r in db.scalars(select(BackupRecord).order_by(BackupRecord.id.desc()).limit(50))]
    return {"files": backup.list_backups(), "history": history, "backup_dir": str(get_settings().resolved_backup_dir())}


class BackupIn(BaseModel):
    include_documents: bool = True


@router.post("/backups", status_code=201)
def create_backup(body: BackupIn | None = None, db: Session = Depends(get_db)):
    rec = backup.create_backup(db, include_documents=body.include_documents if body else True)
    return {"filename": rec.filename, "size_bytes": rec.size_bytes, "sha256": rec.sha256, "details": rec.details}


@router.get("/backups/{filename}/download")
def download_backup(filename: str):
    p = backup.resolve_backup(filename)
    return FileResponse(p, media_type="application/zip", filename=p.name)


@router.post("/backups/inspect")
async def inspect_backup(file: UploadFile = File(...)):
    info = backup.inspect_backup(await file.read())
    m = info["manifest"]
    return {"valid": info["valid"], "problems": info["problems"], "created_at": m.get("created_at"),
            "schema_revision": m.get("schema_revision"), "tables": m.get("tables"),
            "documents": len(m.get("documents", {}))}


@router.post("/backups/restore")
async def restore_backup(file: UploadFile | None = File(None), filename: str | None = Form(None),
                         confirm: bool = Form(False), db: Session = Depends(get_db)):
    if file is not None:
        data = await file.read()
    elif filename:
        data = backup.resolve_backup(filename).read_bytes()
    else:
        raise AppError("Upload a backup file or choose an existing backup")
    return backup.restore_backup(db, data, confirm=confirm)


health_router = APIRouter(tags=["system"])


@health_router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {"status": "ok", "database": "ok", "schema_revision": rev}

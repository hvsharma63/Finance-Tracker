"""Logical backup and restore.

A backup is a ZIP containing:
  manifest.json            — app/schema version, created time, table row counts, file checksums
  tables/<table>.json      — every row of every application table
  documents/<reference>    — the private statement files referenced by import batches
Restore validates the archive (checksums, schema revision) and replaces all data in ONE
database transaction; nothing is changed if any step fails.
Excluded: user sessions (users must sign in again). The users table is included.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Base
from app.core.errors import AppError
from app.models import BackupRecord
from app.services.imports import storage

FORMAT_VERSION = 1
EXCLUDED_TABLES = {"user_sessions", "backup_records"}


def _tables():
    """Tables in foreign-key dependency order (parents first)."""
    return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDED_TABLES]


def _encode(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, bytes):
        return base64.b64encode(v).decode()
    return v


def _decode(col, v):
    if v is None:
        return None
    t = col.type
    if isinstance(t, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(t, Date):
        return date.fromisoformat(v)
    if isinstance(t, Numeric) and not isinstance(t, (Integer, BigInteger)):
        return Decimal(v)
    return v


def _schema_revision(db: Session) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        db.rollback()
        return None


def backup_dir() -> Path:
    d = get_settings().resolved_backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_backup(db: Session, include_documents: bool = True) -> BackupRecord:
    created = datetime.now(timezone.utc)
    name = f"finance-backup-{created:%Y%m%d-%H%M%S}.zip"
    path = backup_dir() / name
    tmp = path.with_suffix(".partial")
    manifest = {"format_version": FORMAT_VERSION, "created_at": created.isoformat(),
                "schema_revision": _schema_revision(db), "tables": {}, "documents": {}, "excluded": sorted(EXCLUDED_TABLES)}
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for table in _tables():
                rows = [dict(r._mapping) for r in db.execute(table.select().order_by(*table.primary_key.columns))]
                payload = json.dumps([{k: _encode(v) for k, v in r.items()} for r in rows], ensure_ascii=False).encode()
                z.writestr(f"tables/{table.name}.json", payload)
                manifest["tables"][table.name] = {"rows": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}
            if include_documents:
                refs = {r[0] for r in db.execute(text(
                    "SELECT DISTINCT storage_reference FROM import_batches WHERE storage_reference IS NOT NULL"))}
                for ref in sorted(refs):
                    p = storage.resolve(ref)
                    if p.exists():
                        data = p.read_bytes()
                        z.writestr(f"documents/{ref}", data)
                        manifest["documents"][ref] = hashlib.sha256(data).hexdigest()
                    else:
                        manifest.setdefault("missing_documents", []).append(ref)
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
        # verify the archive we just wrote before declaring success
        with zipfile.ZipFile(tmp) as z:
            bad = z.testzip()
            if bad:
                raise AppError(f"Backup verification failed at {bad}")
        tmp.replace(path)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        rec = BackupRecord(kind="backup", filename=name, status="failed", error_message=str(e)[:500])
        db.add(rec)
        db.commit()
        raise
    data = path.read_bytes()
    rec = BackupRecord(kind="backup", filename=name, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                       status="success", details={"tables": {k: v["rows"] for k, v in manifest["tables"].items()},
                                                  "documents": len(manifest["documents"]),
                                                  "missing_documents": manifest.get("missing_documents", [])})
    db.add(rec)
    db.commit()
    return rec


def list_backups() -> list[dict]:
    out = []
    for p in sorted(backup_dir().glob("finance-backup-*.zip"), reverse=True):
        out.append({"filename": p.name, "size_bytes": p.stat().st_size,
                    "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()})
    return out


def resolve_backup(filename: str) -> Path:
    p = (backup_dir() / filename).resolve()
    if p.parent != backup_dir().resolve() or not p.name.startswith("finance-backup-") or p.suffix != ".zip":
        raise AppError("Invalid backup filename")
    if not p.exists():
        raise AppError("Backup not found", status_code=404)
    return p


def inspect_backup(data: bytes) -> dict:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise AppError("Not a valid backup archive", code="invalid_backup")
    with z:
        if "manifest.json" not in z.namelist():
            raise AppError("Backup has no manifest", code="invalid_backup")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format_version") != FORMAT_VERSION:
            raise AppError("Unsupported backup format version", code="invalid_backup")
        problems = []
        for name, info in manifest["tables"].items():
            payload = z.read(f"tables/{name}.json")
            if hashlib.sha256(payload).hexdigest() != info["sha256"]:
                problems.append(f"Checksum mismatch in table {name}")
        for ref, digest in manifest.get("documents", {}).items():
            if hashlib.sha256(z.read(f"documents/{ref}")).hexdigest() != digest:
                problems.append(f"Checksum mismatch in document {ref}")
    return {"manifest": manifest, "problems": problems, "valid": not problems}


def restore_backup(db: Session, data: bytes, *, confirm: bool) -> dict:
    if not confirm:
        raise AppError("Restoring replaces ALL current data. Pass confirm=true to proceed.", code="confirmation_required")
    info = inspect_backup(data)
    if not info["valid"]:
        raise AppError("Backup failed validation: " + "; ".join(info["problems"]), code="invalid_backup")
    manifest = info["manifest"]
    current_rev = _schema_revision(db)
    if manifest.get("schema_revision") and current_rev and manifest["schema_revision"] != current_rev:
        raise AppError(f"Backup schema revision {manifest['schema_revision']} differs from the database "
                       f"({current_rev}). Restore into a matching version, then run migrations.",
                       code="schema_mismatch")
    tables = _tables()
    counts = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        try:
            conn = db.connection()
            names = ", ".join(f'"{t.name}"' for t in tables)
            conn.execute(text(f"TRUNCATE {names}, user_sessions RESTART IDENTITY CASCADE"))
            for t in tables:
                member = f"tables/{t.name}.json"
                rows = json.loads(z.read(member)) if member in z.namelist() else []
                cols = {c.name: c for c in t.columns}
                decoded = [{k: _decode(cols[k], v) for k, v in r.items() if k in cols} for r in rows]
                if decoded:
                    conn.execute(t.insert(), decoded)
                counts[t.name] = len(decoded)
                pk = list(t.primary_key.columns)
                if len(pk) == 1 and isinstance(pk[0].type, (Integer, BigInteger)) and pk[0].autoincrement:
                    conn.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{t.name}', '{pk[0].name}'), "
                        f"COALESCE((SELECT MAX({pk[0].name}) FROM \"{t.name}\"), 0) + 1, false)"))
            # Write documents only after the data load succeeded; content-addressed so safe to overwrite.
            for ref in manifest.get("documents", {}):
                target = storage.resolve(ref)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(f"documents/{ref}"))
            db.add(BackupRecord(kind="restore", filename=manifest["created_at"], status="success",
                                size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                details={"tables": counts}))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"restored_tables": counts, "documents": len(manifest.get("documents", {})),
            "backup_created_at": manifest["created_at"]}

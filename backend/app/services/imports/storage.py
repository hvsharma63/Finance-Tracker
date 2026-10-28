"""Private statement file storage. Files are never served publicly."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_root() -> Path:
    root = get_settings().resolved_storage_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def store(data: bytes, file_type: str) -> tuple[str, Path]:
    """Store content-addressed. Returns (relative reference, absolute path)."""
    digest = sha256(data)
    ext = {"csv": "csv", "xlsx": "xlsx", "xls": "xls", "pdf": "pdf"}.get(file_type, "bin")
    rel = f"{datetime.now(timezone.utc):%Y}/{digest}.{ext}"
    path = storage_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - Windows ignores POSIX modes
            pass
    return rel, path


def resolve(reference: str) -> Path:
    root = storage_root()
    path = (root / reference).resolve()
    if root not in path.parents:
        raise ValueError("Invalid storage reference")
    return path


def delete(reference: str | None) -> bool:
    if not reference:
        return False
    path = resolve(reference)
    if path.exists():
        path.unlink()
        return True
    return False

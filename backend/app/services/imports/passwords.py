"""Saved PDF statement passwords.

Stored encrypted (Fernet / AES-128-CBC + HMAC) with a key derived from SECRET_KEY. Plaintext is
only held in memory while opening a PDF and is never returned by the API or written to logs.
Changing SECRET_KEY makes saved passwords unreadable (they must be re-entered).
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import PdfPassword


def _fernet() -> Fernet:
    secret = get_settings().secret_key
    if not secret or len(secret) < 16:
        raise AppError("SECRET_KEY must be set (16+ characters) to save PDF passwords", code="no_secret_key")
    key = base64.urlsafe_b64encode(hashlib.sha256(f"pdf-passwords:{secret}".encode()).digest())
    return Fernet(key)


def _decrypt(p: PdfPassword) -> str | None:
    try:
        return _fernet().decrypt(p.secret_enc.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def save(db: Session, label: str, password: str, account_id: int | None = None) -> PdfPassword:
    if not password:
        raise AppError("Password is empty")
    for existing in db.scalars(select(PdfPassword)):
        if _decrypt(existing) == password:
            if account_id and existing.account_id is None:
                existing.account_id = account_id
            return existing
    p = PdfPassword(label=label[:120] or "PDF password", secret_enc=_fernet().encrypt(password.encode()).decode(),
                    account_id=account_id)
    db.add(p)
    db.flush()
    return p


def candidates(db: Session, account_id: int | None) -> list[tuple[PdfPassword, str]]:
    """Saved passwords to try, the account's own first, then most used."""
    rows = list(db.scalars(select(PdfPassword)))
    rows.sort(key=lambda p: (p.account_id != account_id if account_id else True, -(p.use_count or 0), p.id))
    out = []
    for p in rows:
        pw = _decrypt(p)
        if pw:
            out.append((p, pw))
    return out


def mark_used(p: PdfPassword, account_id: int | None) -> None:
    p.use_count = (p.use_count or 0) + 1
    p.last_used_at = datetime.now(timezone.utc)
    if account_id and p.account_id is None:
        p.account_id = account_id

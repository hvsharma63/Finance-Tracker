"""Document retention: delete stored statement files older than DOCUMENT_RETENTION_DAYS.

Only the original files are removed. Ledger transactions, statements and import history remain;
those batches simply can no longer be reprocessed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ImportBatch
from app.services.imports import storage
from app.services.ledger import audit


def purge_old_documents(db: Session, days: int | None = None) -> int:
    days = get_settings().document_retention_days if days is None else days
    if not days or days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    batches = list(db.scalars(select(ImportBatch).where(ImportBatch.storage_reference.is_not(None),
                                                        ImportBatch.created_at < cutoff,
                                                        ImportBatch.status != "preview")))
    refs = {b.storage_reference for b in batches}
    # keep files still referenced by a newer batch or an open preview
    still_used = set(db.scalars(select(ImportBatch.storage_reference).where(
        ImportBatch.storage_reference.in_(refs),
        (ImportBatch.created_at >= cutoff) | (ImportBatch.status == "preview"))))
    removed = 0
    for b in batches:
        if b.storage_reference in still_used:
            continue
        if storage.delete(b.storage_reference):
            removed += 1
        b.storage_reference = None
    if batches:
        audit.record(db, "retention", None, "purged_documents", {"files": removed, "older_than_days": days})
    db.commit()
    return removed

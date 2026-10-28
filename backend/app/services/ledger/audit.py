from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(db: Session, entity_type: str, entity_id: int | None, action: str, details: dict | None = None) -> None:
    """Append an audit event. Never put full statement contents in details."""
    db.add(AuditEvent(entity_type=entity_type, entity_id=entity_id, action=action, details=details))

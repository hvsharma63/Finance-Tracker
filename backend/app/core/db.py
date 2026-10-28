from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker | None = None


def configure_engine(url: str | None = None):
    global _engine, _SessionLocal
    _engine = create_engine(url or get_settings().database_url, pool_pre_ping=True, future=True)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine():
    if _engine is None:
        configure_engine()
    return _engine


def session_factory() -> sessionmaker:
    if _SessionLocal is None:
        configure_engine()
    return _SessionLocal


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()

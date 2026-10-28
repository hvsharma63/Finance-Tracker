"""Test configuration. Uses a dedicated PostgreSQL database (TEST_DATABASE_URL), never the main one."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="ft-tests-"))
os.environ["AUTH_ENABLED"] = "false"
os.environ["STORAGE_DIR"] = str(_TMP / "statements")
os.environ["BACKUP_DIR"] = str(_TMP / "backups")
os.environ["CORS_ORIGINS"] = ""

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
_settings = get_settings()
TEST_URL = _settings.test_database_url
if not TEST_URL or not TEST_URL.rstrip("/").endswith("_test"):
    raise RuntimeError("Set TEST_DATABASE_URL to a database whose name ends with _test")
os.environ["DATABASE_URL"] = TEST_URL
get_settings.cache_clear()

from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core import db as dbmod  # noqa: E402
from app.core.db import Base  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    engine = dbmod.configure_engine(TEST_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["database_url"] = TEST_URL
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean(_schema):
    engine = dbmod.get_engine()
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    from app.core.security import login_limiter
    from app.services.ledger.seed import seed_defaults

    login_limiter.reset()
    with dbmod.session_factory()() as s:
        seed_defaults(s)
    for sub in ("statements", "backups"):
        shutil.rmtree(_TMP / sub, ignore_errors=True)
    yield


@pytest.fixture
def db():
    s = dbmod.session_factory()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), headers={"X-Requested-With": "finance-tracker"}) as c:
        yield c

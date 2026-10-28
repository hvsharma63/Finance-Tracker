from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://finance:finance@127.0.0.1:5433/finance"
    test_database_url: str = ""
    secret_key: str = ""
    storage_dir: Path = BACKEND_DIR.parent / "private" / "statements"
    backup_dir: Path = BACKEND_DIR.parent / "private" / "backups"
    auth_enabled: bool = True
    cors_origins: str = ""
    cookie_secure: bool = False
    session_hours: int = 12
    ocr_enabled: bool = True
    tesseract_cmd: str = ""
    max_upload_mb: int = 25
    document_retention_days: int = 0
    timezone: str = "Asia/Kolkata"
    base_currency: str = "INR"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def resolved_storage_dir(self) -> Path:
        p = self.storage_dir if self.storage_dir.is_absolute() else (BACKEND_DIR / self.storage_dir)
        return p.resolve()

    def resolved_backup_dir(self) -> Path:
        p = self.backup_dir if self.backup_dir.is_absolute() else (BACKEND_DIR / self.backup_dir)
        return p.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()

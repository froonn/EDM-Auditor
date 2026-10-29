"""Configuration for the FastAPI application."""

from dataclasses import dataclass
from os import environ
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApiSettings:
    database_url: str = "sqlite:///data/edm_auditor.sqlite3"
    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = 20 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "ApiSettings":
        return cls(
            database_url=environ.get("EDM_DATABASE_URL", cls.database_url),
            upload_dir=Path(environ.get("EDM_UPLOAD_DIR", str(cls.upload_dir))),
            max_upload_bytes=int(
                environ.get("EDM_MAX_UPLOAD_BYTES", str(cls.max_upload_bytes))
            ),
        )

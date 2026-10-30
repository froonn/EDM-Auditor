"""Configuration for the FastAPI application."""

from dataclasses import dataclass
from os import environ
from pathlib import Path

DEFAULT_DATABASE_URL = "sqlite:///data/edm_auditor.sqlite3"
DEFAULT_UPLOAD_DIR = Path("data/uploads")
DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_NEURAL_MODE = "disabled"
DEFAULT_MODEL_CONFIG = Path("config/models.toml")


@dataclass(frozen=True, slots=True)
class ApiSettings:
    database_url: str = DEFAULT_DATABASE_URL
    upload_dir: Path = DEFAULT_UPLOAD_DIR
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    neural_mode: str = DEFAULT_NEURAL_MODE
    model_config: Path = DEFAULT_MODEL_CONFIG

    @classmethod
    def from_env(cls) -> "ApiSettings":
        return cls(
            database_url=environ.get("EDM_DATABASE_URL", DEFAULT_DATABASE_URL),
            upload_dir=Path(environ.get("EDM_UPLOAD_DIR", str(DEFAULT_UPLOAD_DIR))),
            max_upload_bytes=int(
                environ.get("EDM_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
            ),
            neural_mode=environ.get("EDM_NEURAL_MODE", DEFAULT_NEURAL_MODE),
            model_config=Path(environ.get("EDM_MODEL_CONFIG", str(DEFAULT_MODEL_CONFIG))),
        )

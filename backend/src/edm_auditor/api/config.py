"""Configuration for the FastAPI application."""

from dataclasses import dataclass
from os import environ
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_DATABASE_URL = "sqlite:///data/edm_auditor.sqlite3"
DEFAULT_UPLOAD_DIR = Path("data/uploads")
DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_SOURCE_LANGUAGE = "auto"
DEFAULT_MODEL_CONFIG = Path("config/models.toml")
DEFAULT_RAG_INDEX_PATH = Path("data/rag-index.sqlite3")
DEFAULT_LOG_FILE = Path("data/debug.log")


@dataclass(frozen=True, slots=True)
class ApiSettings:
    database_url: str = DEFAULT_DATABASE_URL
    upload_dir: Path = DEFAULT_UPLOAD_DIR
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    source_language: str = DEFAULT_SOURCE_LANGUAGE
    model_config: Path = DEFAULT_MODEL_CONFIG
    rag_index_path: Path = DEFAULT_RAG_INDEX_PATH
    log_file: Path = DEFAULT_LOG_FILE

    @classmethod
    def from_env(cls) -> "ApiSettings":
        for candidate in [
            Path.cwd() / ".env",
            Path.cwd() / "backend" / ".env",
            Path(__file__).resolve().parents[3] / ".env",
            Path(__file__).resolve().parents[3] / "backend" / ".env",
        ]:
            if candidate.exists():
                load_dotenv(candidate)

        model_cfg_env = environ.get("EDM_MODEL_CONFIG")
        if model_cfg_env:
            model_cfg_path = Path(model_cfg_env)
        elif DEFAULT_MODEL_CONFIG.exists():
            model_cfg_path = DEFAULT_MODEL_CONFIG
        elif (Path("backend") / DEFAULT_MODEL_CONFIG).exists():
            model_cfg_path = Path("backend") / DEFAULT_MODEL_CONFIG
        else:
            model_cfg_path = Path(__file__).resolve().parents[3] / "backend" / DEFAULT_MODEL_CONFIG

        log_file_env = environ.get("EDM_LOG_FILE")
        if log_file_env:
            log_file_path = Path(log_file_env)
        elif Path("data").exists():
            log_file_path = Path("data/debug.log")
        elif Path("backend/data").exists():
            log_file_path = Path("backend/data/debug.log")
        else:
            log_file_path = Path(__file__).resolve().parents[3] / "backend" / "data" / "debug.log"

        return cls(
            database_url=environ.get("EDM_DATABASE_URL", DEFAULT_DATABASE_URL),
            upload_dir=Path(environ.get("EDM_UPLOAD_DIR", str(DEFAULT_UPLOAD_DIR))),
            max_upload_bytes=int(
                environ.get("EDM_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
            ),
            source_language=environ.get(
                "EDM_SOURCE_LANGUAGE", DEFAULT_SOURCE_LANGUAGE
            ),
            model_config=model_cfg_path,
            rag_index_path=Path(
                environ.get("RAG_INDEX_PATH", str(DEFAULT_RAG_INDEX_PATH))
            ),
            log_file=log_file_path,
        )

from collections.abc import Iterator
import logging
from pathlib import Path

import pytest

from edm_auditor.api import app as api_app
from edm_auditor.api.config import DEFAULT_LOG_FILE


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "EDM_DATABASE_URL",
        "EDM_UPLOAD_DIR",
        "EDM_MAX_UPLOAD_BYTES",
        "EDM_MODEL_CONFIG",
        "EDM_MODEL_PRESET",
        "EDM_SOURCE_LANGUAGE",
        "EDM_LOG_FILE",
        "EDM_AUTH_COOKIE_NAME",
        "EDM_AUTH_COOKIE_SECURE",
        "EDM_AUTH_SESSION_TTL_HOURS",
        "EDM_TRUSTED_ORIGINS",
        "EDM_TRACE_LOG_BODIES",
        "EDM_EXPOSE_DOCS",
        "EDM_INITIAL_ADMIN_USERNAME",
        "EDM_INITIAL_ADMIN_EMAIL",
        "EDM_INITIAL_ADMIN_PASSWORD",
        "RAG_INDEX_PATH",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolate_test_log_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Keep default test logging inside tmp_path so pytest never writes to repo data/debug.log."""
    real_setup = api_app._setup_file_logging
    tmp_prefix = str(tmp_path.resolve())

    def _redirected_setup(log_file: Path) -> None:
        target = tmp_path / "debug.log" if log_file == DEFAULT_LOG_FILE else log_file
        real_setup(target)

    monkeypatch.setattr(api_app, "_setup_file_logging", _redirected_setup)
    yield

    for logger_name in ("edm_auditor", "edm_auditor.trace"):
        lg = logging.getLogger(logger_name)
        for handler in list(lg.handlers):
            if isinstance(handler, logging.FileHandler) and str(
                getattr(handler, "baseFilename", "")
            ).startswith(tmp_prefix):
                lg.removeHandler(handler)
                handler.close()

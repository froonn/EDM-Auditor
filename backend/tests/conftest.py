import pytest


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "EDM_DATABASE_URL",
        "EDM_UPLOAD_DIR",
        "EDM_MAX_UPLOAD_BYTES",
        "EDM_MODEL_CONFIG",
        "EDM_MODEL_PRESET",
        "EDM_SOURCE_LANGUAGE",
        "RAG_INDEX_PATH",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

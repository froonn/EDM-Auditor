"""Run the corpus through the real API with real models in a temporary database."""

from __future__ import annotations

import dataclasses
import logging
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

from fastapi.testclient import TestClient

from edm_auditor.api import app as api_module
from edm_auditor.api.config import ApiSettings
from edm_auditor.model_config import ModelSettings

from .corpus import Corpus

logger = logging.getLogger(__name__)

# Factories in the API module and the kind of request each provider sends.
_FACTORIES = {
    "create_rule_extraction_provider": "rules",
    "create_document_classification_provider": "classification",
    "create_entity_extraction_provider": "entities",
    "create_llm_provider": "llm",
    "create_embedding_provider": "embedding",
}


# The model is overloaded or out of its request limit.
_OVERLOAD_STATUSES = {429, 503}


class RequestMeter:
    """Count model requests and keep a minimum pause between them for the free request limit."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0
        self.counts: Counter[str] = Counter()

    def before_request(self, kind: str) -> None:
        with self._lock:
            pause = self._last + self._min_interval - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            self._last = time.monotonic()
            self.counts[kind] += 1


class _MeteredProvider:
    """Forward every public call to the provider after the meter allows it."""

    def __init__(self, inner: Any, kind: str, meter: RequestMeter) -> None:
        self._inner = inner
        self._kind = kind
        self._meter = meter

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._inner, name)
        if name.startswith("_") or not callable(value):
            return value

        def call(*args: Any, **kwargs: Any) -> Any:
            self._meter.before_request(self._kind)
            return value(*args, **kwargs)

        return call


@contextmanager
def _metered_factories(meter: RequestMeter) -> Iterator[None]:
    def wrap(factory: Callable[..., Any], kind: str) -> Callable[..., Any]:
        return lambda *args, **kwargs: _MeteredProvider(factory(*args, **kwargs), kind, meter)

    with ExitStack() as stack:
        for name, kind in _FACTORIES.items():
            stack.enter_context(
                mock.patch.object(api_module, name, wrap(getattr(api_module, name), kind))
            )
        yield


def _error(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail = body.get("error") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return f"HTTP {response.status_code} {detail.get('code')}: {detail.get('message')}"
    return f"HTTP {response.status_code}: {body}"


def run_corpus(
    corpus: Corpus,
    *,
    label: str,
    min_interval: float,
    log_file: Path | None = None,
    base_settings: ApiSettings | None = None,
    retry_pause: float = 30.0,
) -> dict[str, Any]:
    """Upload every act and document, audit each document with the rules of its acts."""
    started = time.monotonic()
    meter = RequestMeter(min_interval)
    retries = 0
    base = base_settings or ApiSettings.from_env()
    models = ModelSettings.from_toml(base.model_config)
    run: dict[str, Any] = {
        "label": label,
        "models": {
            "extractor": models.extractor.model if models.extractor else None,
            "llm": models.llm.model,
            "embedding": models.embedding.model,
        },
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "acts": {},
        "documents": {},
    }
    with tempfile.TemporaryDirectory(prefix="edm-eval-") as temp:
        workdir = Path(temp)
        settings = dataclasses.replace(
            base,
            database_url=f"sqlite:///{workdir / 'eval.sqlite3'}",
            upload_dir=workdir / "uploads",
            rag_index_path=workdir / "rag-index.sqlite3",
            log_file=log_file or workdir / "debug.log",
            initial_admin_username="eval-admin",
            initial_admin_email="eval-admin@local.invalid",
            initial_admin_password="eval-runner-temp-password",
        )
        with _metered_factories(meter), TestClient(
            api_module.create_app(settings=settings), raise_server_exceptions=False
        ) as client:
            login_resp = client.post(
                "/api/auth/login",
                json={
                    "username": "eval-admin",
                    "password": "eval-runner-temp-password",
                },
            )
            if login_resp.status_code != 200:
                raise RuntimeError(f"Evaluation runner failed to authenticate: {login_resp.text}")
            act_ids = {}
            for act in corpus.acts:
                logger.info("Legal act %s", act.id)
                act_started = time.monotonic()
                response = client.post(
                    "/api/legal-acts/upload",
                    data={"code": act.code, "title": act.title},
                    files={"file": (act.path.name, act.path.read_bytes(), "text/plain")},
                )
                recorded: dict[str, Any] = {"status": "ok", "error": None, "rules": []}
                if response.status_code != 201:
                    recorded.update(status="error", error=_error(response))
                    listed = client.get("/api/legal-acts").json()
                    found = [item for item in listed if item["code"] == act.code]
                    legal_act_id = found[0]["id"] if found else None
                else:
                    legal_act_id = response.json()["id"]
                    status = response.json().get("processing_status")
                    if status not in (None, "processed", "completed"):
                        recorded["status"] = status
                if legal_act_id is not None:
                    act_ids[act.id] = legal_act_id
                    detail = client.get(f"/api/legal-acts/{legal_act_id}").json()
                    recorded["text"] = detail.get("article_text")
                    recorded["rules"] = client.get(
                        "/api/rules", params={"legal_act_id": legal_act_id}
                    ).json()
                    recorded["diagnostics"] = client.get(
                        f"/api/legal-acts/{legal_act_id}/diagnostics"
                    ).json().get("diagnostics", [])
                recorded["seconds"] = round(time.monotonic() - act_started, 1)
                run["acts"][act.id] = recorded

            for document in corpus.documents:
                logger.info("Document %s", document.id)
                document_started = time.monotonic()
                recorded = {"status": "ok", "error": None, "findings": []}
                run["documents"][document.id] = recorded
                response = client.post(
                    "/api/documents/upload",
                    files={"file": (document.path.name, document.path.read_bytes(), "text/plain")},
                )
                if response.status_code != 201:
                    recorded.update(status="error", error=_error(response))
                    continue
                document_id = response.json()["id"]
                recorded["classified_types"] = response.json().get("confirmed_document_types")
                recorded["text"] = client.get(f"/api/documents/{document_id}").json()["text"]
                if document.document_types:
                    client.patch(
                        f"/api/documents/{document_id}/classification",
                        json={"confirmed_document_types": list(document.document_types)},
                    )
                rule_ids = [
                    rule["id"]
                    for act_id in document.acts
                    for rule in run["acts"].get(act_id, {}).get("rules", [])
                    if rule.get("is_active", True)
                ]
                if not rule_ids:
                    recorded.update(status="error", error="no rules for the document's acts")
                    continue
                selection = {"selection_mode": "manual", "included_rule_ids": rule_ids}
                response = client.post(f"/api/documents/{document_id}/audit", json=selection)
                if response.status_code in _OVERLOAD_STATUSES:
                    # An overloaded model says nothing about audit quality, so try once more.
                    recorded["retried_after"] = _error(response)
                    retries += 1
                    time.sleep(retry_pause)
                    response = client.post(
                        f"/api/documents/{document_id}/audit", json=selection
                    )
                if response.status_code != 200:
                    recorded.update(status="error", error=_error(response))
                    continue
                report = client.get(f"/api/documents/{document_id}/report").json()
                recorded["findings"] = report["findings"]
                recorded["rejected_candidates"] = report["summary"].get("rejected_candidates", [])
                recorded["seconds"] = round(time.monotonic() - document_started, 1)

    run["requests"] = {
        "total": sum(meter.counts.values()),
        "by_kind": dict(meter.counts),
        "audit_retries": retries,
    }
    run["duration_seconds"] = round(time.monotonic() - started, 1)
    return run

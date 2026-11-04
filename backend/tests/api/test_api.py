from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.database import Base, create_session_factory
from edm_auditor.database.models import (
    AuditFinding,
    AuditReport,
    AuditRule,
    Document,
    LegalAct,
    RuleExtractionResult,
)
from edm_auditor.rag import SQLiteVectorStore
from edm_auditor.rag.models import TextChunk
from fakes import (
    DeterministicEmbeddingProvider,
    FailingEntityProvider,
    FailingLLMProvider,
    FakeEntityProvider,
    FakeLLMProvider,
    FakeRuleExtractor,
)


@pytest.fixture(autouse=True)
def fake_model_providers(monkeypatch) -> None:
    monkeypatch.setenv("EDM_MODEL_PRESET", "lm-studio")
    for factory, provider in (
        ("create_llm_provider", FakeLLMProvider),
        ("create_entity_extraction_provider", FakeEntityProvider),
        ("create_rule_extraction_provider", FakeRuleExtractor),
        ("create_embedding_provider", DeterministicEmbeddingProvider),
    ):
        monkeypatch.setattr(
            f"edm_auditor.api.app.{factory}",
            lambda config, provider=provider: provider(),
        )


def test_api_settings_use_defaults_without_environment(monkeypatch) -> None:
    monkeypatch.delenv("EDM_DATABASE_URL", raising=False)
    monkeypatch.delenv("EDM_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("EDM_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("EDM_SOURCE_LANGUAGE", raising=False)

    settings = ApiSettings.from_env()

    assert settings.database_url == "sqlite:///data/edm_auditor.sqlite3"
    assert settings.upload_dir == Path("data/uploads")
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert settings.source_language == "auto"


def test_api_settings_load_dotenv_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "RAG_INDEX_PATH=custom/index.sqlite3\n",
        encoding="utf-8",
    )

    settings = ApiSettings.from_env()

    assert settings.rag_index_path == Path("custom/index.sqlite3")


def test_app_rejects_preset_without_online_extractor(
    tmp_path: Path, monkeypatch
) -> None:
    from dataclasses import replace
    from edm_auditor.model_config import ModelSettings

    configured = ModelSettings.from_toml(preset_name="lm-studio")
    monkeypatch.setattr(
        "edm_auditor.api.app.ModelSettings.from_toml",
        lambda *args, **kwargs: replace(configured, extractor=None),
    )
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024,
        rag_index_path=tmp_path / "rag-index.sqlite3",
    )

    with pytest.raises(ValueError, match="online extractor"):
        create_app(settings=settings)


def test_app_does_not_start_without_model_preset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("EDM_MODEL_PRESET")
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'api.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024,
        rag_index_path=tmp_path / "rag-index.sqlite3",
    )

    with pytest.raises(ValueError, match="EDM_MODEL_PRESET"):
        create_app(settings=settings)


def test_app_reports_database_with_outdated_schema(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE audit_rules (id INTEGER PRIMARY KEY)")
    settings = ApiSettings(
        database_url=f"sqlite:///{path}",
        upload_dir=tmp_path / "uploads",
        rag_index_path=tmp_path / "rag-index.sqlite3",
    )

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        create_app(settings=settings)


def make_client(tmp_path: Path) -> TestClient:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    settings = ApiSettings(
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024,
        rag_index_path=tmp_path / "rag-index.sqlite3",
    )
    return TestClient(create_app(settings=settings, session_factory=session_factory))


def test_app_creates_schema_for_missing_database(tmp_path: Path) -> None:
    database_path = tmp_path / "new" / "edm_auditor.sqlite3"
    settings = ApiSettings(
        database_url=f"sqlite:///{database_path}",
        upload_dir=tmp_path / "uploads",
        rag_index_path=tmp_path / "rag-index.sqlite3",
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/api/documents")

    assert response.status_code == 200
    assert database_path.exists()


def test_health_and_upload_document(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    assert client.get("/health").json() == {"status": "ok"}
    response = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"Employee receives 14 days leave.", "text/plain")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "contract"
    assert body["file_type"] == "txt"
    assert body["status"] == "uploaded"
    assert client.get(f"/api/documents/{body['id']}").status_code == 200


def test_upload_maps_parser_errors_and_size_limit(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    unsupported = client.post(
        "/api/documents/upload",
        files={"file": ("contract.doc", b"not supported", "application/msword")},
    )
    oversized = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"x" * 1025, "text/plain")},
    )

    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "unsupported_document_format"
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "document_too_large"


def test_create_rule_audit_and_get_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"Employee receives 14 days leave.", "text/plain")},
    )
    document_id = upload.json()["id"]

    rule = client.post(
        "/api/rules",
        json={
            "rule_code": "leave-short",
            "name": "Short leave",
            "severity": "high",
            "check_type": "keyword",
            "parameters": {"keywords": ["14 days"]},
        },
    )
    assert rule.status_code == 201
    assert client.get("/api/rules?check_type=keyword").json()[0]["rule_code"] == "leave-short"

    audit = client.post(f"/api/documents/{document_id}/audit")
    assert audit.status_code == 200
    report = client.get(f"/api/documents/{document_id}/report")

    assert report.status_code == 200
    assert report.json()["total_findings"] == 1
    assert report.json()["findings"][0]["quote"] == "14 days"


@pytest.mark.parametrize(
    "factory, provider, message",
    [
        ("create_llm_provider", FailingLLMProvider, "LLM analysis failed"),
        (
            "create_entity_extraction_provider",
            FailingEntityProvider,
            "entity extraction model failed",
        ),
    ],
)
def test_audit_fails_without_report_when_model_is_unavailable(
    tmp_path: Path, monkeypatch, factory, provider, message
) -> None:
    monkeypatch.setattr(f"edm_auditor.api.app.{factory}", lambda config: provider())
    client = make_client(tmp_path)
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"Employee receives 14 days leave.", "text/plain")},
    )
    document_id = upload.json()["id"]

    audit = client.post(f"/api/documents/{document_id}/audit")

    assert audit.status_code == 503
    assert audit.json()["error"]["code"] == "model_provider_error"
    assert message in audit.json()["error"]["message"]
    assert client.get(f"/api/documents/{document_id}").json()["status"] == "error"
    assert client.get(f"/api/documents/{document_id}/report").status_code == 404


def test_list_legal_acts_does_not_expose_article_text(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    with client.app.state.session_factory.begin() as session:
        session.add(
            LegalAct(
                code="TK-RB",
                title="Labour Code",
                number="155",
                article_text="Private normative text",
            )
        )

    response = client.get("/api/legal-acts?search=labour")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "code": "TK-RB",
            "title": "Labour Code",
            "number": "155",
            "source_url": None,
            "processing_status": "uploaded",
            "processing_version": None,
            "chunks_total": 0,
            "chunks_processed": 0,
            "rules_accepted": 0,
            "rules_rejected": 0,
        }
    ]


def test_legal_act_can_be_created_read_updated_and_deleted(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/api/legal-acts",
        json={
            "code": "TK-RB",
            "title": "Labour Code",
            "article_text": "Article 1",
            "number": "155",
        },
    )
    assert created.status_code == 201
    legal_act_id = created.json()["id"]
    assert "article_text" not in created.json()

    detail = client.get(f"/api/legal-acts/{legal_act_id}")
    assert detail.status_code == 200
    assert detail.json()["article_text"] == "Article 1"

    updated = client.patch(
        f"/api/legal-acts/{legal_act_id}",
        json={"article_text": "Updated article", "source_url": "https://example.test"},
    )
    assert updated.status_code == 200
    assert client.get(f"/api/legal-acts/{legal_act_id}").json()["article_text"] == (
        "Updated article"
    )

    assert client.delete(f"/api/legal-acts/{legal_act_id}").status_code == 204
    assert client.get(f"/api/legal-acts/{legal_act_id}").status_code == 404


def test_delete_legal_act_removes_rules_and_preserves_findings(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/api/legal-acts",
        json={"code": "TK-RB", "title": "Labour Code", "article_text": "Article 1"},
    )
    legal_act_id = created.json()["id"]
    rule = client.post(
        "/api/rules",
        json={
            "rule_code": "linked-rule",
            "name": "Linked rule",
            "description": "Linked to the legal act",
            "severity": "low",
            "check_type": "keyword",
            "parameters": {"keywords": ["leave"]},
            "legal_act_id": legal_act_id,
        },
    )
    rule_id = rule.json()["id"]

    with client.app.state.session_factory.begin() as session:
        report = AuditReport(
            document=Document(
                title="Contract",
                file_type="txt",
                file_path="contract.txt",
                raw_text="Annual leave",
                status="audited",
            ),
            total_findings=1,
            summary="{}",
        )
        finding = AuditFinding(
            report=report,
            rule_id=rule_id,
            legal_act_id=legal_act_id,
            severity="low",
            description="Existing finding",
        )
        session.add(finding)
        session.flush()
        finding_id = finding.id
        report_id = report.id

    assert client.delete(f"/api/legal-acts/{legal_act_id}").status_code == 204

    assert client.get("/api/rules").json() == []
    with client.app.state.session_factory() as session:
        assert session.get(AuditRule, rule_id) is None
        finding = session.get(AuditFinding, finding_id)
        assert finding is not None
        assert finding.rule_id is None
        assert finding.legal_act_id is None
        assert session.get(AuditReport, report_id) is not None


def test_web_ui_and_report_document_endpoints(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/").status_code == 200
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"Employee receives 14 days leave.", "text/plain")},
    )
    document_id = upload.json()["id"]
    assert client.get("/api/documents").json()[0]["id"] == document_id
    client.post(
        "/api/rules",
        json={
            "rule_code": "web-ui-leave-check",
            "name": "Leave check",
            "severity": "high",
            "check_type": "keyword",
            "parameters": {"keywords": ["14 days"]},
        },
    )
    audit = client.post(f"/api/documents/{document_id}/audit")
    reports = client.get("/api/reports")
    assert reports.status_code == 200
    assert reports.json()[0]["id"] == audit.json()["report_id"]


def test_upload_legal_act_from_text_file(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/api/legal-acts/upload",
        data={"code": "ACT-UPLOAD", "title": "Uploaded act"},
        files={"file": ("act.txt", b"Normative text", "text/plain")},
    )
    assert response.status_code == 201
    legal_act_id = response.json()["id"]
    detail = client.get(f"/api/legal-acts/{legal_act_id}")
    assert detail.json()["article_text"] == "Normative text"
    assert client.get("/api/rules").json() == []
    store = SQLiteVectorStore(
        tmp_path / "rag-index.sqlite3",
        embedding_model="deterministic-v1",
        dimension=32,
        chunking_version="paragraph-v1",
    )
    assert store.count() > 0


def test_upload_legal_act_generates_neural_rule(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeRuleExtractor:
        def extract_rules(
            self, text: str, *, source_language: str, source_location: str
        ):
            assert "24" in text
            return (
                {
                    "rule_code": "leave-minimum",
                    "name": "Минимальная продолжительность отпуска",
                    "description": "Отпуск предоставляется продолжительностью не менее 24 календарных дня.",
                    "severity": "high",
                    "check_type": "duration",
                    "parameters": {"min_days": 24},
                    "source_quote": (
                        "Отпуск предоставляется продолжительностью не менее "
                        "24 календарных дня."
                    ),
                    "source_location": source_location,
                },
            )

    monkeypatch.setattr(
        "edm_auditor.api.app.create_rule_extraction_provider",
        lambda config: FakeRuleExtractor(),
    )
    settings = ApiSettings(
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024,
        rag_index_path=tmp_path / "rag-index.sqlite3",
    )
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    client = TestClient(
        create_app(settings=settings, session_factory=create_session_factory(engine))
    )
    response = client.post(
        "/api/legal-acts/upload",
        data={"code": "ACT-LEAVE", "title": "Leave act"},
        files={
            "file": (
                "act.txt",
                "Отпуск предоставляется продолжительностью не менее 24 календарных дня.".encode(),
                "text/plain",
            )
        },
    )

    assert response.status_code == 201
    rules = client.get("/api/rules").json()
    assert len(rules) == 1
    assert rules[0]["rule_code"].startswith("ACT-LEAVE-0-001-")
    assert rules[0]["is_generated"] is True
    assert rules[0]["source_quote"].startswith("Отпуск предоставляется")
    assert rules[0]["legal_act_id"] == response.json()["id"]
    assert rules[0]["parameters"]["min_days"] == 24
    assert response.json()["processing_status"] == "completed"
    assert response.json()["chunks_total"] == 1
    assert response.json()["rules_accepted"] == 1
    diagnostics = client.get(
        f"/api/legal-acts/{response.json()['id']}/diagnostics"
    )
    assert diagnostics.status_code == 200
    assert diagnostics.json()["diagnostics"][0]["status"] == "accepted"


def test_reprocess_replaces_generated_rules_atomically(tmp_path: Path, monkeypatch) -> None:
    calls = {"count": 0}

    class FakeRuleExtractor:
        def extract_rules(self, text: str, *, source_language: str, source_location: str):
            calls["count"] += 1
            return (
                {
                    "rule_code": "model-code",
                    "name": "Минимальный срок",
                    "description": "Срок не менее 24 дней.",
                    "severity": "high",
                    "check_type": "duration",
                    "parameters": {"min_days": 24},
                    "source_quote": "Срок не менее 24 дней.",
                    "source_location": source_location,
                },
            )

    monkeypatch.setattr(
        "edm_auditor.api.app.create_rule_extraction_provider",
        lambda config: FakeRuleExtractor(),
    )
    client = make_client(tmp_path)
    response = client.post(
        "/api/legal-acts/upload",
        data={"code": "ACT-REPROCESS", "title": "Act"},
        files={"file": ("act.txt", "Срок не менее 24 дней.".encode(), "text/plain")},
    )
    assert response.status_code == 201
    legal_act_id = response.json()["id"]
    first_code = client.get("/api/rules").json()[0]["rule_code"]

    response = client.post(f"/api/legal-acts/{legal_act_id}/reprocess")

    assert response.status_code == 200
    assert calls["count"] == 2
    rules = client.get("/api/rules").json()
    assert len(rules) == 1
    assert rules[0]["rule_code"] == first_code
    with client.app.state.session_factory() as session:
        result = session.scalar(
            select(RuleExtractionResult).where(
                RuleExtractionResult.legal_act_id == legal_act_id
            )
        )
        assert result.status == "accepted"


def test_failed_chunk_is_persisted_without_publishing_partial_rules(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    class FakeRuleExtractor:
        def extract_rules(self, text: str, *, source_language: str, source_location: str):
            calls.append(source_location)
            if source_location.endswith("chunk-1"):
                raise RuntimeError("provider unavailable")
            return ()

    def fake_chunks(text, *, legal_act_id, **kwargs):
        return [
            TextChunk(
                f"legal-act-{legal_act_id}:chunk-{index}",
                legal_act_id,
                None,
                part,
                index,
                start,
                start + len(part),
                "paragraph-v1",
                "hash",
            )
            for index, (part, start) in enumerate(
                (("First article", 0), ("Second article", 14))
            )
        ]

    monkeypatch.setattr("edm_auditor.api.app.chunk_text", fake_chunks)
    monkeypatch.setattr(
        "edm_auditor.api.app.create_rule_extraction_provider",
        lambda config: FakeRuleExtractor(),
    )
    client = make_client(tmp_path)

    response = client.post(
        "/api/legal-acts/upload",
        data={"code": "ACT-FAILED-CHUNK", "title": "Act"},
        files={"file": ("act.txt", b"First article Second article", "text/plain")},
    )

    assert response.status_code == 503
    legal_act_id = client.get("/api/legal-acts").json()[0]["id"]
    assert calls == [
        f"legal-act-{legal_act_id}:chunk-0",
        f"legal-act-{legal_act_id}:chunk-1",
    ]
    diagnostics = client.get(f"/api/legal-acts/{legal_act_id}/diagnostics").json()
    assert diagnostics["processing_status"] == "failed"
    assert [item["status"] for item in diagnostics["diagnostics"]] == [
        "accepted",
        "failed",
    ]


def test_delete_rule_preserves_existing_findings_and_rebuilds_index(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/api/rules",
        json={
            "rule_code": "temporary-rule",
            "name": "Temporary rule",
            "description": "Temporary check",
            "severity": "low",
            "check_type": "keyword",
            "parameters": {"keywords": ["temporary"]},
        },
    )
    assert response.status_code == 201
    rule_id = response.json()["id"]

    deleted = client.delete(f"/api/rules/{rule_id}")

    assert deleted.status_code == 204
    assert client.get(f"/api/rules?is_active=true").json() == []
    assert client.delete(f"/api/rules/{rule_id}").status_code == 404

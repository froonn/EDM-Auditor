from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.database import Base, create_session_factory
from edm_auditor.model_providers import ModelRateLimited, ModelRequestTimeout
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
    FakeClassificationProvider,
    FakeEntityProvider,
    FakeLLMProvider,
    FakeRuleExtractor,
)


@pytest.fixture(autouse=True)
def fake_model_providers(monkeypatch) -> None:
    monkeypatch.setenv("EDM_MODEL_PRESET", "lm-studio")
    for factory, provider in (
        ("create_llm_provider", FakeLLMProvider),
        ("create_document_classification_provider", FakeClassificationProvider),
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

    audit = client.post(
        f"/api/documents/{document_id}/audit",
        json={"selection_mode": "manual", "included_rule_ids": [rule.json()["id"]]},
    )
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
    rule = client.post(
        "/api/rules",
        json={
            "rule_code": "leave-check",
            "name": "Leave check",
            "severity": "high",
            "check_type": "keyword",
            "parameters": {"keywords": ["14 days"]},
        },
    )

    audit = client.post(
        f"/api/documents/{document_id}/audit",
        json={"selection_mode": "manual", "included_rule_ids": [rule.json()["id"]]},
    )

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
            "document_types": [],
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
    assert 'id="audit-config"' in client.get("/").text
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"Employee receives 14 days leave.", "text/plain")},
    )
    document_id = upload.json()["id"]
    assert client.get("/api/documents").json()[0]["id"] == document_id
    rule = client.post(
        "/api/rules",
        json={
            "rule_code": "web-ui-leave-check",
            "name": "Leave check",
            "severity": "high",
            "check_type": "keyword",
            "parameters": {"keywords": ["14 days"]},
        },
    )
    audit = client.post(
        f"/api/documents/{document_id}/audit",
        json={"selection_mode": "manual", "included_rule_ids": [rule.json()["id"]]},
    )
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
            self, text: str, *, source_language: str, source_location: str, **_
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
        def extract_rules(self, text: str, *, source_language: str, source_location: str, **_):
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
        def extract_rules(self, text: str, *, source_language: str, source_location: str, **_):
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


def _rule_payload(code: str, keyword: str, **extra) -> dict:
    return {
        "rule_code": code,
        "name": code,
        "severity": "high",
        "check_type": "keyword",
        "parameters": {"keywords": [keyword]},
        **extra,
    }


def _upload(client: TestClient, text: str, name: str = "document.txt") -> dict:
    response = client.post(
        "/api/documents/upload", files={"file": (name, text.encode(), "text/plain")}
    )
    assert response.status_code == 201
    return response.json()


TRIP_ORDER = "Приказ о направлении в командировку.\n\nОтчет о командировке за 7 дней."


def test_document_type_catalog_can_be_extended_and_deactivated(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    codes = [item["code"] for item in client.get("/api/document-types").json()]
    assert "business_trip_order" in codes and "unknown" not in codes

    created = client.post(
        "/api/document-types",
        json={
            "code": "travel_expense_report",
            "name": "Авансовый отчет",
            "description": "Отчёт работника о расходах в командировке.",
        },
    )
    assert created.status_code == 201
    assert client.post(
        "/api/document-types", json={"code": "travel_expense_report", "name": "Копия", "description": "Копия"}
    ).status_code == 409

    report = _upload(client, "Авансовый отчет\nСуточные и командировочные расходы.")
    assert report["confirmed_document_types"] == ["travel_expense_report"]

    unused = client.post(
        "/api/document-types", json={"code": "unused_type", "name": "Unused", "description": "Unused"}
    )
    assert unused.status_code == 201
    assert client.delete("/api/document-types/unused_type").status_code == 204
    codes = [item["code"] for item in client.get("/api/document-types").json()]
    assert "unused_type" not in codes
    inactive = client.get("/api/document-types?include_inactive=true").json()
    assert [item["is_active"] for item in inactive if item["code"] == "unused_type"] == [False]
    assert client.delete("/api/document-types/missing").status_code == 404


def test_unknown_is_not_a_valid_catalog_type(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/api/document-types", json={"code": "unknown", "name": "No", "description": "No"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "reserved_document_type"


@pytest.mark.parametrize("dependency", ["rule", "document", "legal_act"])
def test_document_type_with_dependencies_cannot_be_deleted(
    tmp_path: Path, dependency
) -> None:
    client = make_client(tmp_path)
    code = "vacation_order"
    if dependency == "rule":
        client.post("/api/rules", json=_rule_payload("r", "x", document_types=[code]))
    elif dependency == "document":
        document = _upload(client, "Текст без признаков.")
        client.patch(
            f"/api/documents/{document['id']}/classification",
            json={"confirmed_document_types": [code]},
        )
    else:
        client.post(
            "/api/legal-acts",
            json={"code": "A", "title": "A", "article_text": "A", "document_types": [code]},
        )

    response = client.delete(f"/api/document-types/{code}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "document_type_in_use"


def test_upload_classifies_and_manual_override_keeps_automatic_result(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    document = _upload(client, TRIP_ORDER)
    assert document["classification_status"] == "classified"
    assert document["confirmed_document_types"] == ["business_trip_order"]
    assert document["classification_source"] == "llm"
    assert document["needs_configuration"] is False
    assert document["classification_confidence"] >= 0.6

    updated = client.patch(
        f"/api/documents/{document['id']}/classification",
        json={"confirmed_document_types": ["payroll_order", "vacation_order"]},
    ).json()
    assert updated["classification_source"] == "manual"
    assert updated["confirmed_document_types"] == ["payroll_order", "vacation_order"]
    assert updated["automatic_classification"]["confirmed_document_types"] == [
        "business_trip_order"
    ]

    repeated = client.post(f"/api/documents/{document['id']}/classify").json()
    assert repeated["confirmed_document_types"] == ["payroll_order", "vacation_order"]

    restored = client.patch(
        f"/api/documents/{document['id']}/classification",
        json={"confirmed_document_types": []},
    ).json()
    assert restored["confirmed_document_types"] == ["business_trip_order"]


def test_classification_rejects_unknown_types_and_documents(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    document = _upload(client, "Текст.")

    response = client.patch(
        f"/api/documents/{document['id']}/classification",
        json={"confirmed_document_types": ["unknown"]},
    )

    assert response.status_code == 422
    assert client.post("/api/documents/999/classify").status_code == 404
    assert client.post("/api/documents/999/audit/preview").status_code == 404


def test_unknown_document_requires_configuration_and_never_runs_all_rules(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    client.post("/api/rules", json=_rule_payload("any", "текст"))
    document = _upload(client, "Обычный текст без признаков.")
    assert document["needs_configuration"] is True

    preview = client.post(f"/api/documents/{document['id']}/audit/preview").json()
    audit = client.post(f"/api/documents/{document['id']}/audit")

    assert preview["status"] == "needs_configuration"
    assert preview["selected_rule_ids"] == []
    assert "document_type_unknown" in preview["warnings"]
    assert audit.status_code == 409
    assert audit.json()["error"]["code"] == "audit_configuration_required"
    assert client.get(f"/api/documents/{document['id']}/report").status_code == 404
    assert client.get(f"/api/documents/{document['id']}").json()["status"] == "uploaded"


def test_preview_matches_the_audit_for_every_selection_mode(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    act = client.post(
        "/api/legal-acts",
        json={"code": "ACT", "title": "Act", "article_text": "Текст акта."},
    ).json()
    trip = client.post(
        "/api/rules",
        json=_rule_payload(
            "trip", "командировк", document_types=["business_trip_order"], legal_act_id=act["id"]
        ),
    ).json()
    payroll = client.post(
        "/api/rules", json=_rule_payload("payroll", "приказ", document_types=["payroll_order"])
    ).json()
    universal = client.post("/api/rules", json=_rule_payload("universal", "отчет")).json()
    document = _upload(client, TRIP_ORDER)

    for selection, expected in (
        ({}, {trip["id"], universal["id"]}),
        (
            {"selection_mode": "manual", "included_rule_ids": [payroll["id"]]},
            {payroll["id"]},
        ),
        (
            {"selection_mode": "combined", "included_rule_ids": [payroll["id"]]},
            {trip["id"], payroll["id"], universal["id"]},
        ),
        (
            {"selection_mode": "manual", "legal_act_ids": [act["id"]]},
            {trip["id"]},
        ),
        ({"excluded_rule_ids": [trip["id"]]}, {universal["id"]}),
        (
            {"selection_mode": "all", "confirm_all": True},
            {trip["id"], payroll["id"], universal["id"]},
        ),
    ):
        preview = client.post(
            f"/api/documents/{document['id']}/audit/preview", json=selection
        ).json()
        audit = client.post(f"/api/documents/{document['id']}/audit", json=selection)
        report = client.get(
            f"/api/documents/{document['id']}/report",
            params={"report_id": audit.json()["report_id"]},
        ).json()

        assert set(preview["selected_rule_ids"]) == expected, selection
        assert {item["rule_id"] for item in report["findings"]} == expected, selection


def test_all_mode_requires_explicit_confirmation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/api/rules", json=_rule_payload("any", "текст"))
    document = _upload(client, "Обычный текст.")

    response = client.post(
        f"/api/documents/{document['id']}/audit", json={"selection_mode": "all"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "all_mode_not_confirmed"
    assert client.get(f"/api/documents/{document['id']}/report").status_code == 404


def test_selection_rejects_unknown_identifiers(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    document = _upload(client, TRIP_ORDER)

    unknown_rule = client.post(
        f"/api/documents/{document['id']}/audit/preview",
        json={"included_rule_ids": [999]},
    )
    unknown_act = client.post(
        f"/api/documents/{document['id']}/audit/preview",
        json={"legal_act_ids": [999]},
    )

    assert unknown_rule.json()["error"]["code"] == "unknown_rule"
    assert unknown_act.json()["error"]["code"] == "unknown_legal_act"


def test_no_applicable_rules_is_reported_as_a_conflict(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/api/rules", json=_rule_payload("payroll", "приказ", document_types=["payroll_order"])
    )
    document = _upload(client, TRIP_ORDER)

    response = client.post(f"/api/documents/{document['id']}/audit")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_applicable_rules"


def test_rule_applicability_can_be_changed_and_is_validated(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    rule = client.post("/api/rules", json=_rule_payload("r", "x")).json()
    assert rule["applicability_scope"] == "universal"

    updated = client.patch(
        f"/api/rules/{rule['id']}/applicability",
        json={
            "applicability_scope": "typed",
            "document_types": ["payroll_order", "vacation_order"],
        },
    ).json()
    assert updated["document_types"] == ["payroll_order", "vacation_order"]
    assert updated["applicability_source"] == "manual"
    assert [
        item["rule_code"]
        for item in client.get("/api/rules?document_type=vacation_order").json()
    ] == ["r"]

    for body in (
        {"applicability_scope": "typed"},
        {"applicability_scope": "universal", "document_types": ["payroll_order"]},
        {"applicability_scope": "everything"},
        {"applicability_scope": "typed", "document_types": ["missing"]},
    ):
        response = client.patch(f"/api/rules/{rule['id']}/applicability", json=body)
        assert response.status_code == 422, body


def test_preview_reports_rag_candidates_without_selecting_rules(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    client.post(
        "/api/legal-acts",
        json={
            "code": "ACT-RAG",
            "title": "Act",
            "article_text": "Заработная плата выплачивается два раза в месяц.",
        },
    )
    with client.app.state.session_factory.begin() as session:
        act = session.scalar(select(LegalAct))
        act.processing_status = "completed"
    client.app.state.rebuild_rag_index()
    universal = client.post("/api/rules", json=_rule_payload("universal", "приказ")).json()
    document = _upload(client, TRIP_ORDER)

    preview = client.post(f"/api/documents/{document['id']}/audit/preview").json()

    assert preview["selected_rule_ids"] == [universal["id"]]
    assert preview["rag_recommendations"]
    assert {"score", "threshold", "reason"} <= set(preview["rag_recommendations"][0])


def test_audit_continues_when_rag_index_is_incompatible(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path)
    client.post("/api/rules", json=_rule_payload("universal", "приказ"))
    document = _upload(client, TRIP_ORDER)
    (tmp_path / "rag-index.sqlite3").unlink()
    SQLiteVectorStore(
        tmp_path / "rag-index.sqlite3",
        embedding_model="another-model",
        dimension=4,
        chunking_version="paragraph-v1",
    )

    preview = client.post(f"/api/documents/{document['id']}/audit/preview").json()
    audit = client.post(f"/api/documents/{document['id']}/audit")

    assert "rag_unavailable" in preview["warnings"]
    assert audit.status_code == 200
    assert audit.json()["total_findings"] == 1


def test_generated_rules_follow_legal_act_types_and_stay_unknown_otherwise(
    tmp_path: Path, monkeypatch
) -> None:
    answers = {
        "ACT-1": {"applicability_scope": "unknown", "applicability_confidence": 0.9},
        "ACT-2": {"applicability_scope": "universal", "applicability_confidence": 0.9},
        "ACT-3": {
            "applicability_scope": "typed",
            "document_types": ["business_trip_order"],
            "applicability_confidence": 0.9,
        },
    }

    class Extractor:
        def extract_rules(
            self, text: str, *, source_language: str, source_location: str, **options
        ):
            assert {item.code for item in options["document_types"]} >= {"vacation_order"}
            return (
                {
                    "rule_code": "model",
                    "name": "Срок",
                    "description": "Срок не менее 24 дней.",
                    "severity": "high",
                    "check_type": "duration",
                    "parameters": {"min_days": 24},
                    "source_quote": "Срок не менее 24 дней.",
                    "source_location": source_location,
                    **answers[options["legal_act_title"]],
                },
            )

    monkeypatch.setattr(
        "edm_auditor.api.app.create_rule_extraction_provider", lambda config: Extractor()
    )
    client = make_client(tmp_path)

    def upload(code: str, text: str, **data) -> dict:
        response = client.post(
            "/api/legal-acts/upload",
            data={"code": code, "title": code, **data},
            files={"file": ("act.txt", text.encode(), "text/plain")},
        )
        assert response.status_code == 201
        return response.json()

    unknown = upload("ACT-1", "Срок не менее 24 дней.")
    universal = upload("ACT-2", "Срок не менее 24 дней.")
    classified = upload("ACT-3", "Срок не менее 24 дней.")
    explicit = client.post(
        "/api/legal-acts/upload",
        data={"code": "ACT-4", "title": "ACT-3", "document_types": "vacation_order"},
        files={"file": ("act.txt", "Срок не менее 24 дней.".encode(), "text/plain")},
    ).json()
    rules = {item["legal_act_id"]: item for item in client.get("/api/rules").json()}

    assert rules[unknown["id"]]["applicability_scope"] == "unknown"
    assert rules[universal["id"]]["applicability_scope"] == "universal"
    assert rules[universal["id"]]["applicability_source"] == "llm"
    assert rules[classified["id"]]["document_types"] == ["business_trip_order"]
    assert rules[classified["id"]]["applicability_source"] == "llm"
    assert rules[explicit["id"]]["document_types"] == ["vacation_order"]
    assert rules[explicit["id"]]["applicability_source"] == "legal_act"

    # Clearing the explicit types brings back the answer of the model without a new request.
    client.patch(f"/api/legal-acts/{explicit['id']}", json={"document_types": []})
    rule = next(
        item
        for item in client.get("/api/rules").json()
        if item["legal_act_id"] == explicit["id"]
    )
    assert rule["document_types"] == ["business_trip_order"]
    assert rule["applicability_source"] == "llm"

    updated = client.patch(
        f"/api/legal-acts/{unknown['id']}", json={"document_types": ["payroll_order"]}
    )
    assert updated.json()["document_types"] == ["payroll_order"]
    rule = next(
        item
        for item in client.get("/api/rules").json()
        if item["legal_act_id"] == unknown["id"]
    )
    assert rule["applicability_scope"] == "typed"
    assert rule["document_types"] == ["payroll_order"]

    client.post(f"/api/legal-acts/{unknown['id']}/reprocess")
    rule = next(
        item
        for item in client.get("/api/rules").json()
        if item["legal_act_id"] == unknown["id"]
    )
    assert rule["document_types"] == ["payroll_order"]

    client.patch(
        f"/api/rules/{rule['id']}/applicability",
        json={"applicability_scope": "manual_only"},
    )
    client.patch(
        f"/api/legal-acts/{unknown['id']}", json={"document_types": ["vacation_order"]}
    )
    rule = next(
        item
        for item in client.get("/api/rules").json()
        if item["legal_act_id"] == unknown["id"]
    )
    assert rule["applicability_scope"] == "manual_only"


def test_report_stores_selection_snapshot_that_survives_later_changes(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    act = client.post(
        "/api/legal-acts",
        json={"code": "ACT-TRIP", "title": "Командировки", "article_text": "Текст."},
    ).json()
    applied = client.post(
        "/api/rules",
        json=_rule_payload(
            "trip", "приказ", document_types=["business_trip_order"], legal_act_id=act["id"]
        ),
    ).json()
    skipped = client.post(
        "/api/rules", json=_rule_payload("payroll", "приказ", document_types=["payroll_order"])
    ).json()
    document = _upload(client, TRIP_ORDER)
    audit = client.post(
        f"/api/documents/{document['id']}/audit", json={"excluded_rule_ids": []}
    )
    assert audit.status_code == 200
    url = f"/api/documents/{document['id']}/report"

    selection = client.get(url).json()["selection"]

    assert selection["selection_mode"] == "automatic"
    assert selection["confirmed_document_types"] == ["business_trip_order"]
    assert selection["classification_status"] == "classified"
    assert selection["applied_rule_ids"] == [applied["id"]]
    assert selection["applied_legal_acts"] == [
        {"id": act["id"], "code": "ACT-TRIP", "title": "Командировки"}
    ]
    reasons = {item["rule_id"]: item for item in selection["selection_reasons"]}
    assert reasons[applied["id"]]["reason"] == "rule_matched_document_type"
    assert reasons[skipped["id"]]["reason"] == "rule_excluded_by_document_type"
    assert client.get("/api/reports").json()[0]["selection_mode"] == "automatic"
    assert TRIP_ORDER not in str(selection)

    client.patch(
        f"/api/documents/{document['id']}/classification",
        json={"confirmed_document_types": ["payroll_order"]},
    )
    client.delete(f"/api/rules/{applied['id']}")
    client.delete(f"/api/legal-acts/{act['id']}")

    assert client.get(url).json()["selection"] == selection


def test_report_created_before_selection_stays_readable(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    document = _upload(client, TRIP_ORDER)
    with client.app.state.session_factory.begin() as session:
        session.add(
            AuditReport(
                document_id=document["id"],
                summary='{"diagnostics": [], "neural": {"status": "completed"}}',
            )
        )

    report = client.get(f"/api/documents/{document['id']}/report").json()

    assert report["selection"] is None
    assert report["summary"] == {"diagnostics": [], "neural": {"status": "completed"}}
    assert client.get("/api/reports").json()[0]["selection_mode"] is None


def _legal_act_extractor(*answers: dict):
    """Return one rule per answer; each quote exists in the uploaded act."""

    class Extractor:
        def extract_rules(self, text: str, *, source_language: str, source_location: str, **_):
            return tuple(
                {
                    "rule_code": f"model-{index}",
                    "name": "Срок",
                    "description": "Срок не менее 24 дней.",
                    "severity": "high",
                    "check_type": "duration",
                    "parameters": {"min_days": 24 + index},
                    "source_quote": f"Пункт {index}: срок не менее 24 дней.",
                    "source_location": source_location,
                    **answer,
                }
                for index, answer in enumerate(answers)
            )

    return Extractor()


def _upload_act(client: TestClient, count: int) -> dict:
    text = "\n".join(f"Пункт {index}: срок не менее 24 дней." for index in range(count))
    response = client.post(
        "/api/legal-acts/upload",
        data={"code": "ACT", "title": "Акт"},
        files={"file": ("act.txt", text.encode(), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()


def test_one_act_gives_each_rule_its_own_types(tmp_path: Path, monkeypatch) -> None:
    extractor = _legal_act_extractor(
        {
            "applicability_scope": "typed",
            "document_types": ["vacation_order", "invented_type"],
            "applicability_confidence": 0.9,
        },
        {
            "applicability_scope": "typed",
            "document_types": ["payroll_order"],
            "applicability_confidence": 0.8,
        },
        {"applicability_scope": "universal", "applicability_confidence": 0.3},
        {
            "applicability_scope": "typed",
            "document_types": ["invented_type"],
            "applicability_confidence": 0.9,
        },
    )
    monkeypatch.setattr(
        "edm_auditor.api.app.create_rule_extraction_provider", lambda config: extractor
    )
    client = make_client(tmp_path)

    _upload_act(client, 4)

    rules = sorted(client.get("/api/rules").json(), key=lambda item: item["id"])
    assert [item["document_types"] for item in rules] == [
        ["vacation_order"],
        ["payroll_order"],
        [],
        [],
    ]
    # A doubtful universal answer must not reach every document.
    assert [item["applicability_scope"] for item in rules] == [
        "typed",
        "typed",
        "unknown",
        "unknown",
    ]
    assert rules[2]["automatic_applicability"]["scope"] == "universal"


def test_suggested_type_needs_a_decision_and_is_not_repeated(
    tmp_path: Path, monkeypatch
) -> None:
    suggestion = {
        "applicability_scope": "unknown",
        "applicability_confidence": 0.9,
        "suggested_type_name": "Авансовый отчёт",
        "suggested_type_reason": "Требование к отчёту о расходах.",
    }
    extractor = _legal_act_extractor(suggestion, {**suggestion, "suggested_type_name": "авансовый  отчёт"})
    monkeypatch.setattr(
        "edm_auditor.api.app.create_rule_extraction_provider", lambda config: extractor
    )
    client = make_client(tmp_path)
    before = {item["code"] for item in client.get("/api/document-types").json()}

    _upload_act(client, 2)

    suggestions = client.get("/api/document-type-suggestions").json()
    assert len(suggestions) == 1
    assert suggestions[0]["occurrences"] == 2
    assert {item["code"] for item in client.get("/api/document-types").json()} == before

    accepted = client.post(
        f"/api/document-type-suggestions/{suggestions[0]['id']}/accept",
        json={"code": "travel_expense_report"},
    )
    assert accepted.status_code == 201
    assert accepted.json()["name"] == "Авансовый отчёт"
    assert accepted.json()["description"] == "Требование к отчёту о расходах."
    assert client.get("/api/document-type-suggestions").json() == []
    assert client.post(
        f"/api/document-type-suggestions/{suggestions[0]['id']}/dismiss"
    ).status_code == 409


def test_dismissed_suggestion_stays_dismissed(tmp_path: Path, monkeypatch) -> None:
    class Classifier(FakeClassificationProvider):
        def classify(self, text, *, title, filename, document_types):
            return {
                "document_types": [],
                "suggested_type_name": "Докладная записка",
                "suggested_type_reason": "Такого типа нет в каталоге.",
            }

    monkeypatch.setattr(
        "edm_auditor.api.app.create_document_classification_provider",
        lambda config: Classifier(),
    )
    client = make_client(tmp_path)

    document = _upload(client, "Докладная записка.")
    assert document["classification_status"] == "unknown"
    suggestion = client.get("/api/document-type-suggestions").json()[0]
    assert suggestion["document_id"] == document["id"]
    assert client.post(
        f"/api/document-type-suggestions/{suggestion['id']}/dismiss"
    ).status_code == 204

    client.post(f"/api/documents/{document['id']}/classify")

    assert client.get("/api/document-type-suggestions").json() == []
    dismissed = client.get("/api/document-type-suggestions?status=dismissed").json()
    assert dismissed[0]["occurrences"] == 2


def test_failed_classification_keeps_the_document_and_blocks_the_audit(
    tmp_path: Path, monkeypatch
) -> None:
    provider = FakeClassificationProvider()
    calls = {"fail": True}

    class Flaky:
        def classify(self, *args, **kwargs):
            if calls["fail"]:
                raise RuntimeError("model unavailable")
            return provider.classify(*args, **kwargs)

    monkeypatch.setattr(
        "edm_auditor.api.app.create_document_classification_provider", lambda config: Flaky()
    )
    client = make_client(tmp_path)

    document = _upload(client, TRIP_ORDER)
    assert document["classification_status"] == "pending"
    assert document["needs_configuration"] is True

    url = f"/api/documents/{document['id']}"
    for response in (
        client.post(f"{url}/audit/preview"),
        client.post(f"{url}/audit"),
        client.post(f"{url}/classify"),
    ):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "classification_model_error"
    assert client.get("/api/reports").json() == []

    calls["fail"] = False
    assert client.post(f"{url}/audit/preview").status_code == 200
    assert client.get(url).json()["confirmed_document_types"] == ["business_trip_order"]


def test_repeated_classification_failure_keeps_the_previous_result(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path)
    document = _upload(client, TRIP_ORDER)

    class Failing:
        def classify(self, *args, **kwargs):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "edm_auditor.api.app.create_document_classification_provider", lambda config: Failing()
    )
    failing = make_client(tmp_path)

    assert failing.post(f"/api/documents/{document['id']}/classify").status_code == 503
    stored = failing.get(f"/api/documents/{document['id']}").json()
    assert stored["classification_status"] == "classified"
    assert stored["confirmed_document_types"] == ["business_trip_order"]


def test_audit_refuses_a_document_needing_too_many_model_requests(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    class Entities(FakeEntityProvider):
        def extract(self, text: str):
            calls.append(text)
            return ()

    monkeypatch.setattr(
        "edm_auditor.api.app.create_entity_extraction_provider", lambda config: Entities()
    )
    client = make_client(tmp_path)
    client.post(
        "/api/rules",
        json={
            "rule_code": "universal-rule",
            "name": "Правило",
            "severity": "low",
            "check_type": "keyword",
            "description": "Ключевое слово",
            "parameters": {"keywords": ["запрет"], "mode": "forbidden"},
        },
    )
    with client.app.state.session_factory.begin() as session:
        stored = Document(
            title="Большой",
            file_type="txt",
            file_path="big.txt",
            raw_text="\n".join(["Строка документа для проверки размера."] * 20000),
            classification_status="classified",
            classification_source="manual",
        )
        session.add(stored)
        session.flush()
        document_id = stored.id

    response = client.post(
        f"/api/documents/{document_id}/audit",
        json={"selection_mode": "all", "confirm_all": True},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "document_too_large_for_audit"
    assert calls == []
    assert client.get("/api/reports").json() == []


def _add_universal_rule(client: TestClient) -> None:
    created = client.post(
        "/api/rules",
        json={
            "rule_code": "universal-rule",
            "name": "Правило",
            "severity": "low",
            "check_type": "keyword",
            "parameters": {"keywords": ["запрет"], "mode": "forbidden"},
        },
    )
    assert created.status_code == 201


MODEL_ERRORS = [
    (ModelRateLimited("limit"), 429, "model_rate_limited"),
    (ModelRequestTimeout("slow"), 504, "model_timeout"),
]


@pytest.mark.parametrize("error, status, code", MODEL_ERRORS)
def test_audit_reports_model_limits_and_timeouts(
    tmp_path: Path, monkeypatch, error, status, code
) -> None:
    class Entities(FakeEntityProvider):
        def extract(self, text: str):
            raise error

    monkeypatch.setattr(
        "edm_auditor.api.app.create_entity_extraction_provider", lambda config: Entities()
    )
    client = make_client(tmp_path)
    document = _upload(client, TRIP_ORDER)
    _add_universal_rule(client)

    response = client.post(
        f"/api/documents/{document['id']}/audit",
        json={"selection_mode": "all", "confirm_all": True},
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert client.get("/api/reports").json() == []


@pytest.mark.parametrize("error, status, code", MODEL_ERRORS)
def test_llm_analysis_reports_model_limits_and_timeouts(
    tmp_path: Path, monkeypatch, error, status, code
) -> None:
    class Llm(FakeLLMProvider):
        def generate(self, *, system_prompt, user_prompt, context=()):
            raise error

    monkeypatch.setattr("edm_auditor.api.app.create_llm_provider", lambda config: Llm())
    client = make_client(tmp_path)
    document = _upload(client, TRIP_ORDER)
    _add_universal_rule(client)

    response = client.post(
        f"/api/documents/{document['id']}/audit",
        json={"selection_mode": "all", "confirm_all": True},
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("error, status, code", MODEL_ERRORS)
def test_classification_reports_model_limits_and_timeouts(
    tmp_path: Path, monkeypatch, error, status, code
) -> None:
    class Classifier(FakeClassificationProvider):
        def classify(self, *args, **kwargs):
            raise error

    monkeypatch.setattr(
        "edm_auditor.api.app.create_document_classification_provider",
        lambda config: Classifier(),
    )
    client = make_client(tmp_path)

    document = _upload(client, TRIP_ORDER)
    assert document["classification_status"] == "pending"

    response = client.post(f"/api/documents/{document['id']}/classify")

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("error, status, code", MODEL_ERRORS)
def test_rule_extraction_stops_at_a_model_limit_or_timeout(
    tmp_path: Path, monkeypatch, error, status, code
) -> None:
    calls: list[str] = []

    class Extractor:
        def extract_rules(self, text: str, **_):
            calls.append(text)
            raise error

    monkeypatch.setattr(
        "edm_auditor.api.app.create_rule_extraction_provider", lambda config: Extractor()
    )
    client = make_client(tmp_path)

    response = client.post(
        "/api/legal-acts/upload",
        data={"code": "ACT", "title": "Акт"},
        files={
            "file": (
                "act.txt",
                "Статья 1. Первая.\nСтатья 2. Вторая.\nСтатья 3. Третья.".encode(),
                "text/plain",
            )
        },
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert len(calls) == 1
    act = client.get("/api/legal-acts").json()[0]
    assert act["processing_status"] == "failed"
    assert act["chunks_processed"] == 0
    diagnostics = client.get(f"/api/legal-acts/{act['id']}/diagnostics").json()["diagnostics"]
    assert [item["error_code"] for item in diagnostics] == [code]

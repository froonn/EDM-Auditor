"""Focused checks for the stage 2 rule contract and extraction workflow."""

from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.database import Base, create_session_factory
from edm_auditor.database.models import AuditRule
from edm_auditor.model_providers import rule_extraction_schema
from edm_auditor.rule_validation import validate_generated_rule
from fakes import (
    DeterministicEmbeddingProvider,
    FakeClassificationProvider,
    FakeEntityProvider,
    FakeLLMProvider,
)


def _make_client(tmp_path: Path, monkeypatch, rule_extractor) -> TestClient:
    monkeypatch.setenv("EDM_MODEL_PRESET", "lm-studio")
    for factory, provider in (
        ("create_llm_provider", FakeLLMProvider),
        ("create_document_classification_provider", FakeClassificationProvider),
        ("create_entity_extraction_provider", FakeEntityProvider),
        ("create_embedding_provider", DeterministicEmbeddingProvider),
    ):
        monkeypatch.setattr(
            f"edm_auditor.api.app.{factory}",
            lambda config, provider=provider: provider(),
        )
    monkeypatch.setattr(
        "edm_auditor.api.app.create_rule_extraction_provider",
        lambda config: rule_extractor,
    )
    engine = create_engine(
        f"sqlite:///{tmp_path / 'stage2.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return TestClient(
        create_app(
            settings=ApiSettings(
                upload_dir=tmp_path / "uploads",
                rag_index_path=tmp_path / "rag-index.sqlite3",
            ),
            session_factory=create_session_factory(engine),
        )
    )


def test_model_schema_uses_textual_constraint_fields_and_skipped_norms() -> None:
    schema = rule_extraction_schema()
    fields = schema["properties"]["rules"]["items"]["properties"]
    assert {"subject", "constraint_text", "constraint_json", "condition"} <= set(fields)
    assert "check_type" not in fields
    assert "parameters" not in fields
    assert "source_location" not in fields
    assert "skipped_norms" in schema["properties"]


def test_generated_rule_keeps_text_when_structure_is_absent_or_contradicts_text() -> None:
    absent = validate_generated_rule(
        {
            "subject": "Срок хранения",
            "constraint_text": "хранить не менее пяти лет",
            "constraint_json": None,
            "condition": "для кадровых документов",
            "severity": "medium",
            "source_quote": "Срок хранения — не менее пяти лет",
        },
        source_text="Срок хранения — не менее пяти лет",
        source_language="ru",
        source_location="article:1",
        index=1,
    )
    assert absent["constraint_json"] is None
    assert absent["constraint_text"] == "хранить не менее пяти лет"
    assert absent["source_location"] == "article:1"

    contradictory = validate_generated_rule(
        {
            "subject": "Срок уведомления",
            "constraint_text": "Уведомление направляется не менее чем за 10 дней.",
            "constraint_json": {"kind": "value", "operator": "lte", "value": 10, "unit": "day"},
            "condition": "",
            "severity": "high",
            "source_quote": "Уведомление направляется не менее чем за 10 дней.",
        },
        source_text="Уведомление направляется не менее чем за 10 дней.",
        source_language="ru",
        source_location="article:1",
        index=1,
    )
    assert contradictory["constraint_json"] is None
    assert contradictory["subject"] == "Срок уведомления"


def test_database_model_has_no_legacy_rule_type_columns() -> None:
    columns = set(AuditRule.__table__.c.keys())
    assert {"subject", "constraint_text", "constraint_json", "condition"} <= columns
    assert {"check_type", "parameters_json"}.isdisjoint(columns)


def test_per_rule_validation_and_skipped_norms_in_diagnostics(
    tmp_path: Path, monkeypatch
) -> None:
    class Extractor:
        last_skipped_norms = (
            {"source_quote": "Контроль осуществляет бухгалтер.", "reason": "не относится к документам"},
        )

        def extract_rules(self, text: str, **_):
            self.last_skipped_norms = (
                {"source_quote": "Контроль осуществляет бухгалтер.", "reason": "не относится к документам"},
            )
            return (
                {
                    "subject": "Валидное правило",
                    "constraint_text": "Компенсация не менее 50 рублей.",
                    "constraint_json": {"kind": "value", "operator": "gte", "value": 50, "unit": "byn"},
                    "condition": "",
                    "severity": "high",
                    "source_quote": "Компенсация не менее 50 рублей.",
                },
                {
                    "subject": "С несуществующей цитатой",
                    "constraint_text": "Текст",
                    "constraint_json": None,
                    "condition": "",
                    "severity": "low",
                    "source_quote": "Цитаты нет в акте.",
                },
            )

    client = _make_client(tmp_path, monkeypatch, Extractor())
    act_text = "1. Компенсация не менее 50 рублей.\n2. Контроль осуществляет бухгалтер."
    response = client.post(
        "/api/legal-acts/upload",
        data={"code": "ACT-MIXED", "title": "Положение"},
        files={"file": ("act.txt", act_text.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "partial"
    assert body["rules_accepted"] == 1
    assert body["rules_rejected"] == 1
    rules = client.get("/api/rules").json()
    assert [item["subject"] for item in rules] == ["Валидное правило"]

    diagnostics = client.get(f"/api/legal-acts/{body['id']}/diagnostics").json()["diagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["status"] == "partial"
    assert diagnostics[0]["error_code"] == "quote_not_found"
    assert "skipped: «Контроль осуществляет бухгалтер.» (не относится к документам)" in (
        diagnostics[0]["diagnostic_message"] or ""
    )

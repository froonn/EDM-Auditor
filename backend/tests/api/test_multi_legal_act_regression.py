"""Three legal acts must not add up to false findings in unrelated documents."""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.database import Base, create_session_factory
from fakes import (
    DeterministicEmbeddingProvider,
    FakeEntityProvider,
    FakeLLMProvider,
)

EXAMPLES = Path(__file__).parents[2] / "examples"

GENERATED_RULES = (
    {
        "rule_code": "remote-compensation",
        "check_type": "numeric",
        "parameters": {"entity": "money", "min": 50},
        "source_quote": "Ежемесячная компенсация расходов на интернет не может быть меньше 50 рублей.",
    },
    {
        "rule_code": "trip-duration",
        "check_type": "duration",
        "parameters": {"max_days": 30},
        "source_quote": "Срок служебной командировки не может превышать 30 календарных дней.",
    },
    {
        "rule_code": "trip-keyword",
        "check_type": "keyword",
        "parameters": {"keywords": ["командировка"], "mode": "required", "match": "stem"},
        "source_quote": "Командировочное удостоверение должно содержать слово «командировка».",
    },
    {
        "rule_code": "payroll-keyword",
        "check_type": "keyword",
        "parameters": {"keywords": ["заработная"], "mode": "required", "match": "stem"},
        "source_quote": "Заработная плата выплачивается не реже двух раз в месяц.",
    },
)


class ExampleRuleExtractor:
    """Return the prepared rules whose source quote occurs in the chunk."""

    model_name = "fake-extractor"

    def extract_rules(self, text: str, *, source_language: str, source_location: str):
        return tuple(
            {
                **rule,
                "name": rule["source_quote"],
                "description": rule["source_quote"],
                "severity": "high",
                "source_location": source_location,
            }
            for rule in GENERATED_RULES
            if rule["source_quote"] in text
        )


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EDM_MODEL_PRESET", "lm-studio")
    for factory, provider in (
        ("create_llm_provider", FakeLLMProvider),
        ("create_entity_extraction_provider", FakeEntityProvider),
        ("create_rule_extraction_provider", ExampleRuleExtractor),
        ("create_embedding_provider", DeterministicEmbeddingProvider),
    ):
        monkeypatch.setattr(
            f"edm_auditor.api.app.{factory}",
            lambda config, provider=provider: provider(),
        )
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    client = TestClient(
        create_app(
            settings=ApiSettings(
                upload_dir=tmp_path / "uploads",
                rag_index_path=tmp_path / "rag-index.sqlite3",
            ),
            session_factory=create_session_factory(engine),
        )
    )
    for code, title, filename, expected_type in (
        ("ACT-REMOTE", "Положение о дистанционной работе", "legal_act_remote_work.txt", "remote_work_agreement"),
        ("ACT-TRIP", "Положение о служебных командировках", "legal_act_business_trip.txt", "business_trip_order"),
        ("ACT-PAYMENTS", "Положение о выплате заработной платы", "legal_act_payments.txt", "payroll_order"),
    ):
        response = client.post(
            "/api/legal-acts/upload",
            data={"code": code, "title": title},
            files={"file": (filename, (EXAMPLES / filename).read_bytes(), "text/plain")},
        )
        assert response.status_code == 201
        rules = [
            rule
            for rule in client.get("/api/rules").json()
            if rule["legal_act_id"] == response.json()["id"]
        ]
        assert rules
        assert all(rule["document_types"] == [expected_type] for rule in rules)
    return client


def _audit(client: TestClient, filename: str, **selection) -> dict:
    document = client.post(
        "/api/documents/upload",
        files={"file": (filename, (EXAMPLES / filename).read_bytes(), "text/plain")},
    ).json()
    audit = client.post(f"/api/documents/{document['id']}/audit", json=selection)
    assert audit.status_code == 200, audit.text
    return client.get(f"/api/documents/{document['id']}/report").json()


def _applied_acts(report: dict) -> list[str]:
    return [act["code"] for act in report["selection"]["applied_legal_acts"]]


def test_each_document_gets_only_its_own_violation(client: TestClient) -> None:
    remote = _audit(client, "remote_work_agreement.txt")
    trip = _audit(client, "business_trip_order.txt")

    assert [item["quote"] for item in remote["findings"]] == ["35 рублей"]
    assert _applied_acts(remote) == ["ACT-REMOTE"]
    assert [item["quote"] for item in trip["findings"]] == ["45 календарных дней"]
    assert _applied_acts(trip) == ["ACT-TRIP"]


def test_all_mode_shows_the_false_findings_that_selection_prevents(client: TestClient) -> None:
    selective = _audit(client, "remote_work_agreement.txt")
    broad = _audit(
        client, "remote_work_agreement.txt", selection_mode="all", confirm_all=True
    )

    assert selective["total_findings"] == 1
    assert broad["total_findings"] == 3
    assert "all_mode_false_positive_risk" in broad["selection"]["warnings"]


@pytest.mark.parametrize(
    "filename",
    [
        "compliant_remote_work_agreement.txt",
        "compliant_business_trip_order.txt",
        "compliant_payroll_order.txt",
    ],
)
def test_compliant_documents_have_no_findings(client: TestClient, filename: str) -> None:
    report = _audit(client, filename)

    assert report["total_findings"] == 0
    assert report["selection"]["applied_rule_ids"]


def test_payroll_order_is_checked_only_by_the_payments_act(client: TestClient) -> None:
    report = _audit(client, "payroll_order.txt")

    assert _applied_acts(report) == ["ACT-PAYMENTS"]
    assert report["total_findings"] == 0

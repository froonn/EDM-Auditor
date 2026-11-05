"""Check the audit of the examples on answers saved from a real model run."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.database import Base, create_session_factory
from fakes import (
    DeterministicEmbeddingProvider,
    FakeClassificationProvider,
)

EXAMPLES = Path(__file__).parents[2] / "examples"

# Answers saved from a real Gemini run: the rules, entities, and verdicts it gave for the examples.
RECORDED = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "recorded_gemini_audit.json").read_text(
        encoding="utf-8"
    )
)
VERDICTS = {
    (item["description"], item["quote"]): item["is_violation"] for item in RECORDED["verdicts"]
}


class RecordedRuleExtractor:
    model_name = "recorded-extractor"

    def extract_rules(
        self, text: str, *, source_language: str, source_location: str, legal_act_title: str, **_
    ):
        return tuple(
            {**rule, "source_location": source_location}
            for rule in RECORDED["rules"][legal_act_title]
        )


class RecordedEntityProvider:
    model_name = "recorded-extractor"

    def extract(self, text: str):
        return RECORDED["entities"].get(text, ())


class RecordedLLMProvider:
    """Give the saved verdict; a pair never seen by the model stays a violation."""

    model_name = "recorded-llm"

    def generate(self, *, system_prompt, user_prompt, context=()) -> str:
        return json.dumps(
            {
                "analyses": [
                    {
                        "finding_key": item["finding_key"],
                        "explanation": "Пояснение.",
                        "recommendation": "",
                        "confidence": 0.9,
                        "is_violation": VERDICTS.get((item["description"], item["quote"]), True),
                    }
                    for item in json.loads(user_prompt).get("findings", [])
                ],
                "general_summary": "Итог.",
            }
        )


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EDM_MODEL_PRESET", "lm-studio")
    for factory, provider in (
        ("create_llm_provider", RecordedLLMProvider),
        ("create_document_classification_provider", FakeClassificationProvider),
        ("create_entity_extraction_provider", RecordedEntityProvider),
        ("create_rule_extraction_provider", RecordedRuleExtractor),
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
        assert all(
            rule["document_types"] == [expected_type]
            for rule in rules
            if rule["applicability_scope"] == "typed"
        )
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


def _quotes(report: dict) -> list[str]:
    return [" ".join((item["quote"] or "").split()) for item in report["findings"]]


def test_each_document_gets_only_its_own_violations(client: TestClient) -> None:
    remote = _audit(client, "remote_work_agreement.txt")
    trip = _audit(client, "business_trip_order.txt")

    assert _quotes(remote) == [
        "01.03.2027. Уведомление направлено работнику 25.02.2027",
        "35 рублей",
    ]
    assert _applied_acts(remote) == ["ACT-REMOTE"]
    assert _quotes(trip) == ["45 календарных дней", "7 календарных дней"]
    assert _applied_acts(trip) == ["ACT-TRIP"]


def test_model_rejects_values_that_the_norm_does_not_regulate(client: TestClient) -> None:
    trip = _audit(client, "business_trip_order.txt")
    payroll = _audit(client, "payroll_order.txt")

    assert [item["quote"] for item in trip["summary"]["rejected_candidates"]] == [
        "45 календарных дней"
    ]
    assert trip["high_count"] + trip["critical_count"] + trip["medium_count"] == 2
    assert [item["quote"] for item in payroll["summary"]["rejected_candidates"]] == ["25"]


def test_day_of_month_is_not_reported_as_a_period(client: TestClient) -> None:
    payroll = _audit(client, "payroll_order.txt")

    assert _quotes(payroll) == ["25 процентов", "8"]


def test_all_mode_shows_the_false_findings_that_selection_prevents(client: TestClient) -> None:
    selective = _audit(client, "remote_work_agreement.txt")
    broad = _audit(
        client, "remote_work_agreement.txt", selection_mode="all", confirm_all=True
    )

    assert selective["total_findings"] == 2
    assert broad["total_findings"] > selective["total_findings"]
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


def test_explanation_cites_the_norm_from_the_rule(client: TestClient) -> None:
    report = _audit(client, "remote_work_agreement.txt")

    basis = report["neural_analyses"][0]["legal_basis"]
    assert [item["code"] for item in basis] == ["ACT-REMOTE"]
    assert basis[0]["quote"].startswith("Работодатель обязан предоставить")

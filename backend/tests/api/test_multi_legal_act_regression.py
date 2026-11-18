"""Check the audit of the evaluation corpus on answers saved from a real model run and labels."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.database import Base, create_session_factory
from fakes import (
    BiasedEmbeddingProvider,
    FakeClassificationProvider,
)

CORPUS = Path(__file__).parents[2] / "evaluation" / "corpus"
ACTS_DIR = CORPUS / "acts"
DOCS_DIR = CORPUS / "documents"

# Rules recorded from Gemini 3.5 Flash Lite (stage4-v2); statements and matching verdicts
# are authored from evaluation/corpus/labels.toml.
RECORDED = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "recorded_gemini_audit.json").read_text(
        encoding="utf-8"
    )
)

DOC_TEXTS = {
    path.name: path.read_text(encoding="utf-8") for path in sorted(DOCS_DIR.glob("*.txt"))
}
RULE_SUBJECT_BY_CODE = {
    rule["rule_code"]: rule["subject"]
    for act_rules in RECORDED["rules"].values()
    for rule in act_rules
}
MATCHING_BY_DOC_SUBJECT = {
    doc_name: {
        RULE_SUBJECT_BY_CODE[rule_code]: verdict
        for rule_code, verdict in verdicts.items()
    }
    for doc_name, verdicts in RECORDED["matching"].items()
}


def _norm(text: str) -> str:
    return " ".join(text.split())


def _find_doc_name(text: str) -> str | None:
    normalized = _norm(text)
    for name, content in DOC_TEXTS.items():
        if normalized == _norm(content) or normalized in _norm(content):
            return name
    return None


def _find_doc_name_by_statements(statements: list[dict]) -> str | None:
    quotes = {_norm(item.get("source_quote", "")) for item in statements}
    quotes.discard("")
    if not quotes:
        return None
    for name, recorded_stmts in RECORDED["statements"].items():
        recorded_quotes = {_norm(item["source_quote"]) for item in recorded_stmts}
        if quotes <= recorded_quotes:
            return name
    return None


class RecordedRuleExtractor:
    model_name = "recorded-extractor"

    def extract_rules(
        self, text: str, *, source_language: str, source_location: str, legal_act_title: str, **_
    ):
        return tuple(
            {
                "subject": rule["subject"],
                "constraint_text": rule["constraint_text"],
                "constraint_json": rule["constraint_json"],
                "condition": rule["condition"],
                "severity": rule["severity"],
                "source_quote": rule["source_quote"],
                "applicability_scope": rule["applicability_scope"],
                "document_types": rule["document_types"],
                "applicability_confidence": rule["applicability_confidence"],
                "suggested_type_name": rule["suggested_type_name"],
                "suggested_type_reason": rule["suggested_type_reason"],
            }
            for rule in RECORDED["rules"][legal_act_title]
        )


class RecordedStatementProvider:
    model_name = "recorded-extractor"

    def extract_statements(self, chunk: str, *, source_language: str = "auto"):
        doc_name = _find_doc_name(chunk)
        if doc_name is None:
            return ()
        return tuple(RECORDED["statements"].get(doc_name, ()))


class RecordedLLMProvider:
    """Answer matching requests from the corpus table and confirm structural explanations."""

    model_name = "recorded-llm"

    def generate(self, *, system_prompt, user_prompt, context=(), response_schema=None) -> str:
        prompt = json.loads(user_prompt)
        if "rules" in prompt:
            stmts = prompt.get("document_statements", [])
            doc_name = _find_doc_name(
                prompt.get("document_text", "")
            ) or _find_doc_name_by_statements(stmts)
            doc_verdicts = MATCHING_BY_DOC_SUBJECT.get(doc_name or "", {})
            statements_by_quote = {
                _norm(item["source_quote"]): item["statement_id"]
                for item in stmts
            }
            analyses = []
            for rule in prompt["rules"]:
                verdict = doc_verdicts.get(rule["subject"])
                if verdict is not None:
                    matched_quote = verdict.get("matched_quote")
                    matched_id = (
                        statements_by_quote.get(_norm(matched_quote)) if matched_quote else None
                    )
                    analyses.append(
                        {
                            "finding_key": rule["finding_key"],
                            "matched_statement_id": matched_id,
                            "condition_applicable": verdict.get("condition_applicable", True),
                            "is_mandatory_condition": verdict.get("is_mandatory_condition", False),
                            "is_violation": verdict.get("is_violation", False),
                            "explanation": "Пояснение.",
                            "recommendation": "",
                            "confidence": 0.9,
                        }
                    )
                else:
                    # Cross-act rule in selection_mode="all": trigger a false positive.
                    candidates = rule.get("candidates", [])
                    analyses.append(
                        {
                            "finding_key": rule["finding_key"],
                            "matched_statement_id": candidates[0]["statement_id"] if candidates else None,
                            "condition_applicable": True,
                            "is_mandatory_condition": True,
                            "is_violation": True,
                            "explanation": "Лишнее срабатывание чужого правила.",
                            "recommendation": "",
                            "confidence": 0.9,
                        }
                    )
            return json.dumps(
                {
                    "schema_version": "4",
                    "analyses": analyses,
                    "general_summary": "Итог.",
                }
            )
        return json.dumps(
            {
                "schema_version": "3",
                "analyses": [
                    {
                        "finding_key": item["finding_key"],
                        "explanation": "Пояснение.",
                        "recommendation": "",
                        "confidence": 0.9,
                        "is_violation": True,
                    }
                    for item in prompt.get("findings", [])
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
        ("create_entity_extraction_provider", RecordedStatementProvider),
        ("create_rule_extraction_provider", RecordedRuleExtractor),
        ("create_embedding_provider", BiasedEmbeddingProvider),
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
    for code, title, filename in (
        ("ACT-PAYMENTS", "Положение об оплате труда работников", "payments.txt"),
        ("ACT-REMOTE", "Положение о дистанционной работе", "remote_work.txt"),
        ("ACT-TRIP", "Положение о служебных командировках", "business_trip.txt"),
        ("ACT-VACATION", "Положение о трудовых отпусках", "vacation.txt"),
    ):
        response = client.post(
            "/api/legal-acts/upload",
            data={"code": code, "title": title},
            files={"file": (filename, (ACTS_DIR / filename).read_bytes(), "text/plain")},
        )
        assert response.status_code == 201
        rules = [
            rule
            for rule in client.get("/api/rules").json()
            if rule["legal_act_id"] == response.json()["id"]
        ]
        assert rules
    return client


def _audit(client: TestClient, filename: str, **selection) -> dict:
    document = client.post(
        "/api/documents/upload",
        files={"file": (filename, (DOCS_DIR / filename).read_bytes(), "text/plain")},
    ).json()
    audit = client.post(f"/api/documents/{document['id']}/audit", json=selection)
    assert audit.status_code == 200, audit.text
    return client.get(f"/api/documents/{document['id']}/report").json()


def _applied_acts(report: dict) -> list[str]:
    return [act["code"] for act in report["selection"]["applied_legal_acts"]]


def _quotes(report: dict) -> list[str]:
    return [" ".join((item["quote"] or "").split()) for item in report["findings"] if item["quote"]]


def test_each_document_gets_only_its_own_violations(client: TestClient) -> None:
    remote = _audit(client, "remote_violating.txt")
    trip = _audit(client, "trip_violating.txt")
    vacation = _audit(client, "vacation_violating.txt")

    assert _quotes(remote) == ["35 рублей", "25.02.2027"]
    assert any(item["evaluation_mode"] == "missing" for item in remote["findings"])
    assert _applied_acts(remote) == ["ACT-REMOTE"]

    assert _quotes(trip) == ["45 календарных дней", "20 рублей", "7 рабочих дней"]
    assert any(item["evaluation_mode"] == "missing" for item in trip["findings"])
    assert _applied_acts(trip) == ["ACT-TRIP"]

    assert _quotes(vacation) == ["21 календарный день", "заменить денежной компенсацией", "24.11.2026"]
    assert any(item["evaluation_mode"] == "missing" for item in vacation["findings"])
    assert _applied_acts(vacation) == ["ACT-VACATION"]


def test_day_of_month_and_frequency_are_detected_without_false_period_matches(
    client: TestClient,
) -> None:
    payroll = _audit(client, "payroll_violating.txt")

    assert _quotes(payroll) == [
        "один раз в месяц",
        "25 процентов",
        "8 числа следующего месяца",
        "продукцией собственного производства",
    ]
    assert any(item["evaluation_mode"] == "missing" for item in payroll["findings"])


def test_conditional_rules_apply_only_when_condition_holds(client: TestClient) -> None:
    remote_child = _audit(client, "remote_child.txt")
    vacation_minor = _audit(client, "vacation_minor.txt")

    assert _quotes(remote_child) == ["за 14 календарных дней"]
    assert _quotes(vacation_minor) == ["24 календарных дня"]


def test_all_mode_shows_the_false_findings_that_selection_prevents(client: TestClient) -> None:
    selective = _audit(client, "remote_violating.txt")
    broad = _audit(
        client, "remote_violating.txt", selection_mode="all", confirm_all=True
    )

    assert selective["total_findings"] == 3
    assert broad["total_findings"] > selective["total_findings"]
    assert "all_mode_false_positive_risk" in broad["selection"]["warnings"]


@pytest.mark.parametrize(
    "filename",
    [
        "payroll_compliant.txt",
        "payroll_paraphrase.txt",
        "remote_compliant.txt",
        "trip_compliant.txt",
        "vacation_compliant.txt",
    ],
)
def test_compliant_documents_have_no_findings(client: TestClient, filename: str) -> None:
    report = _audit(client, filename)

    assert report["total_findings"] == 0
    assert report["selection"]["applied_rule_ids"]


def test_payroll_order_is_checked_only_by_the_payments_act(client: TestClient) -> None:
    report = _audit(client, "payroll_violating.txt")

    assert _applied_acts(report) == ["ACT-PAYMENTS"]


def test_explanation_cites_the_norm_from_the_rule(client: TestClient) -> None:
    report = _audit(client, "remote_violating.txt")

    basis = report["neural_analyses"][0]["legal_basis"]
    assert [item["code"] for item in basis] == ["ACT-REMOTE"]
    assert basis[0]["quote"]

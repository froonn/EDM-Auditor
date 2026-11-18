"""Focused checks for the stage 3 document statement extraction, caching, and unit normalization."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.audit_engine import (
    AuditEngine,
    AuditPersistence,
    ChunkedStatementExtractor,
    LLMInterpreter,
    RuleSpec,
    statements_from_provider,
)
from edm_auditor.database import Base, create_session_factory
from edm_auditor.database.models import AuditRule, Document, DocumentStatement, DocumentType
from edm_auditor.model_config import ModelConfig
from edm_auditor.model_providers import (
    GoogleAIStudioStatementExtractionProvider,
    OpenAICompatibleStatementExtractionProvider,
    STATEMENT_EXTRACTION_SCHEMA,
)
from edm_auditor.rule_validation import (
    normalize_constraint_json,
    parse_constraint_from_text,
    validate_generated_statement,
)
from edm_auditor.audit_engine.matching import RuleMatcher
from edm_auditor.model_config import AuditMatchingConfig
from fakes import (
    BiasedEmbeddingProvider,
    DeterministicEmbeddingProvider,
    FakeClassificationProvider,
    FakeLLMProvider,
    FakeRuleExtractor,
)


def test_unit_normalization_is_shared_by_rules_and_statements() -> None:
    # Weeks and months are converted to days by normalize_constraint_json.
    months = normalize_constraint_json(
        {"kind": "value", "operator": "lte", "value": 4, "unit": "month"},
        constraint_text="Испытательный срок составляет 4 месяца.",
        source_quote="Испытательный срок 4 месяца.",
    )
    assert months == {"kind": "value", "operator": "lte", "value": 120, "unit": "day"}

    weeks = normalize_constraint_json(
        {"kind": "value", "operator": "gte", "value": 2, "unit": "недели"},
        constraint_text="Срок предупреждения 2 недели.",
        source_quote="за две недели",
    )
    assert weeks == {"kind": "value", "operator": "gte", "value": 14, "unit": "day"}

    # Even when the model sets unit="day" with value=4 for "4 месяца", text rescaling converts to 120 days.
    rescaled = normalize_constraint_json(
        {"kind": "value", "operator": "eq", "value": 4, "unit": "day"},
        constraint_text="Испытательный срок 4 месяца.",
        source_quote="Испытательный срок 4 месяца.",
    )
    assert rescaled == {"kind": "value", "operator": "eq", "value": 120, "unit": "day"}

    # Frequency and day_of_month with month_offset normalization.
    freq = parse_constraint_from_text("Заработная плата выплачивается два раза в месяц.")
    assert freq == {"kind": "frequency", "operator": "eq", "count": 2, "period": "month"}

    two_days = normalize_constraint_json(
        {"kind": "day_of_month", "operator": "eq", "day": 15, "month_offset": 0},
        constraint_text="Выплату заработной платы производить 15 и 30 числа каждого месяца.",
        source_quote="Выплату производить 15 и 30 числа каждого месяца.",
    )
    assert two_days == {"kind": "frequency", "operator": "eq", "count": 2, "period": "month"}

    dom = parse_constraint_from_text(
        "Окончательный расчет производится не позднее 5 числа следующего месяца."
    )
    assert dom == {
        "kind": "day_of_month",
        "operator": "lte",
        "day": 5,
        "month_offset": 1,
    }


def test_validate_generated_statement_checks_quote_and_drops_bad_structure() -> None:
    text = "1. Выплачивать заработную плату один раз в месяц.\n2. Оплата производится на счет работника."
    valid = validate_generated_statement(
        {
            "subject": "Частота выплаты заработной платы",
            "statement_text": "Заработная плата выплачивается один раз в месяц.",
            "constraint_json": {"kind": "frequency", "operator": "eq", "count": 1, "period": "month"},
            "source_quote": "Выплачивать заработную плату один раз в месяц.",
        },
        source_text=text,
        source_language="ru",
    )
    assert valid["start_char"] == 3
    assert text[valid["start_char"] : valid["end_char"]] == valid["source_quote"]
    assert valid["constraint_json"] == {
        "kind": "frequency",
        "operator": "eq",
        "count": 1,
        "period": "month",
    }

    # Contradictory structure (count=2 when text says "один раз") is dropped, keeping textual statement.
    dropped = validate_generated_statement(
        {
            "subject": "Частота выплаты заработной платы",
            "statement_text": "Заработная плата выплачивается один раз в месяц.",
            "constraint_json": {"kind": "frequency", "operator": "eq", "count": 2, "period": "month"},
            "source_quote": "Выплачивать заработную плату один раз в месяц.",
        },
        source_text=text,
        source_language="ru",
    )
    assert dropped["constraint_json"] is None
    assert dropped["statement_text"] == "Заработная плата выплачивается один раз в месяц."


def test_chunked_statement_extractor_sends_one_request_per_chunk_and_restores_offsets() -> None:
    calls: list[str] = []

    class FakeStatementProvider:
        model_name = "fake-statement"

        def extract_statements(self, chunk: str, *, source_language: str = "auto"):
            calls.append(chunk)
            if "35 рублей" in chunk:
                return (
                    {
                        "subject": "Компенсация за интернет",
                        "statement_text": "Компенсация составляет 35 рублей.",
                        "constraint_json": {
                            "kind": "value",
                            "operator": "eq",
                            "value": 35,
                            "unit": "byn",
                        },
                        "source_quote": "Компенсация составляет 35 рублей.",
                    },
                )
            return (
                {
                    "subject": "Дистанционная работа",
                    "statement_text": "Работа выполняется дистанционно.",
                    "constraint_json": None,
                    "source_quote": "Работа выполняется дистанционно.",
                },
            )

    doc_text = "Работа выполняется дистанционно.\n\n" + ("Текст условия. " * 20) + "\n\nКомпенсация составляет 35 рублей."
    extractor = ChunkedStatementExtractor(
        FakeStatementProvider(),
        max_chars=200,
        overlap_chars=0,
        prompt_version="v3",
    )
    statements = extractor(doc_text)

    assert len(calls) >= 2
    assert len(statements) == 2
    for stmt in statements:
        assert doc_text[stmt.start_char : stmt.end_char] == stmt.source_quote
        assert stmt.prompt_version == "v3"


def test_persistence_caches_statements_across_repeated_audits(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cache.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    extraction_calls = 0

    class CountingProvider:
        model_name = "counting-extractor"

        def extract_statements(self, chunk: str, *, source_language: str = "auto"):
            nonlocal extraction_calls
            extraction_calls += 1
            return (
                {
                    "subject": "Продолжительность отпуска",
                    "statement_text": "Отпуск составляет две недели.",
                    "constraint_json": {
                        "kind": "value",
                        "operator": "eq",
                        "value": 2,
                        "unit": "недели",
                    },
                    "source_quote": "Отпуск составляет две недели.",
                },
            )

    text = "Приказ об отпуске.\n\nОтпуск составляет две недели."
    with session_factory.begin() as session:
        doc_type = DocumentType(code="vacation_order", name="Vacation order")
        doc = Document(
            title="Vacation",
            file_type="txt",
            file_path="vacation.txt",
            raw_text=text,
            classification_status="classified",
            classification_confidence=1.0,
            confirmed_types=[doc_type],
        )
        rule = AuditRule(
            rule_code="VAC-MIN",
            subject="Продолжительность отпуска",
            constraint_text="Отпуск не менее 24 дней.",
            constraint_json='{"kind":"value","operator":"gte","value":24,"unit":"day"}',
            severity="high",
            applicability_scope="typed",
            document_types=[doc_type],
        )
        session.add_all([doc_type, doc, rule])
        session.flush()
        doc_id = doc.id

    stmt_extractor = ChunkedStatementExtractor(CountingProvider(), prompt_version="v1")
    llm = FakeLLMProvider()
    matcher = RuleMatcher(llm, BiasedEmbeddingProvider(), AuditMatchingConfig())
    persistence = AuditPersistence(
        session_factory,
        engine=AuditEngine(statement_extractor=stmt_extractor),
        neural_interpreter=LLMInterpreter(llm),
        statement_prompt_version="v1",
        rule_matcher=matcher,
    )

    first_report = persistence.audit_document(doc_id)
    assert extraction_calls == 1
    assert first_report.total_findings == 1

    # Second audit with the same prompt_version reuses stored statements without calling provider.
    second_report = persistence.audit_document(doc_id)
    assert extraction_calls == 1
    assert second_report.total_findings == 1

    with session_factory() as session:
        stored_doc = session.get(Document, doc_id)
        stored_stmts = session.scalars(
            select(DocumentStatement).where(DocumentStatement.document_id == doc_id)
        ).all()
        assert stored_doc.statements_version == "v1"
        assert len(stored_stmts) == 1
        assert stored_stmts[0].subject == "Продолжительность отпуска"
        assert '"value": 14' in (stored_stmts[0].constraint_json or "")

    # Bumping prompt_version triggers a fresh extraction.
    persistence_v2 = AuditPersistence(
        session_factory,
        engine=AuditEngine(statement_extractor=stmt_extractor),
        neural_interpreter=LLMInterpreter(llm),
        statement_prompt_version="v2",
        rule_matcher=matcher,
    )
    persistence_v2.audit_document(doc_id)
    assert extraction_calls == 2


def test_api_returns_document_statements_on_document_detail_and_endpoint(
    tmp_path: Path, monkeypatch
) -> None:
    class StatementProvider:
        model_name = "statement-provider"

        def extract_statements(self, text: str, *, source_language: str = "auto"):
            return (
                {
                    "subject": "Частота выплаты зарплаты",
                    "statement_text": "Выплата один раз в месяц.",
                    "constraint_json": {
                        "kind": "frequency",
                        "operator": "eq",
                        "count": 1,
                        "period": "month",
                    },
                    "source_quote": "Заработная плата выплачивается один раз в месяц.",
                },
            )

    monkeypatch.setenv("EDM_MODEL_PRESET", "lm-studio")
    for factory, provider in (
        ("create_llm_provider", FakeLLMProvider),
        ("create_document_classification_provider", FakeClassificationProvider),
        ("create_entity_extraction_provider", StatementProvider),
        ("create_rule_extraction_provider", FakeRuleExtractor),
        ("create_embedding_provider", DeterministicEmbeddingProvider),
    ):
        monkeypatch.setattr(
            f"edm_auditor.api.app.{factory}",
            lambda config, provider=provider: provider(),
        )
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api-stage3.sqlite3'}",
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

    upload = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "payroll.txt",
                "Приказ о выплате заработной платы.\n\nЗаработная плата выплачивается один раз в месяц.".encode(
                    "utf-8"
                ),
                "text/plain",
            )
        },
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    extracted = client.post(f"/api/documents/{doc_id}/statements/extract")
    assert extracted.status_code == 200
    items = extracted.json()
    assert len(items) == 1
    assert items[0]["subject"] == "Частота выплаты зарплаты"
    assert items[0]["constraint_json"] == {
        "kind": "frequency",
        "operator": "eq",
        "count": 1,
        "period": "month",
    }

    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["statements_version"] == "1"
    assert len(detail["statements"]) == 1
    assert detail["statements"][0]["source_quote"] == "Заработная плата выплачивается один раз в месяц."

    listed = client.get(f"/api/documents/{doc_id}/statements").json()
    assert listed == detail["statements"]


def test_openai_and_google_statement_extraction_providers_use_statement_schema(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(config, endpoint, payload, timeout):
        captured.update(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"statements":[{"subject":"Срок отпуска",'
                            '"statement_text":"Отпуск 24 дня.",'
                            '"constraint_json":{"kind":"value","operator":"eq","value":24,"unit":"day"},'
                            '"source_quote":"Отпуск 24 дня."}]}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("edm_auditor.model_providers._post_json", fake_post)
    openai_provider = OpenAICompatibleStatementExtractionProvider(
        ModelConfig(
            provider="openai-compatible",
            model="google/gemma-4-e4b",
            base_url="http://localhost:1234/v1",
            structured_output="json_schema",
        )
    )
    result = openai_provider.extract_statements("Отпуск 24 дня.", source_language="ru")
    assert len(result) == 1
    assert result[0]["subject"] == "Срок отпуска"
    assert captured["response_format"]["json_schema"]["name"] == "statement_extraction"
    assert STATEMENT_EXTRACTION_SCHEMA["required"] == ["statements"]

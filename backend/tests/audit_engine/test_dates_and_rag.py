from pathlib import Path

from edm_auditor.audit_engine import AuditEngine, RuleSpec
from edm_auditor.audit_engine import entities_from_provider
from edm_auditor.rag import (
    IndexSource,
    RAGIndexer,
    RAGSearch,
    SQLiteVectorStore,
)
from fakes import DeterministicEmbeddingProvider, no_entities


def test_date_and_duration_rules_compare_normalized_values() -> None:
    result = AuditEngine(entity_extractor=no_entities).audit(
        "Договор заключен 01.02.2026. Испытательный срок 4 месяца.",
        [
            RuleSpec(
                rule_id=1,
                rule_code="date-after",
                name="Date must not be too early",
                severity="high",
                check_type="date",
                parameters={"after": "2026-03-01"},
            ),
            RuleSpec(
                rule_id=2,
                rule_code="probation-limit",
                name="Probation limit",
                severity="high",
                check_type="duration",
                parameters={"max_days": 90},
            ),
        ],
    )

    assert [finding.rule_code for finding in result.findings] == [
        "date-after",
        "probation-limit",
    ]
    assert result.findings[0].quote == "01.02.2026"
    assert result.findings[1].quote == "4 месяца"


def test_provider_entities_support_qualifying_words_in_durations() -> None:
    text = "Работнику предоставляется отпуск 14 календарных дней."
    entities = entities_from_provider(
        text, [{"kind": "duration", "value": "14 календарных дней"}]
    )

    result = AuditEngine(
        entity_extractor=lambda _: entities
    ).audit(
        text,
        [
            RuleSpec(
                rule_id=9,
                rule_code="annual-leave-minimum",
                name="Minimum annual leave",
                severity="high",
                check_type="duration",
                parameters={"min_days": 24},
            )
        ],
    )

    assert result.findings[0].quote == "14 календарных дней"


def test_duration_rule_checks_date_interval_when_duration_is_not_written() -> None:
    result = AuditEngine(entity_extractor=no_entities).audit(
        "Изменение действует с 01.03.2027. Уведомление направлено 25.02.2027.",
        [
            RuleSpec(
                rule_id=10,
                rule_code="notice-period",
                name="Notice period",
                severity="high",
                check_type="duration",
                parameters={"min_days": 10},
            )
        ],
    )

    assert len(result.findings) == 1
    assert result.findings[0].quote == "01.03.2027. Уведомление направлено 25.02.2027"


def test_required_keyword_accepts_inflected_word_forms() -> None:
    result = AuditEngine(entity_extractor=no_entities).audit(
        "Соглашение о дистанционной работе предусматривает дистанционную работу.",
        [
            RuleSpec(
                rule_id=11,
                rule_code="required-remote-word",
                name="Required remote wording",
                severity="medium",
                check_type="keyword",
                parameters={"keywords": ["дистанционная"], "mode": "required"},
            )
        ],
    )

    assert result.findings == ()


def test_required_keyword_reports_missing_wording() -> None:
    result = AuditEngine(entity_extractor=no_entities).audit(
        "Соглашение о работе.",
        [
            RuleSpec(
                rule_id=12,
                rule_code="required-remote-word",
                name="Required remote wording",
                severity="medium",
                check_type="keyword",
                parameters={"keywords": ["дистанционная"], "mode": "required"},
            )
        ],
    )

    assert len(result.findings) == 1
    assert result.findings[0].quote is None


def test_semantic_rule_returns_ranked_offline_normative_context(tmp_path: Path) -> None:
    fixture = (Path(__file__).parents[1] / "fixtures" / "legal_context.txt").read_text()
    provider = DeterministicEmbeddingProvider(dimension=16)
    store = SQLiteVectorStore(
        tmp_path / "vectors.sqlite3",
        embedding_model=provider.model_name,
        dimension=provider.dimension,
        chunking_version="paragraph-v1",
    )
    RAGIndexer(store, provider).build([IndexSource(legal_act_id=7, text=fixture)])

    result = AuditEngine(
        entity_extractor=no_entities, rag_searcher=RAGSearch(store, provider)
    ).audit(
        "Отпуск работника составляет 14 календарных дней.",
        [
            RuleSpec(
                rule_id=3,
                rule_code="leave-context",
                name="Leave context",
                severity="medium",
                check_type="semantic",
                parameters={"query": "минимальная продолжительность оплачиваемого отпуска"},
            )
        ],
    )

    assert result.findings
    context = result.findings[0].source_context
    assert context is not None
    assert context["legal_act_id"] == 7
    assert context["chunk_id"]
    assert context["score"] > 0

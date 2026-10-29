from pathlib import Path

from edm_auditor.audit_engine import AuditEngine, RuleSpec
from edm_auditor.rag import (
    DeterministicEmbeddingProvider,
    IndexSource,
    RAGIndexer,
    RAGSearch,
    SQLiteVectorStore,
)


def test_date_and_duration_rules_compare_normalized_values() -> None:
    result = AuditEngine().audit(
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

    result = AuditEngine(RAGSearch(store, provider)).audit(
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

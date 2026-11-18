import json

import pytest
from sqlalchemy import select

from edm_auditor.audit_engine import AuditEngine, AuditPersistence, LLMInterpreter, RuleSpec, StatementSpec
from edm_auditor.audit_engine.matching import (
    EVALUATION_MISSING,
    EVALUATION_MODEL,
    EVALUATION_STRUCTURED,
    RuleMatcher,
    candidate_pairs,
    compare_structured,
)
from edm_auditor.audit_engine.neural_errors import AuditModelError
from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.models import AuditRule, Base, Document, DocumentType
from edm_auditor.model_config import AuditMatchingConfig
from edm_auditor.model_providers import MATCHING_RESPONSE_SCHEMA
from fakes import DeterministicEmbeddingProvider, FakeLLMProvider, no_entities

TEXT = (
    "Приказ\n\n1. Заработная плата выплачивается один раз в месяц.\n"
    "2. Часть заработной платы выплачивается продукцией.\n"
)
FREQ_RULE = {"kind": "frequency", "operator": "gte", "count": 2, "period": "month"}


def _rule(code: str, subject: str, text: str, constraint=None, **extra) -> RuleSpec:
    return RuleSpec(
        rule_id=extra.pop("rule_id", 1),
        rule_code=code,
        subject=subject,
        constraint_text=text,
        severity="high",
        constraint_json=constraint,
        **extra,
    )


def _statement(subject: str, text: str, constraint=None, *, quote: str | None = None) -> StatementSpec:
    quote = quote or text
    start = TEXT.find(quote)
    return StatementSpec(
        subject=subject,
        statement_text=text,
        source_quote=quote,
        start_char=max(start, 0),
        end_char=max(start, 0) + len(quote),
        constraint_json=constraint,
    )


FREQ_STATEMENT = _statement(
    "периодичность выплаты заработной платы",
    "Заработная плата выплачивается один раз в месяц.",
    {"kind": "frequency", "operator": "eq", "count": 1, "period": "month"},
)
KIND_STATEMENT = _statement(
    "форма выплаты", "Часть заработной платы выплачивается продукцией."
)


class ScriptedLLM:
    """Answer each rule from a table of verdicts keyed by finding_key."""

    model_name = "scripted-llm"

    def __init__(self, verdicts: dict[str, dict]) -> None:
        self.verdicts = verdicts
        self.prompts: list[dict] = []
        self.schemas: list[object] = []

    def generate(self, *, system_prompt, user_prompt, context=(), response_schema=None) -> str:
        prompt = json.loads(user_prompt)
        self.prompts.append(prompt)
        self.schemas.append(response_schema)
        analyses = []
        for rule in prompt["rules"]:
            verdict = {
                "matched_statement_id": None,
                "condition_applicable": True,
                "is_mandatory_condition": False,
                "is_violation": False,
                "explanation": "Пояснение.",
                "recommendation": "",
                "confidence": 0.9,
                **self.verdicts.get(rule["finding_key"], {}),
            }
            analyses.append({"finding_key": rule["finding_key"], **verdict})
        return json.dumps(
            {"schema_version": "4", "analyses": analyses, "general_summary": "Итог."}
        )


def _matcher(llm, **config) -> RuleMatcher:
    return RuleMatcher(llm, DeterministicEmbeddingProvider(), AuditMatchingConfig(**config))


@pytest.mark.parametrize(
    "rule, statement, expected",
    [
        (FREQ_RULE, {"kind": "frequency", "operator": "eq", "count": 1, "period": "month"}, False),
        (FREQ_RULE, {"kind": "frequency", "operator": "eq", "count": 2, "period": "month"}, True),
        (FREQ_RULE, {"kind": "frequency", "operator": "eq", "count": 1, "period": "year"}, None),
        (
            {"kind": "value", "operator": "lte", "value": 30, "unit": "day"},
            {"kind": "value", "operator": "eq", "value": 45, "unit": "day"},
            False,
        ),
        (
            {"kind": "value", "operator": "lte", "value": 30, "unit": "day"},
            {"kind": "value", "operator": "eq", "value": 20, "unit": "byn"},
            None,
        ),
        (
            {"kind": "day_of_month", "operator": "lte", "day": 5, "month_offset": 1},
            {"kind": "day_of_month", "operator": "eq", "day": 8, "month_offset": 1},
            False,
        ),
        (
            {"kind": "day_of_month", "operator": "lte", "day": 5, "month_offset": 1},
            {"kind": "day_of_month", "operator": "lte", "day": 28, "month_offset": 0},
            True,
        ),
        (None, {"kind": "value", "operator": "eq", "value": 1, "unit": "day"}, None),
        (FREQ_RULE, None, None),
    ],
)
def test_structures_are_compared_by_code(rule, statement, expected) -> None:
    assert compare_structured(rule, statement) is expected


def test_candidates_keep_the_closest_statements_above_the_threshold() -> None:
    pairs = candidate_pairs(
        [(1.0, 0.0)],
        [(0.0, 1.0), (1.0, 0.1), (0.9, 0.5), (0.8, 0.0)],
        threshold=0.8,
        limit=2,
    )

    assert [index for index, _ in pairs[0]] == [3, 1]


def test_structured_violation_is_decided_by_code_even_if_the_model_disagrees() -> None:
    llm = ScriptedLLM(
        {"freq": {"matched_statement_id": 1, "is_violation": False, "explanation": "Нарушения нет."}}
    )

    outcome = _matcher(llm).match(
        [_rule("freq", "выплата заработной платы", "не реже двух раз в месяц", FREQ_RULE)],
        [FREQ_STATEMENT, KIND_STATEMENT],
        TEXT,
    )

    finding = outcome.findings[0].finding
    assert finding.evaluation_mode == EVALUATION_STRUCTURED
    assert finding.statement_text == FREQ_STATEMENT.statement_text
    assert finding.quote == TEXT[FREQ_STATEMENT.start_char : FREQ_STATEMENT.end_char]
    assert llm.schemas == [MATCHING_RESPONSE_SCHEMA]
    first_candidate = llm.prompts[0]["rules"][0]["candidates"][0]
    assert first_candidate["structured_comparison"] == "violation"


def test_structured_compliance_is_not_overruled_by_the_model() -> None:
    llm = ScriptedLLM({"freq": {"matched_statement_id": 1, "is_violation": True}})
    statement = _statement(
        "периодичность выплаты",
        "Заработная плата выплачивается один раз в месяц.",
        {"kind": "frequency", "operator": "eq", "count": 2, "period": "month"},
    )

    outcome = _matcher(llm).match(
        [_rule("freq", "выплата", "не реже двух раз в месяц", FREQ_RULE)], [statement], TEXT
    )

    assert outcome.findings == ()
    assert outcome.pairs[0]["mode"] == EVALUATION_STRUCTURED


def test_text_rule_uses_the_model_verdict_and_is_marked_as_an_estimate() -> None:
    llm = ScriptedLLM(
        {"kind": {"matched_statement_id": 2, "is_violation": True, "recommendation": "Убрать."}}
    )

    outcome = _matcher(llm).match(
        [_rule("kind", "выплата заработной платы", "не допускается выплата в натуральной форме")],
        [FREQ_STATEMENT, KIND_STATEMENT],
        TEXT,
    )

    item = outcome.findings[0]
    assert item.finding.evaluation_mode == EVALUATION_MODEL
    assert item.finding.recommendation == "Убрать."
    assert item.explanation == "Пояснение."


def test_missing_mandatory_condition_is_reported_as_not_stated() -> None:
    llm = ScriptedLLM({"method": {"is_mandatory_condition": True, "is_violation": True}})

    outcome = _matcher(llm).match(
        [_rule("method", "способ выплаты", "указывается способ выплаты")], [FREQ_STATEMENT], TEXT
    )

    finding = outcome.findings[0].finding
    assert finding.evaluation_mode == EVALUATION_MISSING
    assert finding.statement_text is None and finding.start_char is None and finding.quote is None


def test_rule_without_a_statement_is_not_checked_unless_it_is_mandatory() -> None:
    llm = ScriptedLLM({})

    outcome = _matcher(llm).match(
        [_rule("ban", "выплата", "не допускается выплата в натуральной форме")], [], TEXT
    )

    assert outcome.findings == ()
    assert [item["rule_code"] for item in outcome.unchecked] == ["ban"]


def test_rule_whose_condition_does_not_concern_the_document_is_not_applicable() -> None:
    llm = ScriptedLLM({"minor": {"condition_applicable": False, "is_violation": True}})

    outcome = _matcher(llm).match(
        [_rule("minor", "отпуск", "не менее 30 дней", condition="работникам моложе 18 лет")],
        [FREQ_STATEMENT],
        TEXT,
    )

    assert outcome.findings == ()
    assert [item["rule_code"] for item in outcome.inapplicable] == ["minor"]
    assert outcome.unchecked == ()


def test_rules_go_to_the_model_in_batches() -> None:
    llm = ScriptedLLM({})
    rules = [_rule(f"r{index}", "выплата", "текст", rule_id=index) for index in range(5)]

    outcome = _matcher(llm, rules_per_request=2).match(rules, [FREQ_STATEMENT], TEXT)

    assert [len(prompt["rules"]) for prompt in llm.prompts] == [2, 2, 1]
    assert outcome.requests == 3


def test_large_document_sends_only_candidate_statements() -> None:
    llm = ScriptedLLM({})
    statements = [FREQ_STATEMENT, KIND_STATEMENT, _statement("прочее", "Приказ")]

    _matcher(llm, max_statements_in_prompt=1, candidate_threshold=0.99).match(
        [_rule("r", "выплата", "текст")], statements, TEXT
    )

    assert llm.prompts[0]["document_statements"] == []


@pytest.mark.parametrize(
    "verdict",
    [
        {"matched_statement_id": 9},
        {"matched_statement_id": True},
        {"condition_applicable": "yes"},
        {"explanation": " "},
        {"confidence": 2},
    ],
)
def test_untrusted_model_answers_are_rejected(verdict) -> None:
    llm = ScriptedLLM({"r": verdict})

    with pytest.raises(ValueError):
        _matcher(llm).match([_rule("r", "выплата", "текст")], [FREQ_STATEMENT], TEXT)


def test_answer_that_skips_a_rule_is_rejected() -> None:
    class Skipping(ScriptedLLM):
        def generate(self, **kwargs):
            return json.dumps({"schema_version": "4", "analyses": [], "general_summary": ""})

    with pytest.raises(ValueError, match="every rule"):
        _matcher(Skipping({})).match([_rule("r", "выплата", "текст")], [FREQ_STATEMENT], TEXT)


@pytest.fixture
def session_factory():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


def test_audit_stores_the_statement_and_the_matching_summary(session_factory) -> None:
    llm = ScriptedLLM({"freq": {"matched_statement_id": 1, "is_violation": True}})
    statements = [FREQ_STATEMENT]
    with session_factory.begin() as session:
        document = Document(
            title="Order",
            file_type="txt",
            file_path="o.txt",
            raw_text=TEXT,
            confirmed_types=[DocumentType(code="payroll_order", name="Payroll")],
        )
        session.add(document)
        session.add(
            AuditRule(
                rule_code="freq",
                subject="выплата заработной платы",
                constraint_text="не реже двух раз в месяц",
                constraint_json=json.dumps(FREQ_RULE),
                severity="high",
                applicability_scope="universal",
            )
        )
        session.flush()
        document_id = document.id
    persistence = AuditPersistence(
        session_factory,
        engine=AuditEngine(
            entity_extractor=no_entities, statement_extractor=lambda _: tuple(statements)
        ),
        neural_interpreter=LLMInterpreter(FakeLLMProvider()),
        rule_matcher=_matcher(llm),
    )

    report = persistence.audit_document(document_id)

    finding = report.findings[0]
    assert finding.evaluation_mode == EVALUATION_STRUCTURED
    assert finding.statement_text == FREQ_STATEMENT.statement_text
    summary = json.loads(report.summary)
    assert summary["matching"]["requests"] == 1
    assert summary["matching"]["pairs"][0]["statement_id"] is not None
    assert summary["neural"]["analyses"][0]["finding_key"] == finding.finding_key
    assert summary["neural"]["general_summary"] == "Итог."


def test_model_failure_stops_the_audit_without_a_report(session_factory) -> None:
    class Failing(ScriptedLLM):
        def generate(self, **kwargs):
            raise RuntimeError("unavailable")

    with session_factory.begin() as session:
        document = Document(
            title="Order",
            file_type="txt",
            file_path="o.txt",
            raw_text=TEXT,
            confirmed_types=[DocumentType(code="payroll_order", name="Payroll")],
        )
        session.add(document)
        session.add(
            AuditRule(
                rule_code="r",
                subject="s",
                constraint_text="t",
                severity="low",
                applicability_scope="universal",
            )
        )
        session.flush()
        document_id = document.id
    persistence = AuditPersistence(
        session_factory,
        engine=AuditEngine(entity_extractor=no_entities, statement_extractor=lambda _: ()),
        neural_interpreter=LLMInterpreter(FakeLLMProvider()),
        rule_matcher=_matcher(Failing({})),
    )

    with pytest.raises(AuditModelError):
        persistence.audit_document(document_id, None)

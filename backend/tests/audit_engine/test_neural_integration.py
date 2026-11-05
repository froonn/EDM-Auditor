import json

import pytest

from edm_auditor.audit_engine import LLMInterpreter
from edm_auditor.audit_engine.neural_errors import InvalidNeuralResponse
from edm_auditor.audit_engine.neural_models import NeuralFinding


class FakeLLM:
    model_name = "fake-v1"

    def __init__(self, response: str):
        self.response = response

    def generate(self, *, system_prompt, user_prompt, context=()):
        assert "finding_key" in user_prompt
        assert system_prompt
        return self.response


def finding() -> NeuralFinding:
    return NeuralFinding(
        key="leave-short:10:17",
        rule_code="leave-short",
        severity="high",
        description="Leave is below the configured minimum",
        quote="14 days",
    )


def test_interpreter_validates_structured_response() -> None:
    response = json.dumps(
        {
            "schema_version": "1",
            "analyses": [
                {
                    "finding_key": "leave-short:10:17",
                    "explanation": "The quoted term requires review.",
                    "recommendation": "Check the leave duration.",
                    "confidence": 0.8,
                    "legal_basis": [{"legal_act_id": 1, "quote": "Article text"}],
                }
            ],
            "general_summary": "One finding needs review.",
        }
    )

    result = LLMInterpreter(FakeLLM(response)).analyze([finding()])

    assert result.status == "completed"
    assert result.model == "fake-v1"
    assert result.analyses[0].confidence == 0.8


def test_interpreter_calls_provider_when_there_are_no_findings() -> None:
    response = '{"schema_version":"2","analyses":[],"general_summary":"No findings."}'

    result = LLMInterpreter(FakeLLM(response)).analyze([])

    assert result.status == "completed"
    assert result.analyses == ()
    assert result.general_summary == "No findings."


@pytest.mark.parametrize(
    "response, message",
    [
        ("not json", "valid JSON"),
        ('{"analyses":[{"finding_key":"unknown"}]}', "unknown finding"),
        (
            '{"analyses":[{"finding_key":"leave-short:10:17",'
            '"explanation":"x","recommendation":"","confidence":2}]}',
            "between 0 and 1",
        ),
    ],
)
def test_interpreter_rejects_untrusted_responses(response: str, message: str) -> None:
    with pytest.raises(InvalidNeuralResponse, match=message):
        LLMInterpreter(FakeLLM(response)).analyze([finding()])


def _batch_findings(count: int) -> tuple[NeuralFinding, ...]:
    return tuple(
        NeuralFinding(
            key=f"finding-{index}",
            rule_code="rule",
            severity="low",
            description="Описание",
            quote=None,
            context=(),
        )
        for index in range(count)
    )


class _BatchProvider:
    model_name = "batch-llm"

    def __init__(self) -> None:
        self.prompts: list[dict] = []

    def generate(self, *, system_prompt, user_prompt, context=()) -> str:
        prompt = json.loads(user_prompt)
        self.prompts.append(prompt)
        if "batch_summaries" in prompt:
            return json.dumps({"schema_version": "2", "analyses": [], "general_summary": "Итог"})
        return json.dumps(
            {
                "schema_version": "2",
                "analyses": [
                    {
                        "finding_key": item["finding_key"],
                        "explanation": "Пояснение",
                        "recommendation": "",
                        "confidence": 0.5,
                        "is_violation": True,
                    }
                    for item in prompt["findings"]
                ],
                "general_summary": f"Часть {len(self.prompts)}",
            }
        )


def test_interpreter_explains_every_finding_in_batches() -> None:
    provider = _BatchProvider()

    result = LLMInterpreter(provider, batch_size=10).analyze(_batch_findings(25))

    assert len(result.analyses) == 25
    assert [len(item["findings"]) for item in provider.prompts[:3]] == [10, 10, 5]
    assert provider.prompts[3]["batch_summaries"] == ["Часть 1", "Часть 2", "Часть 3"]
    assert result.general_summary == "Итог"


def test_single_batch_needs_no_summary_request() -> None:
    provider = _BatchProvider()

    result = LLMInterpreter(provider, batch_size=10).analyze(_batch_findings(10))

    assert len(provider.prompts) == 1
    assert result.general_summary == "Часть 1"


def test_no_findings_still_make_one_request() -> None:
    provider = _BatchProvider()

    result = LLMInterpreter(provider).analyze(())

    assert len(provider.prompts) == 1
    assert result.analyses == ()


def test_failure_in_any_batch_fails_the_analysis() -> None:
    class FailsLater(_BatchProvider):
        def generate(self, *, system_prompt, user_prompt, context=()) -> str:
            if self.prompts:
                raise RuntimeError("model unavailable")
            return super().generate(
                system_prompt=system_prompt, user_prompt=user_prompt, context=context
            )

    with pytest.raises(RuntimeError):
        LLMInterpreter(FailsLater(), batch_size=10).analyze(_batch_findings(11))


def _candidate() -> NeuralFinding:
    return NeuralFinding(
        key="report:1:2",
        rule_code="report",
        severity="high",
        description="Отчёт не позднее 3 дней",
        quote="20 дней",
        norm_quote="Отчёт не позднее 3 дней",
        surrounding_text="Командировка на 20 дней.",
        requires_confirmation=True,
    )


def _answer(**values) -> str:
    return json.dumps(
        {
            "analyses": [
                {
                    "finding_key": "report:1:2",
                    "explanation": "Значение относится к сроку командировки.",
                    "recommendation": "",
                    "confidence": 0.9,
                    **values,
                }
            ],
            "general_summary": "Итог.",
        }
    )


def test_model_can_reject_a_candidate() -> None:
    result = LLMInterpreter(FakeLLM(_answer(is_violation=False))).analyze([_candidate()])

    assert result.analyses[0].is_violation is False


def test_candidate_without_a_verdict_is_an_error() -> None:
    with pytest.raises(InvalidNeuralResponse, match="is_violation"):
        LLMInterpreter(FakeLLM(_answer())).analyze([_candidate()])


def test_candidate_left_out_of_the_answer_is_an_error() -> None:
    empty = '{"analyses":[],"general_summary":"Итог."}'

    with pytest.raises(InvalidNeuralResponse, match="every candidate"):
        LLMInterpreter(FakeLLM(empty)).analyze([_candidate()])


def test_model_cannot_reject_a_finding_that_needs_no_confirmation() -> None:
    plain = NeuralFinding(
        key="report:1:2", rule_code="report", severity="high", description="d", quote="q"
    )

    result = LLMInterpreter(FakeLLM(_answer(is_violation=False))).analyze([plain])

    assert result.analyses[0].is_violation is True


def test_prompt_carries_the_context_language_and_the_norm() -> None:
    provider = _BatchProvider()
    finding = _candidate()

    LLMInterpreter(provider).analyze([finding], output_language="en")

    prompt = provider.prompts[0]
    assert prompt["output_language"] == "en"
    assert prompt["findings"][0]["surrounding_text"] == "Командировка на 20 дней."
    assert prompt["findings"][0]["norm_quote"] == "Отчёт не позднее 3 дней"
    assert prompt["findings"][0]["requires_confirmation"] is True

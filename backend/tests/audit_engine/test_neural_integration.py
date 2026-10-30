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

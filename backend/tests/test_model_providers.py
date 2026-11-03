from io import BytesIO
from urllib.error import HTTPError

import pytest

from edm_auditor.model_config import ModelConfig
from edm_auditor.model_providers import (
    GoogleAIStudioRuleExtractionProvider,
    OpenAICompatibleEntityExtractionProvider,
    OpenAICompatibleLLMProvider,
    OpenAICompatibleRuleExtractionProvider,
    RULE_EXTRACTION_SCHEMA,
    _google_generation_config,
    _google_schema,
    _post_json,
)


class _GoogleResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _GoogleModels:
    def __init__(self, response: _GoogleResponse) -> None:
        self.response = response
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _GoogleClient:
    def __init__(self, response: _GoogleResponse) -> None:
        self.models = _GoogleModels(response)


def test_llm_requests_json_schema_when_configured(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(config, endpoint, payload, timeout):
        captured.update(payload)
        return {"choices": [{"message": {"content": '{"analyses":[]}'}}]}

    monkeypatch.setattr("edm_auditor.model_providers._post_json", fake_post)
    provider = OpenAICompatibleLLMProvider(
        ModelConfig(
            provider="openai-compatible",
            model="google/gemma-4-e4b",
            base_url="http://localhost:1234/v1",
            structured_output="json_schema",
        )
    )

    provider.generate(system_prompt="Return JSON", user_prompt="Analyze")

    response_format = captured["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "audit_analysis"


def test_openai_request_retries_rate_limit_with_backoff(monkeypatch) -> None:
    attempts = 0
    sleeps = []

    def fake_urlopen(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(
                "https://example.test",
                429,
                "rate limited",
                {},
                BytesIO(b"try again"),
            )
        return _ResponseContext({"ok": True})

    class _ResponseContext:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return BytesIO(b'{"ok": true}')

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("edm_auditor.model_providers.request.urlopen", fake_urlopen)
    monkeypatch.setattr("edm_auditor.model_providers.time.sleep", sleeps.append)
    result = _post_json(
        ModelConfig(
            provider="openai-compatible",
            model="test",
            base_url="https://example.test",
            retry_attempts=2,
            retry_backoff_factor=0.25,
        ),
        "chat/completions",
        {},
        1,
    )

    assert result == {"ok": True}
    assert attempts == 2
    assert sleeps == [0.25]


def test_openai_request_reports_exhausted_rate_limit(monkeypatch) -> None:
    def fake_urlopen(*args, **kwargs):
        raise HTTPError(
            "https://example.test",
            429,
            "rate limited",
            {},
            BytesIO(b"try again"),
        )

    monkeypatch.setattr("edm_auditor.model_providers.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        _post_json(
            ModelConfig(
                provider="openai-compatible",
                model="test",
                base_url="https://example.test",
                retry_attempts=1,
                retry_backoff_factor=0,
            ),
            "chat/completions",
            {},
            1,
        )


def test_llm_requests_json_object_when_configured(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(config, endpoint, payload, timeout):
        captured.update(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr("edm_auditor.model_providers._post_json", fake_post)
    provider = OpenAICompatibleLLMProvider(
        ModelConfig(
            provider="openai-compatible",
            model="test",
            base_url="http://localhost:1234/v1",
            structured_output="json_object",
        )
    )

    provider.generate(system_prompt="Return JSON", user_prompt="Analyze")

    assert captured["response_format"] == {"type": "json_object"}


def test_entity_extractor_requests_json_schema_when_configured(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(config, endpoint, payload, timeout):
        captured.update(payload)
        return {
            "choices": [
                {"message": {"content": '{"entities":[{"kind":"duration","value":"14 календарных дней"}]}'}}
            ]
        }

    monkeypatch.setattr("edm_auditor.model_providers._post_json", fake_post)
    provider = OpenAICompatibleEntityExtractionProvider(
        ModelConfig(
            provider="openai-compatible",
            model="google/gemma-4-e4b",
            base_url="http://localhost:1234/v1",
            api_key_env="LM_STUDIO_API_KEY",
            structured_output="json_schema",
        )
    )

    assert provider.extract("Отпуск 14 календарных дней.") == (
        {"kind": "duration", "value": "14 календарных дней"},
    )
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["name"] == "entity_extraction"


def test_rule_extractor_requests_json_schema_when_configured(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(config, endpoint, payload, timeout):
        captured.update(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"rules":[{"rule_code":"leave-minimum",'
                            '"name":"Minimum leave","description":"At least 24 days",'
                            '"severity":"high","check_type":"duration",'
                            '"parameters":{"min_days":24}}]}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("edm_auditor.model_providers._post_json", fake_post)
    provider = OpenAICompatibleRuleExtractionProvider(
        ModelConfig(
            provider="openai-compatible",
            model="google/gemma-4-e4b",
            base_url="http://localhost:1234/v1",
            structured_output="json_schema",
        )
    )

    rules = provider.extract_rules(
        "Отпуск не менее 24 дней.",
        source_language="ru",
        source_location="legal-act-7:chunk-0",
    )

    assert rules[0]["check_type"] == "duration"
    assert captured["response_format"]["json_schema"]["name"] == "rule_extraction"
    prompt = captured["messages"][0]["content"]
    assert '"min_days"' in prompt
    assert "Never use generic parameters" in prompt
    assert "source_language=ru" in prompt
    assert "source_location=legal-act-7:chunk-0" in prompt
    assert "source_quote" in prompt


def test_google_schema_omits_openai_only_additional_properties() -> None:
    config = ModelConfig(
        provider="google-ai-studio",
        model="gemma-4-31b-it",
        structured_output="json_schema",
    )

    generation = _google_generation_config(
        config,
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "value": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                    },
                }
            },
        },
    )

    assert "additionalProperties" not in generation.response_schema
    assert (
        "additionalProperties"
        not in generation.response_schema["properties"]["value"]["items"]
    )


def test_google_rule_schema_describes_parameters_properties() -> None:
    schema = _google_schema(RULE_EXTRACTION_SCHEMA)
    parameters = schema["properties"]["rules"]["items"]["properties"]["parameters"]

    assert parameters["type"] == "object"
    assert "min_days" in parameters["properties"]
    assert "keywords" in parameters["properties"]
    assert "additionalProperties" not in parameters


def test_google_rule_extractor_accepts_root_array_response() -> None:
    client = _GoogleClient(
        _GoogleResponse(
            '[{"rule_code":"leave-minimum","name":"Minimum leave",'
            '"description":"At least 24 days","severity":"high",'
            '"check_type":"duration","parameters":{"min_days":24}}]'
        )
    )
    provider = GoogleAIStudioRuleExtractionProvider(
        ModelConfig(
            provider="google-ai-studio",
            model="gemma-4-31b-it",
            structured_output="json_schema",
        ),
        client=client,
    )

    rules = provider.extract_rules("Отпуск не менее 24 дней.")

    assert len(rules) == 1
    assert rules[0]["rule_code"] == "leave-minimum"

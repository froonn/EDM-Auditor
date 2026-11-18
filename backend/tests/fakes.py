"""Test doubles for model providers; production code has no offline substitutes."""

from collections.abc import Sequence
from hashlib import sha256
import json
from math import sqrt
import re


class DeterministicEmbeddingProvider:
    """Small hash-based embedding provider that needs no network."""

    def __init__(self, *, dimension: int = 32, model_name: str = "deterministic-v1") -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension
        self.model_name = model_name

    def _embed(self, text: str) -> tuple[float, ...]:
        values = [0.0] * self.dimension
        tokens = re.findall(r"\w+", text.casefold())
        for token in tokens or [text]:
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            values[index] += 1.0
        norm = sqrt(sum(value * value for value in values))
        return tuple(value / norm for value in values) if norm else tuple(values)

    def embed_documents(self, texts: Sequence[str]) -> Sequence[tuple[float, ...]]:
        return tuple(self._embed(text) for text in texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._embed(text)


def _match_rule(rule: dict) -> dict:
    """Pick the candidate the code can compare, else the closest one; leave the verdict to code."""
    candidates = rule.get("candidates", [])
    comparable = [item for item in candidates if item.get("structured_comparison") is not None]
    chosen = max(comparable or candidates, key=lambda item: item["similarity"], default=None)
    return {
        "finding_key": rule["finding_key"],
        "matched_statement_id": chosen["statement_id"] if chosen else None,
        "condition_applicable": True,
        "is_mandatory_condition": False,
        "is_violation": False,
        "explanation": "Пояснение.",
        "recommendation": "",
        "confidence": 0.9,
    }


class BiasedEmbeddingProvider(DeterministicEmbeddingProvider):
    """Keep the ordering of the hash embedding but raise every similarity above the threshold."""

    def _embed(self, text: str) -> tuple[float, ...]:
        base = super()._embed(text)
        values = [value + 3.0 / sqrt(self.dimension) for value in base]
        norm = sqrt(sum(value * value for value in values))
        return tuple(value / norm for value in values)


class FakeLLMProvider:
    """Record prompts, match each rule to its best candidate, and confirm every finding."""

    model_name = "fake-llm"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, system_prompt, user_prompt, context=(), response_schema=None) -> str:
        self.prompts.append(user_prompt)
        prompt = json.loads(user_prompt)
        if "rules" in prompt:
            return json.dumps(
                {
                    "schema_version": "4",
                    "analyses": [_match_rule(rule) for rule in prompt["rules"]],
                    "general_summary": "Reviewed.",
                }
            )
        return json.dumps(
            {
                "schema_version": "3",
                "analyses": [
                    {
                        "finding_key": item["finding_key"],
                        "explanation": "Подтверждено.",
                        "recommendation": "",
                        "confidence": 0.9,
                        "is_violation": True,
                    }
                    for item in prompt.get("findings", [])
                ],
                "general_summary": "Reviewed.",
            }
        )


class FailingLLMProvider:
    model_name = "failing-llm"

    def generate(self, *, system_prompt, user_prompt, context=(), response_schema=None) -> str:
        raise RuntimeError("llm unavailable")


_AMOUNT = re.compile(
    r"(\d+)\s*(календарных дней|календарных дня|рабочих дней|дней|дня|days|месяцев|месяца|месяц|рублей|BYN|процентов|%)",
    re.IGNORECASE,
)
_UNITS = {
    "дн": ("day", 1),
    "day": ("day", 1),
    "мес": ("day", 30),
    "руб": ("byn", 1),
    "byn": ("byn", 1),
    "про": ("%", 1),
    "%": ("%", 1),
}


class FakeStatementProvider:
    """Extract one statement for each amount with a unit; the quote is the amount itself."""

    model_name = "fake-statement-extractor"

    def extract_statements(self, chunk: str, *, source_language: str = "auto"):
        statements = []
        for match in _AMOUNT.finditer(chunk):
            unit_info = next(
                (spec for prefix, spec in _UNITS.items() if match.group(2).casefold().startswith(prefix)),
                None,
            )
            sentence = next(
                (
                    part.strip()
                    for part in re.split(r"(?<=[.!?])\s+", chunk)
                    if match.group(0) in part
                ),
                match.group(0),
            )
            statements.append(
                {
                    "subject": sentence,
                    "statement_text": sentence,
                    "constraint_json": (
                        {
                            "kind": "value",
                            "operator": "eq",
                            "value": int(match.group(1)) * unit_info[1],
                            "unit": unit_info[0],
                        }
                        if unit_info
                        else None
                    ),
                    "source_quote": match.group(0),
                }
            )
        return tuple(statements)


class FailingEntityProvider:
    model_name = "failing-extractor"

    def extract(self, text: str) -> Sequence[dict[str, str]]:
        raise RuntimeError("extractor unavailable")

    def extract_statements(self, chunk: str, *, source_language: str = "auto"):
        raise RuntimeError("extractor unavailable")


class FakeRuleExtractor:
    model_name = "fake-extractor"

    def extract_rules(self, text: str, *, source_language: str, source_location: str, **_):
        return ()


class FakeClassificationProvider:
    """Answer from the document heading, as a model that recognizes the example documents."""

    model_name = "fake-classifier"
    TERMS = {
        "business_trip_order": ("командировк",),
        "remote_work_agreement": ("дистанционн", "удаленн"),
        "payroll_order": ("заработной плат", "оплате труда"),
        "vacation_order": ("об отпуске", "предоставлении отпуска"),
        "employment_contract": ("трудовой договор", "трудовой контракт"),
    }

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def classify(self, text: str, *, title, filename, document_types):
        self.requests.append(
            {"text": text, "title": title, "filename": filename, "document_types": document_types}
        )
        heading = text.strip().partition("\n")[0].casefold()
        matched = [
            item.code
            for item in document_types
            if item.name.casefold() in heading
            or any(term in heading for term in self.TERMS.get(item.code, ()))
        ]
        return {
            "document_types": [{"code": code, "confidence": 0.95} for code in matched],
            "suggested_type_name": "",
            "suggested_type_reason": "",
        }


class FailingClassificationProvider:
    model_name = "failing-classifier"

    def classify(self, text: str, *, title, filename, document_types):
        raise RuntimeError("classifier unavailable")


def patch_fake_providers(monkeypatch, **overrides) -> None:
    """Patch all model provider factories in edm_auditor.api.app with test doubles."""
    monkeypatch.setenv("EDM_MODEL_PRESET", "lm-studio")
    defaults = {
        "create_llm_provider": FakeLLMProvider,
        "create_document_classification_provider": FakeClassificationProvider,
        "create_entity_extraction_provider": FakeStatementProvider,
        "create_rule_extraction_provider": FakeRuleExtractor,
        "create_embedding_provider": BiasedEmbeddingProvider,
    }
    defaults.update(overrides)
    for factory, provider in defaults.items():
        monkeypatch.setattr(
            f"edm_auditor.api.app.{factory}",
            lambda config, provider=provider: provider(),
        )

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


class FakeLLMProvider:
    """Record prompts and confirm every finding."""

    model_name = "fake-llm"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, system_prompt, user_prompt, context=()) -> str:
        self.prompts.append(user_prompt)
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
                    for item in json.loads(user_prompt).get("findings", [])
                ],
                "general_summary": "Reviewed.",
            }
        )


class FailingLLMProvider:
    model_name = "failing-llm"

    def generate(self, *, system_prompt, user_prompt, context=()) -> str:
        raise RuntimeError("llm unavailable")


class FakeEntityProvider:
    model_name = "fake-extractor"

    def extract(self, text: str) -> Sequence[dict[str, str]]:
        return ()


class FailingEntityProvider:
    model_name = "failing-extractor"

    def extract(self, text: str) -> Sequence[dict[str, str]]:
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


def no_entities(_: str) -> tuple:
    """Entity extractor for tests that exercise only the deterministic entities."""
    return ()

"""Test doubles for model providers; production code has no offline substitutes."""

from collections.abc import Sequence
from hashlib import sha256
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
    """Record prompts and return a valid analysis without any findings."""

    model_name = "fake-llm"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, system_prompt, user_prompt, context=()) -> str:
        self.prompts.append(user_prompt)
        return '{"schema_version":"2","analyses":[],"general_summary":"Reviewed."}'


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

    def extract_rules(self, text: str, *, source_language: str, source_location: str):
        return ()


def no_entities(_: str) -> tuple:
    """Entity extractor for tests that exercise only the deterministic entities."""
    return ()

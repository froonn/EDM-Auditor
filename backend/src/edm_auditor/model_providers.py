"""Provider implementations for configured embeddings and LLM calls."""

from collections.abc import Sequence
import json
from typing import Protocol
from urllib import error, request

from .model_config import ModelConfig
from .rag.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    Vector,
    validate_vectors,
)
from .rag.exceptions import EmbeddingError


class LLMProvider(Protocol):
    """Provider used to generate a structured audit explanation."""

    model_name: str

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context: Sequence[str] = (),
    ) -> str:
        """Return the model response text."""


class StubLLMProvider:
    """Offline provider that makes accidental network calls impossible."""

    model_name = "stub-v1"

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context: Sequence[str] = (),
    ) -> str:
        del system_prompt, user_prompt, context
        return '{"status":"not_configured","explanation":"LLM provider is not configured"}'


class OpenAICompatibleEmbeddingProvider:
    """Embedding adapter for LM Studio, OpenRouter, and compatible APIs."""

    def __init__(self, config: ModelConfig, *, timeout: float = 30.0) -> None:
        if not config.base_url:
            raise ValueError("base_url is required for an OpenAI-compatible provider")
        if not config.dimension:
            raise ValueError("dimension is required for an embedding provider")
        self.model_name = config.model
        self.dimension = config.dimension
        self._config = config
        self._timeout = timeout

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        if not texts:
            return ()
        payload = self._request("embeddings", {"model": self.model_name, "input": list(texts)})
        try:
            vectors = tuple(
                tuple(float(value) for value in item["embedding"])
                for item in sorted(payload["data"], key=lambda item: item["index"])
            )
        except (KeyError, TypeError, ValueError) as error:
            raise EmbeddingError("embedding provider returned an invalid response") from error
        validate_vectors(vectors, len(texts), self.dimension)
        return vectors

    def embed_query(self, text: str) -> Vector:
        return self.embed_documents([text])[0]

    def _request(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        return _post_json(self._config, endpoint, payload, self._timeout)


class OpenAICompatibleLLMProvider:
    """Chat-completions adapter for LM Studio, OpenRouter, and compatible APIs."""

    def __init__(self, config: ModelConfig, *, timeout: float = 60.0) -> None:
        if not config.base_url:
            raise ValueError("base_url is required for an OpenAI-compatible provider")
        self.model_name = config.model
        self._config = config
        self._timeout = timeout

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context: Sequence[str] = (),
    ) -> str:
        prompt = user_prompt
        if context:
            prompt = f"{user_prompt}\n\nContext:\n" + "\n\n".join(context)
        payload = self._request(
            "chat/completions",
            {
                "model": self.model_name,
                "temperature": self._config.temperature,
                "max_tokens": self._config.max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("LLM provider returned an invalid response") from error
        if not isinstance(content, str):
            raise ValueError("LLM provider returned non-text content")
        return content

    def _request(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        return _post_json(self._config, endpoint, payload, self._timeout)


def create_embedding_provider(config: ModelConfig) -> EmbeddingProvider:
    """Create an embedding provider from a resolved model config."""
    if config.provider == "deterministic":
        return DeterministicEmbeddingProvider(
            dimension=config.dimension or 32,
            model_name=config.model,
        )
    if config.provider == "openai-compatible":
        return OpenAICompatibleEmbeddingProvider(config)
    raise ValueError(f"unsupported embedding provider: {config.provider}")


def create_llm_provider(config: ModelConfig) -> LLMProvider:
    """Create an LLM provider from a resolved model config."""
    if config.provider == "stub":
        return StubLLMProvider()
    if config.provider == "openai-compatible":
        return OpenAICompatibleLLMProvider(config)
    raise ValueError(f"unsupported LLM provider: {config.provider}")


def _post_json(
    config: ModelConfig,
    endpoint: str,
    payload: dict[str, object],
    timeout: float,
) -> dict[str, object]:
    base_url = config.base_url.rstrip("/")
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = config.api_key()
    if api_key:
        headers["Authorization"] = "Bear" + "er " + api_key
    elif config.api_key_env:
        raise ValueError(f"environment variable {config.api_key_env} is not set")
    try:
        with request.urlopen(
            request.Request(f"{base_url}/{endpoint}", data=body, headers=headers, method="POST"),
            timeout=timeout,
        ) as response:
            result = json.load(response)
    except (error.HTTPError, error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"model provider request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError("model provider returned a non-object response")
    return result

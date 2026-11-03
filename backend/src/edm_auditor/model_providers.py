"""Provider implementations for configured embeddings and LLM calls."""

from collections.abc import Sequence
import json
import logging
import re
import time
from typing import Protocol
from urllib import error, request

logger = logging.getLogger(__name__)
trace_logger = logging.getLogger("edm_auditor.trace")

from .model_config import ModelConfig
from .rag.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    Vector,
    validate_vectors,
)
from .rag.exceptions import EmbeddingError


NEURAL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "analyses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_key": {"type": "string"},
                    "explanation": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "legal_basis": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "legal_act_id": {"type": "integer"},
                                "quote": {"type": "string"},
                            },
                            "required": ["legal_act_id", "quote"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "finding_key",
                    "explanation",
                    "recommendation",
                    "confidence",
                    "legal_basis",
                ],
                "additionalProperties": False,
            },
        },
        "general_summary": {"type": "string"},
    },
    "required": ["schema_version", "analyses", "general_summary"],
    "additionalProperties": False,
}

ENTITY_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["duration", "date", "money", "percent", "number"],
                    },
                    "value": {"type": "string"},
                },
                "required": ["kind", "value"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entities"],
    "additionalProperties": False,
}

RULE_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_code": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "check_type": {
                        "type": "string",
                        "enum": ["keyword", "regex", "numeric", "date", "duration", "semantic"],
                    },
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "min_days": {"type": "integer"},
                            "max_days": {"type": "integer"},
                            "entity": {
                                "type": "string",
                                "enum": ["number", "duration", "percent", "money"],
                            },
                            "min": {"type": "number"},
                            "max": {"type": "number"},
                            "before": {"type": "string"},
                            "after": {"type": "string"},
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["forbidden", "required"],
                            },
                            "match": {
                                "type": "string",
                                "enum": ["literal", "stem", "regex"],
                            },
                            "pattern": {"type": "string"},
                            "query": {"type": "string"},
                            "k": {"type": "integer"},
                            "threshold": {"type": "number"},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "rule_code",
                    "name",
                    "description",
                    "severity",
                    "check_type",
                    "parameters",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rules"],
    "additionalProperties": False,
}


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


class EntityExtractionProvider(Protocol):
    """Provider used to extract normalized entities from document text."""

    model_name: str

    def extract(self, text: str) -> Sequence[dict[str, str]]:
        """Return entity kinds and verbatim values found in the text."""


class RuleExtractionProvider(Protocol):
    """Provider used to derive auditable rules from normative text."""

    model_name: str

    def extract_rules(self, text: str) -> Sequence[dict[str, object]]:
        """Return structured rules explicitly supported by the source text."""


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
        return (
            '{"schema_version":"1","analyses":[],"general_summary":'
            '"LLM analysis is disabled in the offline provider"}'
        )


class StubRuleExtractionProvider:
    """Deterministic rule extractor from normative legal text for offline/fallback use."""

    model_name = "stub-v1"

    def extract_rules(self, text: str) -> Sequence[dict[str, object]]:
        rules: list[dict[str, object]] = []
        normalized_text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+|\n+", normalized_text)
            if s.strip()
        ]
        rule_idx = 1
        for sentence in sentences:
            # 1. Check for duration rules
            duration_match = re.search(
                r"\b(не\s+позднее|не\s+менее|не\s+более|не\s+может\s+превышать|в\s+течение)\s+"
                r"(\d+(?:[.,]\d+)?)\s*(?:[а-я-]+\s+)*(дн(?:я|ей)?|месяц(?:а|ев)?|лет?|год(?:а|ов)?)\b",
                sentence,
                re.IGNORECASE,
            )
            if duration_match:
                prefix = duration_match.group(1).lower()
                val = float(duration_match.group(2).replace(",", "."))
                unit = duration_match.group(3).lower()
                days = val
                if unit.startswith("месяц"):
                    days = val * 30
                elif unit.startswith(("год", "лет")):
                    days = val * 365

                params: dict[str, object] = {}
                if any(w in prefix for w in ("более", "превышать", "течение")):
                    params["max_days"] = int(days)
                else:
                    params["min_days"] = int(days)

                rules.append({
                    "rule_code": f"rule-duration-{rule_idx}",
                    "name": sentence[:100],
                    "description": sentence,
                    "severity": "critical",
                    "check_type": "duration",
                    "parameters": params,
                })
                rule_idx += 1
                continue

            # 2. Check for numeric money rules
            money_match = re.search(
                r"\b(не\s+может\s+быть\s+меньше|не\s+менее|не\s+меньше|не\s+более|не\s+больше)\s+"
                r"(\d+(?:[.,]\d+)?)\s*(руб(?:лей|ля)?|BYN|р\.)\b",
                sentence,
                re.IGNORECASE,
            )
            if money_match:
                prefix = money_match.group(1).lower()
                val = float(money_match.group(2).replace(",", "."))
                params_m: dict[str, object] = {"entity": "money"}
                if "более" in prefix or "больше" in prefix:
                    params_m["max"] = val
                else:
                    params_m["min"] = val
                rules.append({
                    "rule_code": f"rule-numeric-{rule_idx}",
                    "name": sentence[:100],
                    "description": sentence,
                    "severity": "critical",
                    "check_type": "numeric",
                    "parameters": params_m,
                })
                rule_idx += 1
                continue

            # 3. Check for numeric percent rules
            percent_match = re.search(
                r"\b(не\s+менее|не\s+меньше|не\s+более|не\s+больше)\s+"
                r"(\d+(?:[.,]\d+)?)\s*(?:процент(?:а|ов)?|%)\b",
                sentence,
                re.IGNORECASE,
            )
            if percent_match:
                prefix = percent_match.group(1).lower()
                val = float(percent_match.group(2).replace(",", "."))
                params_p: dict[str, object] = {"entity": "percent"}
                if "более" in prefix or "больше" in prefix:
                    params_p["max"] = val
                else:
                    params_p["min"] = val
                rules.append({
                    "rule_code": f"rule-numeric-{rule_idx}",
                    "name": sentence[:100],
                    "description": sentence,
                    "severity": "critical",
                    "check_type": "numeric",
                    "parameters": params_p,
                })
                rule_idx += 1
                continue

            # 4. Check for keyword rules
            kw_match = re.search(
                r"должен\s+содержать\s+(?:слово\s+)?[«\"']([^»\"']+)[»\"']",
                sentence,
                re.IGNORECASE,
            )
            if kw_match:
                kw = kw_match.group(1).strip()
                rules.append({
                    "rule_code": f"rule-keyword-{rule_idx}",
                    "name": sentence[:100],
                    "description": sentence,
                    "severity": "medium",
                    "check_type": "keyword",
                    "parameters": {"keywords": [kw], "mode": "required", "match": "stem"},
                })
                rule_idx += 1
                continue

        return tuple(rules)


class StubEntityExtractionProvider:
    """Offline entity extractor that performs no external model call."""

    model_name = "stub-v1"

    def extract(self, text: str) -> Sequence[dict[str, str]]:
        del text
        return ()


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
        request_payload: dict[str, object] = {
            "model": self.model_name,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        if self._config.structured_output == "json_object":
            request_payload["response_format"] = {"type": "json_object"}
        elif self._config.structured_output == "json_schema":
            request_payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "audit_analysis",
                    "strict": True,
                    "schema": NEURAL_RESPONSE_SCHEMA,
                },
            }
        payload = self._request("chat/completions", request_payload)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("LLM provider returned an invalid response") from error
        if not isinstance(content, str):
            raise ValueError("LLM provider returned non-text content")
        return content

    def _request(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        return _post_json(self._config, endpoint, payload, self._timeout)


class OpenAICompatibleEntityExtractionProvider:
    """NuExtract-compatible structured extraction adapter."""

    def __init__(self, config: ModelConfig, *, timeout: float = 60.0) -> None:
        if not config.base_url:
            raise ValueError("base_url is required for an entity extraction provider")
        self.model_name = config.model
        self._config = config
        self._timeout = timeout

    def extract(self, text: str) -> Sequence[dict[str, str]]:
        template = {
            "entities": [
                {
                    "kind": ["duration", "date", "money", "percent", "number"],
                    "value": "verbatim-string",
                }
            ]
        }
        prompt = (
            "Extract every date, duration, money amount, percentage, and standalone "
            "number from the document. Preserve each value exactly as written, "
            "including words between a number and its unit. Return only JSON.\n"
            f"Template:\n{json.dumps(template, ensure_ascii=False)}\n"
            f"Document:\n{text}"
        )
        payload = _post_json(
            self._config,
            "chat/completions",
            {
                "model": self.model_name,
                "temperature": self._config.temperature,
                "max_tokens": self._config.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                **(
                    {
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "entity_extraction",
                                "strict": True,
                                "schema": ENTITY_EXTRACTION_SCHEMA,
                            },
                        }
                    }
                    if self._config.structured_output == "json_schema"
                    else (
                        {"response_format": {"type": "json_object"}}
                        if self._config.structured_output == "json_object"
                        else {}
                    )
                ),
            },
            self._timeout,
        )
        try:
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError
            parsed = json.loads(content.strip().strip("`").removeprefix("json").strip())
            entities = parsed["entities"]
            if not isinstance(entities, list):
                raise ValueError
            return tuple(
                {"kind": item["kind"], "value": item["value"]}
                for item in entities
                if isinstance(item, dict)
                and isinstance(item.get("kind"), str)
                and isinstance(item.get("value"), str)
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("entity extraction provider returned invalid JSON") from error


class OpenAICompatibleRuleExtractionProvider:
    """Structured rule extraction adapter for OpenAI-compatible models."""

    def __init__(self, config: ModelConfig, *, timeout: float = 90.0) -> None:
        if not config.base_url:
            raise ValueError("base_url is required for a rule extraction provider")
        self.model_name = config.model
        self._config = config
        self._timeout = timeout

    def extract_rules(self, text: str) -> Sequence[dict[str, object]]:
        prompt = (
            "Extract only explicit, auditable, mandatory requirements from this legal "
            "act. Do not infer, summarize, or invent requirements. Every rule must be "
            "directly traceable to the source text. Return an empty rules array when "
            "no safe rule can be created.\n\n"
            "The check_type and parameters must match these exact validator contracts:\n"
            '- duration: parameters must contain "min_days" and/or "max_days" as '
            "numbers. Use this for requirements such as 'at least 24 calendar days'.\n"
            '- numeric: parameters must contain "entity" with one of "number", '
            '"duration", "money", or "percent", and "min" and/or "max" as numbers.\n'
            '- date: parameters must contain "before" and/or "after" as ISO dates '
            "(YYYY-MM-DD).\n"
            '- keyword: parameters must contain a non-empty "keywords" array of '
            "strings. Use mode \"required\" when the document must contain the "
            "keyword; use mode \"forbidden\" for prohibited wording. Use match "
            "\"stem\" for inflected word forms.\n"
            '- regex: parameters must contain a non-empty "pattern" string. Use '
            "this only when an exact regular-expression requirement is stated.\n"
            '- semantic: parameters must contain the semantic rule configuration '
            "supported by the audit engine.\n\n"
            "Never use generic parameters such as field, operator, unit, or value. "
            "For example, convert 'vacation must be at least 24 calendar days' to "
            'check_type "duration" with {"min_days": 24}, not to a numeric rule '
            'with {"field": "...", "operator": ">=", "unit": "...", "value": 24}. '
            "Return only JSON.\nDocument:\n"
            f"{text}"
        )
        response_format: dict[str, object] = {}
        if self._config.structured_output == "json_schema":
            response_format = {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "rule_extraction",
                        "strict": True,
                        "schema": RULE_EXTRACTION_SCHEMA,
                    },
                }
            }
        elif self._config.structured_output == "json_object":
            response_format = {"response_format": {"type": "json_object"}}
        payload = _post_json(
            self._config,
            "chat/completions",
            {
                "model": self.model_name,
                "temperature": self._config.temperature,
                "max_tokens": self._config.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                **response_format,
            },
            self._timeout,
        )
        try:
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError
            parsed = json.loads(content.strip().strip("`").removeprefix("json").strip())
            rules = parsed["rules"]
            if not isinstance(rules, list):
                raise ValueError
            return tuple(item for item in rules if isinstance(item, dict))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("rule extraction provider returned invalid JSON") from error


class GoogleAIStudioLLMProvider:
    """Google AI Studio provider using the official google-genai SDK."""

    def __init__(self, config: ModelConfig, *, client=None) -> None:
        self.model_name = config.model
        self._config = config
        self._client = client or _google_client(config)

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
        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=_google_generation_config(
                    self._config,
                    system_instruction=system_prompt,
                    schema=(
                        NEURAL_RESPONSE_SCHEMA
                        if self._config.structured_output == "json_schema"
                        else None
                    ),
                ),
            )
            return _google_response_text(response)
        except Exception as exc:
            logger.warning(
                "Google AI Studio generation failed (%s); using offline stub", exc
            )
            return StubLLMProvider().generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context=context,
            )


class GoogleAIStudioEntityExtractionProvider:
    """Google AI Studio structured entity extraction provider."""

    def __init__(self, config: ModelConfig, *, client=None) -> None:
        self.model_name = config.model
        self._config = config
        self._client = client or _google_client(config)

    def extract(self, text: str) -> Sequence[dict[str, str]]:
        logger.info(
            "Calling Google AI Studio entity extraction (model: %s, text length: %d)",
            self.model_name,
            len(text),
        )
        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=(
                    "Extract every date, duration, money amount, percentage, and "
                    "standalone number. Preserve values verbatim and return only JSON.\n"
                    f"Document:\n{text}"
                ),
                config=_google_generation_config(self._config, schema=ENTITY_EXTRACTION_SCHEMA),
            )
            raw_text = getattr(response, "text", "")
            trace_logger.info(
                "Google AI Studio entity extraction response length: %d",
                len(raw_text),
            )
            payload = _parse_json_response(response)
            entities = payload.get("entities")
            if not isinstance(entities, list):
                raise ValueError("entity extraction provider returned invalid JSON")
            result = tuple(
                {"kind": item["kind"], "value": item["value"]}
                for item in entities
                if isinstance(item, dict)
                and isinstance(item.get("kind"), str)
                and isinstance(item.get("value"), str)
            )
            logger.info("Google AI Studio successfully extracted %d entities", len(result))
            return result
        except Exception as exc:
            logger.warning(
                "Google AI Studio entity extraction failed (%s); using deterministic extraction",
                exc,
            )
            from .audit_engine.extractors import extract_entities
            deterministic = extract_entities(text)
            logger.info("Deterministic entity extraction fallback produced %d entities", len(deterministic))
            return tuple({"kind": entity.kind, "value": entity.value} for entity in deterministic)


class GoogleAIStudioRuleExtractionProvider:
    """Google AI Studio structured legal-act rule extraction provider."""

    def __init__(self, config: ModelConfig, *, client=None) -> None:
        self.model_name = config.model
        self._config = config
        self._client = client or _google_client(config)

    def extract_rules(self, text: str) -> Sequence[dict[str, object]]:
        prompt = (
            "Extract only explicit, mandatory, auditable requirements from this "
            "legal act. Do not infer or invent rules. Use the exact validator "
            'contracts: duration uses min_days/max_days; numeric uses entity '
            "plus min/max; date uses before/after ISO dates; keyword uses "
            "keywords plus optional mode (forbidden/required) and match "
            "(literal/stem/regex); regex uses pattern; semantic uses supported "
            "RAG settings. "
            "Never use generic field/operator/unit/value parameters. Return exactly "
            'one JSON object with a "rules" array; do not return a bare array. '
            f"JSON.\nDocument:\n{text}"
        )
        logger.info(
            "Calling Google AI Studio rule extraction (model: %s, prompt length: %d)",
            self.model_name,
            len(prompt),
        )
        try:
            try:
                response = _generate_google_with_retries(
                    self._client,
                    model=self.model_name,
                    contents=prompt,
                    config=_google_generation_config(
                        self._config, schema=RULE_EXTRACTION_SCHEMA
                    ),
                )
            except _google_api_error() as api_err:
                logger.warning("Structured rule extraction with schema failed (%s), retrying with json_only", api_err)
                response = _generate_google_with_retries(
                    self._client,
                    model=self.model_name,
                    contents=prompt,
                    config=_google_generation_config(self._config, json_only=True),
                )
            raw_text = getattr(response, "text", "")
            trace_logger.info(
                "Google AI Studio rule extraction response length: %d",
                len(raw_text),
            )
            payload = _parse_rule_response(response)
            rules = payload.get("rules")
            if not isinstance(rules, list):
                logger.error("Parsed rule response has no 'rules' array")
                raise ValueError("rule extraction provider returned invalid JSON")
            result = tuple(item for item in rules if isinstance(item, dict))
            logger.info("Google AI Studio successfully extracted %d rules", len(result))
            return result
        except Exception as exc:
            logger.warning(
                "Google AI Studio rule extraction failed (%s); falling back to deterministic extractor",
                exc,
            )
            fallback = StubRuleExtractionProvider().extract_rules(text)
            logger.info(
                "Fallback StubRuleExtractionProvider produced %d rules",
                len(fallback),
            )
            return fallback


class GoogleAIStudioEmbeddingProvider:
    """Google AI Studio text embedding provider."""

    def __init__(self, config: ModelConfig, *, client=None) -> None:
        if not config.dimension:
            raise ValueError("dimension is required for an embedding provider")
        self.model_name = config.model
        self.dimension = config.dimension
        self._config = config
        self._client = client or _google_client(config)

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        if not texts:
            return ()
        try:
            vectors = []
            for text in texts:
                response = self._client.models.embed_content(
                    model=self.model_name,
                    contents=text,
                    config={"output_dimensionality": self.dimension},
                )
                values = getattr(getattr(response, "embeddings", [None])[0], "values", None)
                if not isinstance(values, (list, tuple)):
                    raise EmbeddingError("Google AI Studio returned an invalid embedding")
                vectors.append(tuple(float(value) for value in values))
            validate_vectors(vectors, len(texts), self.dimension)
            return tuple(vectors)
        except Exception as exc:
            logger.warning(
                "Google AI Studio embedding failed (%s); falling back to deterministic provider",
                exc,
            )
            return DeterministicEmbeddingProvider(dimension=self.dimension).embed_documents(texts)

    def embed_query(self, text: str) -> Vector:
        return self.embed_documents([text])[0]


def _google_client(config: ModelConfig):
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is required for the google-ai-studio provider"
        ) from exc
    api_key = config.api_key()
    if not api_key:
        if config.api_key_env:
            raise ValueError(f"environment variable {config.api_key_env} is not set")
        raise ValueError("Google AI Studio requires an API key")
    return genai.Client(api_key=api_key)


def _google_api_error():
    """Return the SDK API error base class without importing Google at module load."""
    try:
        from google.genai.errors import APIError
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is required for the google-ai-studio provider"
        ) from exc
    return APIError


def _generate_google_with_retries(
    client,
    *,
    model: str,
    contents: str,
    config,
    attempts: int = 3,
):
    """Retry transient Google availability failures before reporting an error."""
    api_error = _google_api_error()
    for attempt in range(attempts):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except api_error as exc:
            if not _is_retryable_google_error(exc) or attempt == attempts - 1:
                raise
            time.sleep(2**attempt)


def _is_retryable_google_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    return status_code in {429, 500, 503}


def _google_generation_config(
    config: ModelConfig,
    *,
    system_instruction: str | None = None,
    schema: dict[str, object] | None = None,
    json_only: bool = False,
):
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is required for the google-ai-studio provider"
        ) from exc
    values: dict[str, object] = {
        "temperature": config.temperature,
        "max_output_tokens": config.max_tokens,
    }
    if system_instruction:
        values["system_instruction"] = system_instruction
    if schema is not None:
        values["response_mime_type"] = "application/json"
        values["response_schema"] = _google_schema(schema)
    elif json_only:
        values["response_mime_type"] = "application/json"
    return types.GenerateContentConfig(**values)


def _google_schema(schema: dict[str, object]) -> dict[str, object]:
    """Convert JSON Schema to the narrower Google Generative Language schema."""
    unsupported = {"additionalProperties", "$schema", "definitions", "$defs"}
    converted: dict[str, object] = {}
    for key, value in schema.items():
        if key in unsupported:
            continue
        if key == "properties" and isinstance(value, dict):
            converted[key] = {
                name: _google_schema(item)
                for name, item in value.items()
                if isinstance(item, dict)
            }
        elif key == "items" and isinstance(value, dict):
            converted[key] = _google_schema(value)
        elif key == "type" and value == "integer":
            converted[key] = "integer"
        else:
            converted[key] = value
    return converted


def _google_response_text(response) -> str:
    content = getattr(response, "text", None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Google AI Studio returned empty text")
    return content


def _parse_json_response(response) -> dict[str, object]:
    try:
        parsed = json.loads(_google_response_text(response))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Google AI Studio returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Google AI Studio returned a non-object JSON response")
    return parsed


def _parse_rule_response(response) -> dict[str, object]:
    """Normalize Google rule responses that may use an object or root array."""
    content = _google_response_text(response)
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Google AI Studio returned invalid JSON") from exc
    if isinstance(parsed, list):
        return {"rules": parsed}
    if isinstance(parsed, dict):
        return parsed
    raise ValueError("Google AI Studio returned an invalid rule response")


def create_embedding_provider(config: ModelConfig) -> EmbeddingProvider:
    """Create an embedding provider from a resolved model config."""
    if config.provider == "deterministic":
        return DeterministicEmbeddingProvider(
            dimension=config.dimension or 32,
            model_name=config.model,
        )
    if config.provider == "openai-compatible":
        return OpenAICompatibleEmbeddingProvider(config)
    if config.provider == "google-ai-studio":
        return GoogleAIStudioEmbeddingProvider(config)
    raise ValueError(f"unsupported embedding provider: {config.provider}")


def create_llm_provider(config: ModelConfig) -> LLMProvider:
    """Create an LLM provider from a resolved model config."""
    if config.provider == "stub":
        return StubLLMProvider()
    if config.provider == "openai-compatible":
        return OpenAICompatibleLLMProvider(config)
    if config.provider == "google-ai-studio":
        return GoogleAIStudioLLMProvider(config)
    raise ValueError(f"unsupported LLM provider: {config.provider}")


def create_entity_extraction_provider(
    config: ModelConfig,
) -> EntityExtractionProvider:
    if config.provider == "stub":
        return StubEntityExtractionProvider()
    """Create a configured document entity extraction provider."""
    if config.provider == "openai-compatible":
        return OpenAICompatibleEntityExtractionProvider(config)
    if config.provider == "google-ai-studio":
        return GoogleAIStudioEntityExtractionProvider(config)
    raise ValueError(f"unsupported entity extraction provider: {config.provider}")


def create_rule_extraction_provider(config: ModelConfig) -> RuleExtractionProvider:
    """Create a configured legal-act rule extraction provider."""
    if config.provider == "stub":
        return StubRuleExtractionProvider()
    if config.provider == "openai-compatible":
        return OpenAICompatibleRuleExtractionProvider(config)
    if config.provider == "google-ai-studio":
        return GoogleAIStudioRuleExtractionProvider(config)
    raise ValueError(f"unsupported rule extraction provider: {config.provider}")


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
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"model provider request failed: HTTP {exc.code}: {detail}"
        ) from exc
    except (error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"model provider request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError("model provider returned a non-object response")
    return result

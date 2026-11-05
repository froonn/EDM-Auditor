"""Structured interpretation of deterministic audit findings."""

import json
import logging
from collections.abc import Sequence
from typing import Any

from edm_auditor.model_providers import LLMProvider

from .neural_errors import InvalidNeuralResponse
from .neural_models import (
    NeuralAnalysis,
    NeuralFinding,
    NeuralResult,
)
from .prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_summary_prompt,
    build_user_prompt,
)

logger = logging.getLogger(__name__)


class LLMInterpreter:
    """Call an LLM and accept only references to known findings and sources."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        batch_size: int = 10,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.provider = provider
        self.batch_size = batch_size

    def analyze(
        self,
        findings: Sequence[NeuralFinding],
        *,
        document_type: str | None = None,
        output_language: str = "ru",
    ) -> NeuralResult:
        """Check and explain every finding in batches small enough for one model response."""
        batches = [
            findings[index : index + self.batch_size]
            for index in range(0, len(findings), self.batch_size)
        ] or [()]
        analyses: list[NeuralAnalysis] = []
        summaries: list[str] = []
        for batch in batches:
            known_keys = {item.key for item in batch}
            confirmable = {item.key for item in batch if item.requires_confirmation}
            batch_analyses, summary = self._request(
                build_user_prompt(
                    batch, document_type=document_type, output_language=output_language
                ),
                known_keys,
                confirmable,
            )
            answered = {item.finding_key for item in batch_analyses}
            if confirmable - answered:
                raise InvalidNeuralResponse("the model did not check every candidate finding")
            if known_keys - answered:
                logger.warning(
                    "The model did not explain %d finding(s)", len(known_keys - answered)
                )
            analyses.extend(batch_analyses)
            summaries.append(summary)
        general_summary = summaries[0]
        if len(summaries) > 1:
            _, general_summary = self._request(
                build_summary_prompt(
                    summaries, document_type=document_type, output_language=output_language
                ),
                set(),
                set(),
            )
        return NeuralResult(
            status="completed",
            model=self.provider.model_name,
            prompt_version=PROMPT_VERSION,
            analyses=tuple(analyses),
            general_summary=general_summary[:4000],
        )

    def _request(
        self, user_prompt: str, known_keys: set[str], confirmable: set[str]
    ) -> tuple[tuple[NeuralAnalysis, ...], str]:
        raw = self.provider.generate(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise InvalidNeuralResponse("LLM response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidNeuralResponse("LLM response must be a JSON object")
        analyses = payload.get("analyses", [])
        if not isinstance(analyses, list):
            raise InvalidNeuralResponse("analyses must be a JSON array")
        validated = tuple(
            self._parse_analysis(item, known_keys, confirmable) for item in analyses
        )
        summary = payload.get("general_summary", "")
        if not isinstance(summary, str):
            raise InvalidNeuralResponse("general_summary must be a string")
        return validated, summary

    def _parse_analysis(
        self, value: Any, known_keys: set[str], confirmable: set[str]
    ) -> NeuralAnalysis:
        if not isinstance(value, dict):
            raise InvalidNeuralResponse("each analysis must be an object")
        key = value.get("finding_key")
        if not isinstance(key, str) or key not in known_keys:
            raise InvalidNeuralResponse("analysis references an unknown finding")
        explanation = value.get("explanation")
        recommendation = value.get("recommendation", "")
        confidence = value.get("confidence")
        if not isinstance(explanation, str) or not explanation.strip():
            raise InvalidNeuralResponse("analysis explanation must be non-empty")
        if not isinstance(recommendation, str):
            raise InvalidNeuralResponse("analysis recommendation must be a string")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise InvalidNeuralResponse("analysis confidence must be numeric")
        if not 0 <= confidence <= 1:
            raise InvalidNeuralResponse("analysis confidence must be between 0 and 1")
        is_violation = value.get("is_violation")
        if key in confirmable and not isinstance(is_violation, bool):
            raise InvalidNeuralResponse("is_violation must be a boolean for a candidate finding")
        return NeuralAnalysis(
            finding_key=key,
            explanation=explanation[:4000],
            recommendation=recommendation[:4000],
            confidence=float(confidence),
            # Only value comparisons can be wrong about what the value means.
            is_violation=is_violation if key in confirmable else True,
        )

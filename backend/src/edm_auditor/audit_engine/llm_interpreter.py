"""Structured interpretation of deterministic audit findings."""

import json
from collections.abc import Sequence
from typing import Any

from edm_auditor.model_providers import LLMProvider

from .neural_errors import InvalidNeuralResponse
from .neural_models import (
    NeuralAnalysis,
    NeuralFinding,
    NeuralResult,
)
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt


class LLMInterpreter:
    """Call an LLM and accept only references to known findings and sources."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_findings: int = 20,
        max_contexts: int = 5,
    ) -> None:
        self.provider = provider
        self.max_findings = max_findings
        self.max_contexts = max_contexts

    def analyze(
        self,
        findings: Sequence[NeuralFinding],
        *,
        document_type: str | None = None,
    ) -> NeuralResult:
        selected = tuple(findings[: self.max_findings])
        known_keys = {item.key for item in selected}
        raw = self.provider.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_user_prompt(selected, document_type=document_type),
        )
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
            self._parse_analysis(item, known_keys) for item in analyses
        )
        summary = payload.get("general_summary", "")
        if not isinstance(summary, str):
            raise InvalidNeuralResponse("general_summary must be a string")
        return NeuralResult(
            status="completed",
            model=self.provider.model_name,
            prompt_version=PROMPT_VERSION,
            analyses=validated,
            general_summary=summary[:4000],
        )

    def _parse_analysis(
        self, value: Any, known_keys: set[str]
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
        legal_basis = value.get("legal_basis", [])
        if not isinstance(legal_basis, list) or not all(
            isinstance(item, dict) for item in legal_basis[: self.max_contexts]
        ):
            raise InvalidNeuralResponse("legal_basis must be an array of objects")
        return NeuralAnalysis(
            finding_key=key,
            explanation=explanation[:4000],
            recommendation=recommendation[:4000],
            confidence=float(confidence),
            legal_basis=tuple(legal_basis[: self.max_contexts]),
        )

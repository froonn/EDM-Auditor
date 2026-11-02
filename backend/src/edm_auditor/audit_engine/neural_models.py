"""Contracts for the optional neural interpretation layer."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NeuralFinding:
    """Finding data sent to the language model."""

    key: str
    rule_code: str
    severity: str
    description: str
    quote: str | None
    context: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class NeuralAnalysis:
    """Validated interpretation returned by the language model."""

    finding_key: str
    explanation: str
    recommendation: str
    confidence: float
    legal_basis: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class NeuralResult:
    """Complete validated neural analysis and its execution status."""

    status: str
    model: str | None = None
    prompt_version: str = "1"
    analyses: tuple[NeuralAnalysis, ...] = ()
    general_summary: str = ""
    diagnostic: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "analyses": [
                {
                    "finding_key": item.finding_key,
                    "explanation": item.explanation,
                    "recommendation": item.recommendation,
                    "confidence": item.confidence,
                    "legal_basis": list(item.legal_basis),
                }
                for item in self.analyses
            ],
            "general_summary": self.general_summary,
            "diagnostic": self.diagnostic,
        }

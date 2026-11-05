"""Deterministic document audit engine."""

from .engine import AuditEngine
from .extractors import ChunkedEntityExtractor, entities_from_provider, extract_entities
from .llm_interpreter import LLMInterpreter
from .neural_models import NeuralFinding, NeuralResult
from .persistence import AuditPersistence, AuditSelectionRequired
from .models import (
    AuditRequest,
    AuditResult,
    ExtractedEntity,
    FindingDraft,
    RuleDiagnostic,
    RuleSpec,
)
from .rag_validator import ContextSearcher, validate_semantic_rule
from .validators import validate_rule

__all__ = [
    "AuditEngine",
    "ChunkedEntityExtractor",
    "LLMInterpreter",
    "NeuralFinding",
    "NeuralResult",
    "AuditPersistence",
    "AuditSelectionRequired",
    "AuditRequest",
    "AuditResult",
    "ExtractedEntity",
    "FindingDraft",
    "RuleDiagnostic",
    "RuleSpec",
    "extract_entities",
    "entities_from_provider",
    "validate_rule",
    "ContextSearcher",
    "validate_semantic_rule",
]

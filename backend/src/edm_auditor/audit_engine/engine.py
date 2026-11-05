"""Audit orchestration independent of the database implementation."""

from collections.abc import Callable, Iterable
from typing import Any

from edm_auditor.rag.exceptions import RAGError

from .exceptions import InvalidRuleConfiguration
from .extractors import entities_from_provider, extract_entities
from .models import AuditResult, ExtractedEntity, FindingDraft, RuleDiagnostic, RuleSpec
from .neural_errors import AuditModelError
from .validators import validate_rule
from .rag_validator import ContextSearcher, validate_semantic_rule


class AuditEngine:
    """Run active rules and produce stable, source-preserving findings."""

    def __init__(
        self,
        entity_extractor: Callable[[str], tuple[ExtractedEntity, ...]],
        rag_searcher: ContextSearcher | None = None,
    ) -> None:
        self._rag_searcher = rag_searcher
        self._entity_extractor = entity_extractor

    def audit(
        self,
        text: str,
        rules: Iterable[RuleSpec],
    ) -> AuditResult:
        findings: list[FindingDraft] = []
        diagnostics: list[RuleDiagnostic] = []
        entities = extract_entities(text)
        try:
            provider_entities = self._entity_extractor(text)
            if provider_entities and isinstance(provider_entities[0], dict):
                provider_entities = entities_from_provider(text, provider_entities)
            entities = _merge_entities(entities, provider_entities)
        except (RuntimeError, ValueError, TypeError) as exc:
            raise AuditModelError("entity extraction model failed") from exc
        for rule in rules:
            if not rule.is_active:
                continue
            try:
                if rule.check_type == "semantic":
                    if self._rag_searcher is None:
                        raise ValueError("semantic rule requires a configured RAG searcher")
                    try:
                        findings.extend(
                            validate_semantic_rule(rule, text, self._rag_searcher)
                        )
                    except InvalidRuleConfiguration:
                        raise
                    except (RuntimeError, ValueError, TypeError, RAGError) as exc:
                        raise AuditModelError("semantic search failed") from exc
                else:
                    findings.extend(validate_rule(rule, text, entities))
            except (ValueError, TypeError) as exc:
                diagnostics.append(RuleDiagnostic(rule.rule_code, str(exc)))
        unique = {finding.deduplication_key: finding for finding in findings}
        ordered = tuple(
            sorted(
                unique.values(),
                key=lambda finding: (
                    finding.start_char if finding.start_char is not None else len(text),
                    finding.severity,
                    finding.rule_code,
                ),
            )
        )
        return AuditResult(ordered, tuple(sorted(diagnostics, key=lambda item: item.rule_code)))


def _merge_entities(
    deterministic: tuple[ExtractedEntity, ...],
    provider: tuple[Any, ...],
) -> tuple:
    """Keep deterministic entities and add non-duplicate provider entities."""
    merged = {
        (entity.kind, entity.start_char, entity.end_char): entity
        for entity in deterministic
    }
    merged.update({
        (entity.kind, entity.start_char, entity.end_char): entity
        for entity in provider
    })
    return tuple(
        sorted(merged.values(), key=lambda entity: (entity.start_char, entity.kind))
    )

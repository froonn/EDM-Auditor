"""Audit orchestration independent of the database implementation."""

from collections.abc import Callable, Iterable
from typing import Any

from edm_auditor.rag.exceptions import RAGError

from .exceptions import InvalidRuleConfiguration
from .extractors import entities_from_provider, extract_entities, statements_from_provider
from .models import (
    AuditResult,
    ExtractedEntity,
    FindingDraft,
    RuleDiagnostic,
    RuleSpec,
    StatementSpec,
)
from .neural_errors import AuditModelError
from .validators import validate_rule
from .rag_validator import ContextSearcher


class AuditEngine:
    """Run active rules and produce stable, source-preserving findings."""

    def __init__(
        self,
        entity_extractor: Callable[[str], tuple[Any, ...]] | None = None,
        rag_searcher: ContextSearcher | None = None,
        *,
        statement_extractor: Callable[[str], tuple[StatementSpec, ...]] | None = None,
    ) -> None:
        self._rag_searcher = rag_searcher
        self._entity_extractor = entity_extractor
        self._statement_extractor = statement_extractor

    @property
    def statement_extractor(self) -> Callable[[str], tuple[StatementSpec, ...]] | None:
        return self._statement_extractor

    def extract_statements(self, text: str) -> tuple[StatementSpec, ...]:
        """Extract document statements using the configured statement or entity extractor."""
        extractor = self._statement_extractor or self._entity_extractor
        if extractor is None:
            return ()
        try:
            raw = extractor(text)
            if not raw:
                return ()
            first = raw[0]
            if isinstance(first, StatementSpec):
                return tuple(raw)
            if isinstance(first, dict) and "statement_text" in first:
                return statements_from_provider(text, raw)
            return ()
        except (RuntimeError, ValueError, TypeError) as exc:
            raise AuditModelError("entity extraction model failed") from exc

    def audit(
        self,
        text: str,
        rules: Iterable[RuleSpec],
        *,
        statements: Iterable[StatementSpec] | None = None,
    ) -> AuditResult:
        findings: list[FindingDraft] = []
        diagnostics: list[RuleDiagnostic] = []
        entities = extract_entities(text)
        resolved_statements: tuple[StatementSpec, ...] = (
            tuple(statements) if statements is not None else ()
        )
        if statements is None:
            try:
                extractor = self._statement_extractor or self._entity_extractor
                provider_items = extractor(text) if extractor is not None else ()
                if provider_items:
                    first = provider_items[0]
                    if isinstance(first, StatementSpec):
                        resolved_statements = tuple(provider_items)
                    elif isinstance(first, dict) and "statement_text" in first:
                        resolved_statements = statements_from_provider(text, provider_items)
                    elif isinstance(first, dict):
                        provider_entities = entities_from_provider(text, provider_items)
                        entities = _merge_entities(entities, provider_entities)
                    elif isinstance(first, ExtractedEntity):
                        entities = _merge_entities(entities, tuple(provider_items))
            except (RuntimeError, ValueError, TypeError) as exc:
                raise AuditModelError("entity extraction model failed") from exc
        for rule in rules:
            if not rule.is_active:
                continue
            try:
                findings.extend(validate_rule(rule, text, entities, resolved_statements))
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

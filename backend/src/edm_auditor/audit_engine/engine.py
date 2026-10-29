"""Audit orchestration independent of the database implementation."""

from collections.abc import Iterable

from .extractors import extract_entities
from .models import AuditResult, FindingDraft, RuleDiagnostic, RuleSpec
from .validators import validate_rule
from .rag_validator import ContextSearcher, validate_semantic_rule


class AuditEngine:
    """Run active rules and produce stable, source-preserving findings."""

    def __init__(self, rag_searcher: ContextSearcher | None = None) -> None:
        self._rag_searcher = rag_searcher

    def audit(
        self,
        text: str,
        rules: Iterable[RuleSpec],
        *,
        document_type: str | None = None,
    ) -> AuditResult:
        entities = extract_entities(text)
        findings: list[FindingDraft] = []
        diagnostics: list[RuleDiagnostic] = []
        for rule in rules:
            if not rule.is_active or (
                rule.document_type is not None and rule.document_type != document_type
            ):
                continue
            try:
                if rule.check_type == "semantic":
                    if self._rag_searcher is None:
                        raise ValueError("semantic rule requires a configured RAG searcher")
                    findings.extend(validate_semantic_rule(rule, text, self._rag_searcher))
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

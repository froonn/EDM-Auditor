"""Normative context retrieval for semantic audit rules."""

from typing import Protocol
from typing import Any

from edm_auditor.rag.models import SearchResult

from .exceptions import InvalidRuleConfiguration
from .models import FindingDraft, RuleSpec


class ContextSearcher(Protocol):
    """Minimal RAG contract used by the audit domain."""

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        threshold: float = 0.0,
        legal_act_id: int | None = None,
        rule_id: int | None = None,
    ) -> list[SearchResult]:
        """Return ranked normative fragments."""


def validate_semantic_rule(
    rule: RuleSpec,
    text: str,
    searcher: ContextSearcher,
) -> tuple[FindingDraft, ...]:
    """Retrieve context without pretending retrieval is a legal conclusion."""
    query = rule.parameters.get("query") or text
    if not isinstance(query, str) or not query.strip():
        raise InvalidRuleConfiguration("semantic rule requires a non-empty 'query'")
    k = rule.parameters.get("k", 3)
    threshold = rule.parameters.get("threshold", 0.0)
    if not isinstance(k, int) or k <= 0:
        raise InvalidRuleConfiguration("semantic rule 'k' must be positive")
    if not isinstance(threshold, (int, float)):
        raise InvalidRuleConfiguration("semantic rule 'threshold' must be numeric")
    results = searcher.search(
        query,
        k=k,
        threshold=float(threshold),
        legal_act_id=rule.legal_act_id,
    )
    findings = []
    for result in results:
        chunk = result.chunk
        source_context: dict[str, Any] = {
            "chunk_id": chunk.chunk_id,
            "score": result.score,
            "legal_act_id": chunk.legal_act_id,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "text": chunk.text,
        }
        findings.append(
            FindingDraft(
                rule_id=rule.rule_id,
                rule_code=rule.rule_code,
                severity=rule.severity,
                description=rule.description or "Relevant normative context requires review",
                recommendation=rule.parameters.get("recommendation"),
                legal_act_id=chunk.legal_act_id,
                source_context=source_context,
                deduplication_key=f"{rule.rule_code}:{chunk.chunk_id}",
            )
        )
    return tuple(findings)

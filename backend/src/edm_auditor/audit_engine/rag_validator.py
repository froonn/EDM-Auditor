"""Reserved interface for later semantic matching stages."""

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

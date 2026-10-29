"""Domain contracts for document auditing."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Database-independent representation of an audit rule."""

    rule_id: int
    rule_code: str
    name: str
    severity: str
    check_type: str
    description: str = ""
    document_type: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    legal_act_id: int | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class AuditRequest:
    """Input needed to audit one document."""

    document_id: int
    document_type: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedEntity:
    """A normalized value and its location in the source text."""

    kind: str
    value: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class FindingDraft:
    """A validated finding before persistence."""

    rule_id: int
    rule_code: str
    severity: str
    description: str
    start_char: int | None = None
    end_char: int | None = None
    quote: str | None = None
    recommendation: str | None = None
    legal_act_id: int | None = None
    deduplication_key: str = ""
    source_context: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RuleDiagnostic:
    """Non-fatal error encountered while evaluating one rule."""

    rule_code: str
    message: str


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Complete deterministic audit result."""

    findings: tuple[FindingDraft, ...]
    diagnostics: tuple[RuleDiagnostic, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for finding in self.findings:
            if finding.severity in counts:
                counts[finding.severity] += 1
        return counts

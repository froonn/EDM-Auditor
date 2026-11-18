"""Domain contracts for document auditing."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Database-independent representation of an audit rule."""

    rule_id: int
    rule_code: str
    subject: str
    constraint_text: str
    severity: str
    condition: str = ""
    constraint_json: dict[str, Any] | None = None
    applicability_scope: str = "unknown"
    document_types: tuple[str, ...] = ()
    legal_act_id: int | None = None
    is_active: bool = True
    source_quote: str | None = None


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
class StatementSpec:
    """A validated document statement (provision) with optional structured constraint."""

    subject: str
    statement_text: str
    source_quote: str
    start_char: int
    end_char: int
    constraint_json: dict[str, Any] | None = None
    statement_id: int | None = None
    prompt_version: str = "1"


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
    norm_quote: str | None = None
    rule_name: str = ""
    requires_confirmation: bool = False


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

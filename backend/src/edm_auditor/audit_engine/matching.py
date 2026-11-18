"""Match rules with document statements and decide which rules the document breaks (stage 4).

The model sees the statements of the document, not the rules alone: it confirms which statement
speaks about the subject of a rule and judges what code cannot compare. A rule and a statement that
both carry a structure are compared by code, so the model never overrules a numeric comparison.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from edm_auditor.model_config import AuditMatchingConfig
from edm_auditor.model_providers import MATCHING_RESPONSE_SCHEMA, LLMProvider
from edm_auditor.rag.embeddings import EmbeddingProvider
from edm_auditor.rag.exceptions import RAGError

from .models import FindingDraft, RuleSpec, StatementSpec
from .neural_errors import AuditModelError, InvalidNeuralResponse
from .validators import _satisfies

MATCH_PROMPT_VERSION = "4"
EVALUATION_STRUCTURED = "structured"
EVALUATION_MODEL = "model"
EVALUATION_MISSING = "missing"
PARAGRAPH_CHARS = 600

SYSTEM_PROMPT = (
    "You are an assistant for technical document compliance review. Match rules with the "
    "statements of a document and evaluate them. Return JSON only with schema_version, "
    "analyses, and general_summary."
)

_INSTRUCTIONS = (
    "Return exactly one entry in analyses for every rule in rules, with the same finding_key.",
    "condition_applicable: if rule.condition is empty, set it to true. If rule.condition names a "
    "special category of employees or a special circumstance (for example, employees under 18, "
    "or employees with a child under 3 years old), set it to true only when "
    "document_statements show that this category applies to this document; otherwise set it to "
    "false and is_violation to false. If rule.condition is an exception ('кроме', 'за "
    "исключением'), set it to true unless the exception occurs in the document. If rule.condition "
    "only describes the usual situation of the document itself (for example 'после возвращения из "
    "командировки' in a business trip order), set it to true.",
    "matched_statement_id: the statement_id of the statement that regulates the same subject and "
    "parameter as the rule, or null if the document has none. Never match a different parameter "
    "(an advance percentage is not a bonus percentage, internet compensation is not the cost of "
    "equipment delivery, a per diem is not the cost of travel, the length of a vacation is not the "
    "length of its part replaced by compensation). For a rule about a notice period before an "
    "event, match the statement that says when the employee was notified and use the date of the "
    "event from the other statements to count how many days ahead the notice was given.",
    "When matched_statement_id is null: set is_mandatory_condition to true if the rule requires a "
    "mandatory clause or requisite to be written in the document (a payment period, a payment "
    "method, working hours, the order of interaction, destination, term and purpose of a trip, the "
    "type of a vacation and the work period) AND the required information is truly absent from both "
    "document_statements and document_text (if provided); in that case set is_violation to true. "
    "If the required information IS present in document_text (even in other words: e.g. "
    "'за октябрь 2026 года' states payment period, 'перечислением на счета' / 'на карточные счета' "
    "states payment method, 'по электронной почте и по телефону / в рабочем чате' states interaction "
    "order, 'с 9.00 до 18.00' states work schedule), set is_violation to false. "
    "Set is_mandatory_condition to false for a prohibition or a limit on an optional action that "
    "does not occur in the document; if a prohibited action DOES occur in document_text (even if "
    "omitted from document_statements), set is_violation to true.",
    "When matched_statement_id is set and condition_applicable is true: follow candidate "
    "structured_comparison ('violation' means is_violation true, 'compliant' means false). "
    "Otherwise judge from statement_text, source_quote, paragraph_context, and document_text. "
    "For date-difference rules (e.g. notice date vs event start date), compute the exact number of "
    "calendar days between the two dates before deciding (e.g. from 10.11.2026 to 01.12.2026 is 21 "
    "days, which satisfies 'at least 15 days'). "
    "If the rule requires several items to be stated (for example destination, term and purpose of a "
    "trip), is_violation is true when any of them is missing from the document, and false when all "
    "are present, even in other words.",
    "explanation says briefly why the document does or does not comply; recommendation says what "
    "to change and is empty when there is no violation. Both are in output_language. "
    "general_summary mentions only rules with is_violation true.",
)


@dataclass(frozen=True, slots=True)
class MatchedFinding:
    """A finding together with the explanation the model gave for it."""

    finding: FindingDraft
    explanation: str
    recommendation: str
    confidence: float


@dataclass(frozen=True, slots=True)
class MatchingOutcome:
    findings: tuple[MatchedFinding, ...] = ()
    # Rule and statement pairs, so a person can see what each rule was compared with.
    pairs: tuple[dict[str, Any], ...] = ()
    # Rules without a statement whose absence is not a violation: not checked.
    unchecked: tuple[dict[str, Any], ...] = ()
    # Rules whose condition does not concern the document.
    inapplicable: tuple[dict[str, Any], ...] = ()
    general_summary: str = ""
    model: str = ""
    requests: int = 0


@dataclass(frozen=True, slots=True)
class _Verdict:
    statement_id: int | None
    applicable: bool
    mandatory: bool
    is_violation: bool
    explanation: str
    recommendation: str
    confidence: float


def compare_structured(
    rule_constraint: dict[str, Any] | None, statement_constraint: dict[str, Any] | None
) -> bool | None:
    """True when the statement meets the rule, False when it breaks it, None if not comparable."""
    if not isinstance(rule_constraint, dict) or not isinstance(statement_constraint, dict):
        return None
    kind = rule_constraint.get("kind")
    if not kind or statement_constraint.get("kind") != kind:
        return None
    operator = str(rule_constraint.get("operator", "eq"))
    try:
        if kind == "value":
            if statement_constraint.get("unit") != rule_constraint.get("unit"):
                return None
            return _satisfies(
                float(statement_constraint["value"]), operator, float(rule_constraint["value"])
            )
        if kind == "frequency":
            if statement_constraint.get("period") != rule_constraint.get("period"):
                return None
            return _satisfies(
                float(statement_constraint["count"]), operator, float(rule_constraint["count"])
            )
        if kind == "day_of_month":
            actual = float(statement_constraint["day"])
            target = float(rule_constraint["day"])
            # A later month always follows an earlier one, whatever the day.
            actual += 31 * int(statement_constraint.get("month_offset") or 0)
            target += 31 * int(rule_constraint.get("month_offset") or 0)
            return _satisfies(actual, operator, target)
    except (KeyError, TypeError, ValueError):
        return None
    return None


def cosine(first: Sequence[float], second: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second))
    norm = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return dot / norm if norm else 0.0


def candidate_pairs(
    rule_vectors: Sequence[Sequence[float]],
    statement_vectors: Sequence[Sequence[float]],
    *,
    threshold: float,
    limit: int,
) -> list[list[tuple[int, float]]]:
    """For every rule, the indexes of the most similar statements that reach the threshold."""
    result: list[list[tuple[int, float]]] = []
    for rule_vector in rule_vectors:
        scored = sorted(
            (
                (index, round(cosine(rule_vector, vector), 4))
                for index, vector in enumerate(statement_vectors)
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        result.append([item for item in scored[:limit] if item[1] >= threshold])
    return result


def _paragraph(text: str, start: int, end: int) -> str:
    begin = text.rfind("\n", 0, max(0, start))
    begin = 0 if begin < 0 else begin + 1
    finish = text.find("\n\n", max(0, end))
    finish = len(text) if finish < 0 else finish
    return " ".join(text[begin:finish].split())[:PARAGRAPH_CHARS]


class RuleMatcher:
    """Pair rules with statements, ask the model once per batch of rules, and decide in code."""

    def __init__(
        self,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        config: AuditMatchingConfig | None = None,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._config = config or AuditMatchingConfig()

    def match(
        self,
        rules: Sequence[RuleSpec],
        statements: Sequence[StatementSpec],
        text: str,
        *,
        document_type: str | None = None,
        output_language: str = "ru",
    ) -> MatchingOutcome:
        active = [rule for rule in rules if rule.is_active]
        if not active:
            return MatchingOutcome(model=self._llm.model_name)
        candidates = self._candidates(active, statements)
        findings: list[MatchedFinding] = []
        pairs: list[dict[str, Any]] = []
        unchecked: list[dict[str, Any]] = []
        inapplicable: list[dict[str, Any]] = []
        summaries: list[str] = []
        size = self._config.rules_per_request
        for offset in range(0, len(active), size):
            batch = active[offset : offset + size]
            batch_candidates = candidates[offset : offset + size]
            sent = self._statements_to_send(statements, batch_candidates)
            verdicts, summary = self._ask(
                batch, batch_candidates, statements, sent, text, document_type, output_language
            )
            summaries.append(summary)
            for rule, verdict in zip(batch, verdicts):
                self._decide(
                    rule, verdict, statements, text, findings, pairs, unchecked, inapplicable
                )
        ordered = sorted(
            {item.finding.deduplication_key: item for item in findings}.values(),
            key=lambda item: (
                item.finding.start_char if item.finding.start_char is not None else len(text),
                item.finding.severity,
                item.finding.rule_code,
            ),
        )
        return MatchingOutcome(
            findings=tuple(ordered),
            pairs=tuple(pairs),
            unchecked=tuple(unchecked),
            inapplicable=tuple(inapplicable),
            general_summary=" ".join(item for item in summaries if item)[:4000],
            model=self._llm.model_name,
            requests=-(-len(active) // size),
        )

    def _candidates(
        self, rules: Sequence[RuleSpec], statements: Sequence[StatementSpec]
    ) -> list[list[tuple[int, float]]]:
        if not statements:
            return [[] for _ in rules]
        texts = [f"{rule.subject}: {rule.constraint_text}" for rule in rules] + [
            f"{item.subject}: {item.statement_text}" for item in statements
        ]
        try:
            vectors = self._embedder.embed_documents(texts)
        except (RuntimeError, ValueError, TypeError, RAGError) as exc:
            raise AuditModelError("embedding of rules and statements failed") from exc
        return candidate_pairs(
            vectors[: len(rules)],
            vectors[len(rules) :],
            threshold=self._config.candidate_threshold,
            limit=self._config.candidate_limit,
        )

    def _statements_to_send(
        self,
        statements: Sequence[StatementSpec],
        batch_candidates: Sequence[Sequence[tuple[int, float]]],
    ) -> list[int]:
        if len(statements) <= self._config.max_statements_in_prompt:
            return list(range(len(statements)))
        return sorted({index for pairs in batch_candidates for index, _ in pairs})

    def _ask(
        self,
        batch: Sequence[RuleSpec],
        batch_candidates: Sequence[Sequence[tuple[int, float]]],
        statements: Sequence[StatementSpec],
        sent: Sequence[int],
        text: str,
        document_type: str | None,
        output_language: str,
    ) -> tuple[list[_Verdict], str]:
        prompt = json.dumps(
            {
                "schema_version": MATCH_PROMPT_VERSION,
                "document_type": document_type,
                "output_language": output_language,
                **({"document_text": text} if len(text) <= 6000 else {}),
                "document_statements": [
                    {
                        "statement_id": index + 1,
                        "subject": statements[index].subject,
                        "statement_text": statements[index].statement_text,
                        "source_quote": statements[index].source_quote,
                        "paragraph_context": _paragraph(
                            text, statements[index].start_char, statements[index].end_char
                        ),
                    }
                    for index in sent
                ],
                "rules": [
                    {
                        "finding_key": rule.rule_code,
                        "subject": rule.subject,
                        "constraint_text": rule.constraint_text,
                        "condition": rule.condition,
                        "severity": rule.severity,
                        "norm_quote": rule.source_quote,
                        "candidates": [
                            {
                                "statement_id": index + 1,
                                "similarity": score,
                                "structured_comparison": _comparison_label(
                                    rule, statements[index]
                                ),
                            }
                            for index, score in candidates
                        ],
                    }
                    for rule, candidates in zip(batch, batch_candidates)
                ],
                "instructions": list(_INSTRUCTIONS),
            },
            ensure_ascii=False,
        )
        try:
            raw = self._llm.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt,
                response_schema=MATCHING_RESPONSE_SCHEMA,
            )
        except (RuntimeError, ValueError, TypeError) as exc:
            raise AuditModelError("LLM matching failed") from exc
        return _parse_response(raw, [rule.rule_code for rule in batch], len(statements), set(sent))

    def _decide(
        self,
        rule: RuleSpec,
        verdict: _Verdict,
        statements: Sequence[StatementSpec],
        text: str,
        findings: list[MatchedFinding],
        pairs: list[dict[str, Any]],
        unchecked: list[dict[str, Any]],
        inapplicable: list[dict[str, Any]],
    ) -> None:
        reference = {"rule_id": rule.rule_id, "rule_code": rule.rule_code}
        if not verdict.applicable:
            inapplicable.append({**reference, "condition": rule.condition})
            return
        if verdict.statement_id is None:
            if verdict.is_violation:
                mode = EVALUATION_MISSING if verdict.mandatory else EVALUATION_MODEL
                pairs.append({**reference, "statement_id": None, "mode": mode})
                findings.append(self._finding(rule, verdict, None, text, mode))
            else:
                pairs.append({**reference, "statement_id": None, "mode": EVALUATION_MISSING})
                unchecked.append(reference)
            return
        statement = statements[verdict.statement_id - 1]
        comparison = compare_structured(rule.constraint_json, statement.constraint_json)
        if comparison is None:
            mode, violation = EVALUATION_MODEL, verdict.is_violation
        else:
            mode, violation = EVALUATION_STRUCTURED, not comparison
        pairs.append(
            {
                **reference,
                "statement_id": statement.statement_id,
                "statement_index": verdict.statement_id - 1,
                "mode": mode,
                "is_violation": violation,
            }
        )
        if violation:
            findings.append(self._finding(rule, verdict, statement, text, mode))

    @staticmethod
    def _finding(
        rule: RuleSpec,
        verdict: _Verdict,
        statement: StatementSpec | None,
        text: str,
        mode: str,
    ) -> MatchedFinding:
        start = statement.start_char if statement is not None else None
        end = statement.end_char if statement is not None else None
        description = rule.constraint_text or rule.subject
        return MatchedFinding(
            finding=FindingDraft(
                rule_id=rule.rule_id,
                rule_code=rule.rule_code,
                severity=rule.severity,
                description=description,
                start_char=start,
                end_char=end,
                quote=text[start:end] if start is not None and end is not None else None,
                recommendation=verdict.recommendation or None,
                legal_act_id=rule.legal_act_id,
                deduplication_key=f"{rule.rule_code}:{start}:{end}:{description}",
                norm_quote=rule.source_quote,
                rule_name=rule.subject,
                requires_confirmation=False,
                statement_text=statement.statement_text if statement is not None else None,
                evaluation_mode=mode,
            ),
            explanation=verdict.explanation,
            recommendation=verdict.recommendation,
            confidence=verdict.confidence,
        )


def _comparison_label(rule: RuleSpec, statement: StatementSpec) -> str:
    result = compare_structured(rule.constraint_json, statement.constraint_json)
    return "none" if result is None else "compliant" if result else "violation"


def _parse_response(
    raw: str, keys: Sequence[str], statement_count: int, sent: set[int]
) -> tuple[list[_Verdict], str]:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise InvalidNeuralResponse("LLM response is not valid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("analyses"), list):
        raise InvalidNeuralResponse("analyses must be a JSON array")
    summary = payload.get("general_summary", "")
    if not isinstance(summary, str):
        raise InvalidNeuralResponse("general_summary must be a string")
    by_key: dict[str, _Verdict] = {}
    for item in payload["analyses"]:
        if not isinstance(item, dict) or item.get("finding_key") not in keys:
            raise InvalidNeuralResponse("analysis references an unknown rule")
        by_key[item["finding_key"]] = _parse_verdict(item, statement_count, sent)
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise InvalidNeuralResponse("the model did not check every rule")
    return [by_key[key] for key in keys], summary


def _parse_verdict(item: dict[str, Any], statement_count: int, sent: set[int]) -> _Verdict:
    matched = item.get("matched_statement_id")
    if matched is not None:
        if isinstance(matched, bool) or not isinstance(matched, int):
            raise InvalidNeuralResponse("matched_statement_id must be an integer or null")
        if not 1 <= matched <= statement_count or matched - 1 not in sent:
            raise InvalidNeuralResponse("analysis references an unknown statement")
    for field_name in ("condition_applicable", "is_mandatory_condition", "is_violation"):
        if not isinstance(item.get(field_name), bool):
            raise InvalidNeuralResponse(f"{field_name} must be a boolean")
    explanation = item.get("explanation")
    recommendation = item.get("recommendation", "")
    confidence = item.get("confidence")
    if not isinstance(explanation, str) or not explanation.strip():
        raise InvalidNeuralResponse("analysis explanation must be non-empty")
    if not isinstance(recommendation, str):
        raise InvalidNeuralResponse("analysis recommendation must be a string")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise InvalidNeuralResponse("analysis confidence must be numeric")
    if not 0 <= confidence <= 1:
        raise InvalidNeuralResponse("analysis confidence must be between 0 and 1")
    return _Verdict(
        statement_id=matched,
        applicable=item["condition_applicable"],
        mandatory=item["is_mandatory_condition"],
        is_violation=item["is_violation"],
        explanation=explanation[:4000],
        recommendation=recommendation[:4000],
        confidence=float(confidence),
    )

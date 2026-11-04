"""Build the selection snapshot stored with an audit report."""

from collections.abc import Sequence
from typing import Any

from .models import DocumentContext, ResolutionResult, SelectionConfig


def selection_snapshot(
    config: SelectionConfig,
    document: DocumentContext,
    resolution: ResolutionResult,
    legal_acts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Describe the selection so an old report stays explainable after later changes."""
    return {
        "selection_mode": config.mode.value,
        "selected_legal_act_ids": sorted(config.legal_act_ids),
        "included_rule_ids": sorted(config.included_rule_ids),
        "excluded_rule_ids": sorted(config.excluded_rule_ids),
        "confirmed_document_types": list(document.confirmed_document_types),
        "candidate_document_types": list(document.candidate_document_types),
        "classification_status": document.classification_status,
        "classification_confidence": document.confidence,
        "applied_rule_ids": list(resolution.selected_rule_ids),
        "applied_legal_acts": list(legal_acts),
        "selection_reasons": [
            {
                "rule_id": item.rule_id,
                "rule_code": item.rule_code,
                "name": item.name,
                "legal_act_id": item.legal_act_id,
                "applicability_scope": item.applicability_scope,
                "document_types": list(item.document_types),
                "selected": item.selected,
                "reason": item.reason.value,
            }
            for item in resolution.decisions
        ],
        "warnings": [item.value for item in resolution.warnings],
        "rag_recommendations": [
            {
                "legal_act_id": item.legal_act_id,
                "rule_id": item.rule_id,
                "score": item.score,
                "threshold": item.threshold,
                "reason": item.reason,
            }
            for item in resolution.recommendations
        ],
    }

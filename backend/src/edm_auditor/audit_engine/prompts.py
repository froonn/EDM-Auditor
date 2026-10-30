"""Versioned prompts for audit interpretation."""

import json
from collections.abc import Sequence

from .neural_models import NeuralFinding

PROMPT_VERSION = "1"
SYSTEM_PROMPT = (
    "You are an assistant for technical document review. Do not decide legal "
    "compliance. Return JSON only with schema_version, analyses, and general_summary."
)


def build_user_prompt(
    findings: Sequence[NeuralFinding], *, document_type: str | None = None
) -> str:
    payload = {
        "schema_version": PROMPT_VERSION,
        "document_type": document_type,
        "findings": [
            {
                "finding_key": item.key,
                "rule_code": item.rule_code,
                "severity": item.severity,
                "description": item.description,
                "quote": item.quote,
                "contexts": list(item.context),
            }
            for item in findings
        ],
        "instructions": [
            "Explain only the supplied findings.",
            "Keep finding_key unchanged.",
            "Do not invent legal acts or findings.",
            "Use confidence from 0 to 1.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)

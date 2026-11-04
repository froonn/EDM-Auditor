"""Run an audit against an existing SQLite database without FastAPI."""

import argparse
import json

from edm_auditor.audit_engine import (
    AuditEngine,
    AuditPersistence,
    LLMInterpreter,
    entities_from_provider,
)
from edm_auditor.database import create_engine_for, create_session_factory
from edm_auditor.model_config import ModelSettings
from edm_auditor.model_providers import (
    create_entity_extraction_provider,
    create_llm_provider,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id", type=int)
    parser.add_argument("--database", default="sqlite:///data/edm_auditor.sqlite3")
    args = parser.parse_args()

    factory = create_session_factory(create_engine_for(args.database))
    settings = ModelSettings.from_env()
    if settings.extractor is None:
        raise ValueError("configured model preset must declare an online extractor")
    extractor = create_entity_extraction_provider(settings.extractor)
    report = AuditPersistence(
        factory,
        engine=AuditEngine(
            entity_extractor=lambda text: entities_from_provider(
                text, extractor.extract(text)
            )
        ),
        neural_interpreter=LLMInterpreter(create_llm_provider(settings.llm)),
    ).audit_document(args.document_id)
    print(
        json.dumps(
            {
                "report_id": report.id,
                "document_id": report.document_id,
                "total_findings": report.total_findings,
                "critical": report.critical_count,
                "high": report.high_count,
                "medium": report.medium_count,
                "low": report.low_count,
                "summary": json.loads(report.summary or "{}"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

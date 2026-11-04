"""Run an audit against an existing SQLite database without FastAPI."""

import argparse
import json
import sys

from edm_auditor.applicability import SelectionConfig, SelectionMode
from edm_auditor.audit_engine import (
    AuditEngine,
    AuditPersistence,
    AuditSelectionRequired,
    LLMInterpreter,
    entities_from_provider,
)
from edm_auditor.classification.store import (
    classify_and_store,
    ensure_default_document_types,
)
from edm_auditor.database.models import Document
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
    parser.add_argument(
        "--mode", choices=[item.value for item in SelectionMode], default="automatic"
    )
    parser.add_argument("--legal-act", type=int, action="append", default=[])
    parser.add_argument("--include", type=int, action="append", default=[])
    parser.add_argument("--exclude", type=int, action="append", default=[])
    parser.add_argument(
        "--confirm-all",
        action="store_true",
        help="confirm the broad diagnostic 'all' mode",
    )
    args = parser.parse_args()

    factory = create_session_factory(create_engine_for(args.database))
    ensure_default_document_types(factory)
    with factory.begin() as session:
        document = session.get(Document, args.document_id)
        if document is not None and document.classification_status is None:
            classify_and_store(session, document)
    settings = ModelSettings.from_env()
    if settings.extractor is None:
        raise ValueError("configured model preset must declare an online extractor")
    extractor = create_entity_extraction_provider(settings.extractor)
    persistence = AuditPersistence(
        factory,
        engine=AuditEngine(
            entity_extractor=lambda text: entities_from_provider(
                text, extractor.extract(text)
            )
        ),
        neural_interpreter=LLMInterpreter(create_llm_provider(settings.llm)),
    )
    selection = SelectionConfig(
        mode=SelectionMode(args.mode),
        legal_act_ids=frozenset(args.legal_act),
        included_rule_ids=frozenset(args.include),
        excluded_rule_ids=frozenset(args.exclude),
        confirm_all=args.confirm_all,
    )
    try:
        report = persistence.audit_document(args.document_id, selection)
    except AuditSelectionRequired as exc:
        warnings = ", ".join(item.value for item in exc.resolution.warnings)
        print(f"{exc.resolution.status.value}: {warnings}", file=sys.stderr)
        return 2
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

"""FastAPI application factory and endpoint implementation."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from edm_auditor.audit_engine.persistence import AuditPersistence
from edm_auditor.audit_engine import LLMInterpreter
from edm_auditor.database import (
    DocumentRepository,
    create_engine_for,
    create_session_factory,
)
from edm_auditor.database.enums import AuditSeverity, CheckType
from edm_auditor.database.models import AuditReport, AuditRule, Document, LegalAct
from edm_auditor.document_parser import parse_document
from edm_auditor.document_parser.exceptions import DocumentParserError
from edm_auditor.model_config import ModelSettings
from edm_auditor.model_providers import create_llm_provider

from .config import ApiSettings
from .errors import ApiError, parser_error
from .schemas import (
    AuditRequestResponse,
    DocumentResponse,
    FindingResponse,
    LegalActResponse,
    ReportResponse,
    RuleCreate,
    RuleResponse,
)
from .storage import store_upload

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: ApiSettings | None = None,
    session_factory=None,
) -> FastAPI:
    config = settings or ApiSettings.from_env()
    engine = None
    if session_factory is None:
        engine = create_engine_for(config.database_url)
        session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(title="EDM-Auditor API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.session_factory = session_factory
    neural_interpreter = None
    if config.neural_mode != "disabled":
        model_settings = ModelSettings.from_toml(config.model_config)
        neural_interpreter = LLMInterpreter(
            create_llm_provider(model_settings.llm)
        )

    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid4().hex)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers={"X-Request-ID": request.state.request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": str(exc)}},
            headers={"X-Request-ID": request.state.request_id},
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/documents/upload", response_model=DocumentResponse, status_code=201)
    async def upload_document(
        file: UploadFile = File(...),
        title: str | None = None,
    ) -> DocumentResponse:
        try:
            path, _ = await store_upload(
                file, config.upload_dir, config.max_upload_bytes
            )
        except ValueError as exc:
            raise ApiError(413, "document_too_large", str(exc)) from exc
        try:
            parsed = parse_document(path, max_size_bytes=config.max_upload_bytes)
            repository = DocumentRepository(session_factory)
            document = repository.save_parsed_document(
                parsed,
                title=title or Path(file.filename or path.name).stem,
                file_path=path,
            )
            return DocumentResponse.model_validate(document)
        except DocumentParserError as exc:
            path.unlink(missing_ok=True)
            raise parser_error(exc) from exc

    @app.get("/api/documents/{document_id}", response_model=DocumentResponse)
    def get_document(document_id: int) -> DocumentResponse:
        with session_factory() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise ApiError(404, "document_not_found", "Document does not exist")
            return DocumentResponse.model_validate(document)

    @app.post(
        "/api/documents/{document_id}/audit",
        response_model=AuditRequestResponse,
    )
    def audit_document(document_id: int) -> AuditRequestResponse:
        try:
            report = AuditPersistence(
                session_factory,
                neural_interpreter=neural_interpreter,
                neural_mode=config.neural_mode,
            ).audit_document(document_id)
        except LookupError as exc:
            raise ApiError(404, "document_not_found", str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise ApiError(422, "audit_configuration_error", str(exc)) from exc
        return AuditRequestResponse(
            report_id=report.id,
            document_id=report.document_id,
            total_findings=report.total_findings,
            status="audited",
        )

    @app.get(
        "/api/documents/{document_id}/report",
        response_model=ReportResponse,
    )
    def get_report(
        document_id: int, report_id: int | None = Query(default=None)
    ) -> ReportResponse:
        with session_factory() as session:
            statement = (
                select(AuditReport)
                .options(selectinload(AuditReport.findings))
                .where(AuditReport.document_id == document_id)
            )
            if report_id is not None:
                statement = statement.where(AuditReport.id == report_id)
            else:
                statement = statement.order_by(AuditReport.created_at.desc())
            report = session.scalar(statement)
            if report is None:
                raise ApiError(404, "report_not_found", "Audit report does not exist")
            summary = _parse_summary(report.summary)
            contexts = summary.get("rag_contexts", [])
            neural = summary.get("neural", {})
            findings = [
                FindingResponse(
                    id=finding.id,
                    rule_id=finding.rule_id,
                    legal_act_id=finding.legal_act_id,
                    severity=finding.severity,
                    description=finding.description,
                    start_char=finding.start_char,
                    end_char=finding.end_char,
                    quote=finding.quote,
                    recommendation=finding.recommendation,
                    source_context=(
                        contexts[index] if index < len(contexts) else None
                    ),
                )
                for index, finding in enumerate(report.findings)
            ]
            return ReportResponse(
                id=report.id,
                document_id=report.document_id,
                total_findings=report.total_findings,
                critical_count=report.critical_count,
                high_count=report.high_count,
                medium_count=report.medium_count,
                low_count=report.low_count,
                summary=summary,
                created_at=report.created_at,
                findings=findings,
                neural_status=neural.get("status", "not_requested"),
                neural_analyses=neural.get("analyses", []),
            )

    @app.get("/api/rules", response_model=list[RuleResponse])
    def list_rules(
        is_active: bool | None = None,
        document_type: str | None = None,
        check_type: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[RuleResponse]:
        with session_factory() as session:
            statement = select(AuditRule).order_by(AuditRule.id).offset(offset).limit(limit)
            if is_active is not None:
                statement = statement.where(AuditRule.is_active.is_(is_active))
            if document_type is not None:
                statement = statement.where(AuditRule.document_type == document_type)
            if check_type is not None:
                statement = statement.where(AuditRule.check_type == check_type)
            return [
                _rule_response(rule)
                for rule in session.scalars(statement).all()
            ]

    @app.post("/api/rules", response_model=RuleResponse, status_code=201)
    def create_rule(payload: RuleCreate) -> RuleResponse:
        if payload.severity not in {item.value for item in AuditSeverity}:
            raise ApiError(422, "invalid_severity", "Unsupported severity")
        if payload.check_type not in {item.value for item in CheckType}:
            raise ApiError(422, "invalid_check_type", "Unsupported check type")
        with session_factory.begin() as session:
            if payload.legal_act_id is not None and session.get(
                LegalAct, payload.legal_act_id
            ) is None:
                raise ApiError(404, "legal_act_not_found", "Legal act does not exist")
            rule = AuditRule(
                rule_code=payload.rule_code,
                name=payload.name,
                severity=payload.severity,
                check_type=payload.check_type,
                description=payload.description,
                document_type=payload.document_type,
                parameters_json=json.dumps(
                    payload.parameters, ensure_ascii=False, sort_keys=True
                ),
                legal_act_id=payload.legal_act_id,
            )
            session.add(rule)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ApiError(409, "rule_conflict", "Rule code already exists") from exc
            return _rule_response(rule)

    @app.get("/api/legal-acts", response_model=list[LegalActResponse])
    def list_legal_acts(
        search: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[LegalActResponse]:
        with session_factory() as session:
            statement = select(LegalAct).order_by(LegalAct.id).offset(offset).limit(limit)
            if search:
                pattern = f"%{search}%"
                statement = statement.where(
                    (LegalAct.code.ilike(pattern)) | (LegalAct.title.ilike(pattern))
                )
            return [
                LegalActResponse.model_validate(item)
                for item in session.scalars(statement).all()
            ]

    return app


def _rule_response(rule: AuditRule) -> RuleResponse:
    return RuleResponse(
        id=rule.id,
        rule_code=rule.rule_code,
        name=rule.name,
        document_type=rule.document_type,
        severity=rule.severity,
        description=rule.description,
        check_type=rule.check_type,
        parameters=_parse_parameters(rule.parameters_json),
        is_active=rule.is_active,
        legal_act_id=rule.legal_act_id,
    )


def _parse_parameters(value: str | None) -> dict:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ApiError(500, "invalid_rule_parameters", "Stored parameters are invalid")
    return parsed


def _parse_summary(value: str) -> dict:
    try:
        parsed = json.loads(value) if value else {}
    except json.JSONDecodeError as exc:
        logger.error("Invalid report summary for persisted report")
        raise ApiError(500, "invalid_report_summary", "Stored report is invalid") from exc
    if not isinstance(parsed, dict):
        raise ApiError(500, "invalid_report_summary", "Stored report is invalid")
    return parsed

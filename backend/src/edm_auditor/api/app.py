"""FastAPI application factory and endpoint implementation."""

import json
import logging
from contextlib import asynccontextmanager
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from edm_auditor.audit_engine.persistence import AuditPersistence
from edm_auditor.audit_engine import AuditEngine, LLMInterpreter, entities_from_provider
from edm_auditor.database import (
    Base,
    DocumentRepository,
    create_engine_for,
    create_session_factory,
)
from edm_auditor.database.enums import AuditSeverity, CheckType
from edm_auditor.database.models import (
    AuditFinding,
    AuditReport,
    AuditRule,
    Document,
    LegalAct,
)
from edm_auditor.document_parser import parse_document
from edm_auditor.document_parser.exceptions import DocumentParserError
from edm_auditor.model_config import ModelSettings
from edm_auditor.model_providers import (
    create_entity_extraction_provider,
    create_llm_provider,
    create_rule_extraction_provider,
)
from edm_auditor.model_providers import create_embedding_provider
from edm_auditor.rag import DatabaseIndexSourceLoader, RAGIndexer, SQLiteVectorStore

from .config import ApiSettings
from .errors import ApiError, parser_error
from .schemas import (
    AuditRequestResponse,
    DocumentResponse,
    FindingResponse,
    LegalActResponse,
    LegalActCreate,
    LegalActDetailResponse,
    LegalActUpdate,
    ReportResponse,
    ReportListResponse,
    RuleCreate,
    RuleResponse,
)
from .storage import store_upload
from .web import page

logger = logging.getLogger("edm_auditor.api")
trace_logger = logging.getLogger("edm_auditor.trace")


def _setup_file_logging(log_file: Path) -> None:
    """Set up file logging so verbose HTTP and model dumps go only to the log file."""
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)

        app_logger = logging.getLogger("edm_auditor")
        resolved_path = str(log_file.resolve())
        if not any(
            isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == resolved_path
            for h in app_logger.handlers
        ):
            app_logger.addHandler(file_handler)

        trace_logger.setLevel(logging.DEBUG)
        trace_logger.propagate = False
        trace_logger.handlers.clear()
        trace_logger.addHandler(file_handler)
    except Exception as exc:
        logger.warning("Could not set up file logging at %s: %s", log_file, exc)


def _generated_rule(
    payload: dict[str, object], *, index: int
) -> dict[str, object] | None:
    """Validate one model-generated rule before persisting it."""
    rule_code = payload.get("rule_code")
    name = payload.get("name")
    description = payload.get("description")
    severity = payload.get("severity")
    check_type = payload.get("check_type")
    parameters = payload.get("parameters")
    if not all(isinstance(value, str) for value in (rule_code, name, description)):
        return None
    if severity not in {item.value for item in AuditSeverity}:
        return None
    if check_type not in {item.value for item in CheckType}:
        return None
    if not isinstance(parameters, dict):
        return None
    normalized_code = rule_code.strip()[:100]
    normalized_name = name.strip()[:255]
    if not normalized_code or not normalized_name:
        return None
    return {
        "rule_code": normalized_code or f"generated-rule-{index}",
        "name": normalized_name,
        "severity": severity,
        "description": description[:4000],
        "check_type": check_type,
        "parameters_json": json.dumps(
            parameters, ensure_ascii=False, sort_keys=True
        ),
    }


def create_app(
    *,
    settings: ApiSettings | None = None,
    session_factory=None,
) -> FastAPI:
    config = settings or ApiSettings.from_env()
    _setup_file_logging(config.log_file)
    engine = None
    if session_factory is None:
        engine = create_engine_for(config.database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(title="EDM-Auditor API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.session_factory = session_factory

    def rebuild_rag_index() -> None:
        model_settings = ModelSettings.from_toml(
            config.model_config,
            preset_name=None,
            source_language=config.source_language,
        )
        provider = create_embedding_provider(model_settings.embedding)
        store = SQLiteVectorStore(
            config.rag_index_path,
            embedding_model=provider.model_name,
            dimension=provider.dimension,
            chunking_version="paragraph-v1",
        )
        count = RAGIndexer(store, provider).build(
            DatabaseIndexSourceLoader(session_factory).load()
        )
        logger.info("Rebuilt RAG index: %s chunks", count)

    app.state.rebuild_rag_index = rebuild_rag_index
    neural_interpreter = None
    entity_extractor = None
    model_settings = ModelSettings.from_toml(
        config.model_config,
        source_language=config.source_language,
    )
    neural_interpreter = LLMInterpreter(create_llm_provider(model_settings.llm))
    if model_settings.extractor is None:
        raise ValueError("configured model preset must declare an online extractor")
    provider = create_entity_extraction_provider(model_settings.extractor)
    entity_extractor = lambda text: entities_from_provider(text, provider.extract(text))
    rule_extractor = create_rule_extraction_provider(model_settings.extractor)

    @app.middleware("http")
    async def request_logging_middleware(request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid4().hex)
        request.state.request_id = request_id

        headers_dict = dict(request.headers)
        content_type = request.headers.get("content-type", "")

        req_body_desc = ""
        if "application/json" in content_type:
            raw_body = await request.body()
            req_body_desc = raw_body.decode("utf-8", errors="replace")
        elif "multipart" in content_type:
            req_body_desc = f"[multipart form-data: {content_type}]"

        trace_logger.info(
            "--> %s %s [id=%s]\nHeaders: %s\nBody: %s",
            request.method,
            request.url.path + (f"?{request.url.query}" if request.url.query else ""),
            request_id,
            json.dumps(headers_dict, ensure_ascii=False),
            req_body_desc or "(empty)",
        )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        chunks = [chunk async for chunk in response.body_iterator]
        async def _re_iterator():
            for c in chunks:
                yield c
        response.body_iterator = _re_iterator()

        body_bytes = b"".join(chunks)
        resp_text = body_bytes.decode("utf-8", errors="replace")
        if len(resp_text) > 4000:
            resp_text = resp_text[:4000] + "... [truncated]"

        trace_logger.info(
            "<-- %d %s %s [id=%s]\nHeaders: %s\nBody: %s",
            response.status_code,
            request.method,
            request.url.path,
            request_id,
            json.dumps(dict(response.headers), ensure_ascii=False),
            resp_text or "(empty)",
        )
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

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def web_ui() -> HTMLResponse:
        return page()

    @app.get("/api/documents", response_model=list[DocumentResponse])
    def list_documents(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[DocumentResponse]:
        with session_factory() as session:
            statement = select(Document).order_by(Document.id.desc()).offset(offset).limit(limit)
            return [DocumentResponse.model_validate(item) for item in session.scalars(statement).all()]

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
                engine=AuditEngine(entity_extractor=entity_extractor),
                neural_interpreter=neural_interpreter,
                neural_mode="required",
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

    @app.get("/api/reports", response_model=list[ReportListResponse])
    def list_reports(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[ReportListResponse]:
        with session_factory() as session:
            statement = (
                select(AuditReport, Document.title)
                .join(Document, Document.id == AuditReport.document_id)
                .order_by(AuditReport.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            result = []
            for report, document_title in session.execute(statement):
                summary = _parse_summary(report.summary)
                neural = summary.get("neural", {})
                result.append(
                    ReportListResponse(
                        id=report.id,
                        document_id=report.document_id,
                        document_title=document_title,
                        total_findings=report.total_findings,
                        critical_count=report.critical_count,
                        high_count=report.high_count,
                        medium_count=report.medium_count,
                        low_count=report.low_count,
                        created_at=report.created_at,
                        neural_status=neural.get("status", "not_requested"),
                    )
                )
            return result

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
                if "UNIQUE constraint failed" in str(exc.orig):
                    raise ApiError(409, "rule_conflict", "Rule code already exists") from exc
                logger.exception("Could not persist rule %s", payload.rule_code)
                raise ApiError(
                    500,
                    "rule_persistence_error",
                    "Rule could not be saved; check the database schema",
                ) from exc
            response = _rule_response(rule)
        try:
            rebuild_rag_index()
        except Exception as exc:
            logger.exception("Could not rebuild RAG index after rule creation")
            raise ApiError(
                503, "rag_index_error", "Rule saved, but RAG index rebuild failed"
            ) from exc
        return response

    @app.delete("/api/rules/{rule_id}", status_code=204)
    def delete_rule(rule_id: int) -> None:
        with session_factory.begin() as session:
            rule = session.get(AuditRule, rule_id)
            if rule is None:
                raise ApiError(404, "rule_not_found", "Audit rule does not exist")
            session.delete(rule)
        try:
            rebuild_rag_index()
        except Exception as exc:
            logger.exception("Could not rebuild RAG index after rule deletion")
            raise ApiError(
                503, "rag_index_error", "Rule deleted, but RAG index rebuild failed"
            ) from exc

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

    @app.get("/api/legal-acts/{legal_act_id}", response_model=LegalActDetailResponse)
    def get_legal_act(legal_act_id: int) -> LegalActDetailResponse:
        with session_factory() as session:
            legal_act = session.get(LegalAct, legal_act_id)
            if legal_act is None:
                raise ApiError(404, "legal_act_not_found", "Legal act does not exist")
            return LegalActDetailResponse.model_validate(legal_act)

    @app.post("/api/legal-acts", response_model=LegalActResponse, status_code=201)
    def create_legal_act(payload: LegalActCreate) -> LegalActResponse:
        with session_factory.begin() as session:
            legal_act = LegalAct(**payload.model_dump())
            session.add(legal_act)
            session.flush()
            response = LegalActResponse.model_validate(legal_act)
            _rebuild_after_mutation(rebuild_rag_index)
            return response

    @app.post("/api/legal-acts/upload", response_model=LegalActResponse, status_code=201)
    async def upload_legal_act(
        file: UploadFile = File(...),
        code: str = Form(...),
        title: str = Form(...),
        number: str | None = Form(default=None),
        source_url: str | None = Form(default=None),
    ) -> LegalActResponse:
        path = None
        try:
            path, _ = await store_upload(file, config.upload_dir, config.max_upload_bytes)
            parsed = parse_document(path, max_size_bytes=config.max_upload_bytes)
            if parsed.source.format != "txt":
                raise ApiError(415, "unsupported_legal_act_format", "Legal acts must be TXT files")
            logger.info(
                "Upload legal act: code='%s', title='%s', number='%s', neural_mode='required'",
                code, title, number,
            )
            with session_factory.begin() as session:
                legal_act = LegalAct(
                    code=code,
                    title=title,
                    number=number,
                    source_url=source_url,
                    article_text=parsed.text,
                )
                session.add(legal_act)
                session.flush()
                legal_act_id = legal_act.id
                response = LegalActResponse.model_validate(legal_act)
            logger.info("Saved legal act id=%d. Extracting rules...", legal_act_id)

            generated_rules: tuple[dict[str, object], ...] = ()
            if rule_extractor is not None:
                logger.info("Executing rule extractor (%s)...", type(rule_extractor).__name__)
                try:
                    raw_extracted = rule_extractor.extract_rules(parsed.text)
                    logger.info("Rule extractor returned %d raw items", len(raw_extracted))
                    generated_rules = tuple(
                        item for item in raw_extracted
                        if isinstance(item, dict)
                    )
                except (RuntimeError, ValueError, TypeError) as exc:
                    logger.exception("Could not extract rules from legal act: %s", exc)
                    raise ApiError(
                        503,
                        "rule_extraction_error",
                        "Online rule extraction failed",
                    ) from exc
            else:
                logger.warning(
                    "rule_extractor is unavailable despite required online configuration",
                )
                raise ApiError(
                    503,
                    "rule_extraction_unavailable",
                    "Online rule extraction is not configured",
                )

            with session_factory.begin() as session:
                legal_act = session.get(LegalAct, legal_act_id)
                if legal_act is None:
                    raise ApiError(
                        500, "legal_act_not_found", "Saved legal act is unavailable"
                    )
                logger.info("Processing %d generated rules...", len(generated_rules))
                created_rules_count = 0
                for index, generated in enumerate(generated_rules, start=1):
                    rule = _generated_rule(generated, index=index)
                    if rule is None:
                        logger.warning("Generated rule #%d was rejected by validator", index)
                        continue
                    existing = session.scalar(
                        select(AuditRule.id).where(
                            AuditRule.rule_code == rule["rule_code"]
                        )
                    )
                    if existing is not None:
                        logger.warning(
                            "Rule code '%s' already exists in database (rule id=%d)! Skipping to avoid duplicate.",
                            rule["rule_code"], existing,
                        )
                        continue
                    session.add(AuditRule(legal_act_id=legal_act.id, **rule))
                    created_rules_count += 1
                    logger.info("Created generated rule #%d", index)
                logger.info("Finished rule persistence. Total new rules created: %d", created_rules_count)
            _rebuild_after_mutation(rebuild_rag_index)
            return response
        except ValueError as exc:
            raise ApiError(413, "document_too_large", str(exc)) from exc
        except DocumentParserError as exc:
            if path is not None:
                path.unlink(missing_ok=True)
            raise parser_error(exc) from exc

    @app.patch("/api/legal-acts/{legal_act_id}", response_model=LegalActResponse)
    def update_legal_act(
        legal_act_id: int, payload: LegalActUpdate
    ) -> LegalActResponse:
        with session_factory.begin() as session:
            legal_act = session.get(LegalAct, legal_act_id)
            if legal_act is None:
                raise ApiError(404, "legal_act_not_found", "Legal act does not exist")
            for field, value in payload.model_dump(exclude_unset=True).items():
                setattr(legal_act, field, value)
            session.flush()
            response = LegalActResponse.model_validate(legal_act)
        _rebuild_after_mutation(rebuild_rag_index)
        return response

    @app.delete("/api/legal-acts/{legal_act_id}", status_code=204)
    def delete_legal_act(legal_act_id: int) -> None:
        with session_factory.begin() as session:
            legal_act = session.get(LegalAct, legal_act_id)
            if legal_act is None:
                raise ApiError(404, "legal_act_not_found", "Legal act does not exist")
            rule_ids = session.scalars(
                select(AuditRule.id).where(AuditRule.legal_act_id == legal_act_id)
            ).all()
            if rule_ids:
                session.execute(
                    update(AuditFinding)
                    .where(AuditFinding.rule_id.in_(rule_ids))
                    .values(rule_id=None)
                )
            session.execute(
                update(AuditFinding)
                .where(AuditFinding.legal_act_id == legal_act_id)
                .values(legal_act_id=None)
            )
            session.execute(
                delete(AuditRule).where(AuditRule.legal_act_id == legal_act_id)
            )
            session.delete(legal_act)
        _rebuild_after_mutation(rebuild_rag_index)

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


def _rebuild_after_mutation(rebuild: Callable[[], None]) -> None:
    try:
        rebuild()
    except Exception as exc:
        logger.exception("Could not rebuild RAG index after legal-act mutation")
        raise ApiError(
            503, "rag_index_error", "Legal act saved, but RAG index rebuild failed"
        ) from exc

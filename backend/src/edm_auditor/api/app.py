"""FastAPI application factory and endpoint implementation."""

import json
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, File, Form, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, inspect as inspect_schema, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session, selectinload

from edm_auditor.applicability import (
    ApplicabilityScope,
    InvalidSelection,
    RagCandidate,
    ResolutionResult,
    ResolutionStatus,
    SelectionConfig,
    SelectionMode,
)
from edm_auditor.applicability.rule_scope import (
    SOURCE_LEGAL_ACT,
    SOURCE_LLM,
    SOURCE_MANUAL,
    SOURCE_MIGRATION,
    RuleApplicability,
    apply_rule_applicability,
    generated_rule_applicability,
    split_generated_rule,
)
from edm_auditor.audit_engine.persistence import AuditPersistence, AuditSelectionRequired
from edm_auditor.audit_engine import AuditEngine, ChunkedEntityExtractor, LLMInterpreter
from edm_auditor.audit_engine.neural_errors import AuditModelError, DocumentTooLargeForAudit
from edm_auditor.database import (
    Base,
    DocumentRepository,
    create_engine_for,
    create_session_factory,
)
from edm_auditor.classification import (
    ClassificationModelError,
    ClassificationStatus,
    DocumentClassifier,
)
from edm_auditor.classification.store import (
    DocumentClassificationService,
    document_type_options,
    ensure_default_document_types,
    override_classification,
    record_type_suggestion,
    stored_classification,
)
from edm_auditor.database.enums import AuditSeverity, CheckType
from edm_auditor.database.models import (
    AuditFinding,
    AuditReport,
    AuditRule,
    Document,
    DocumentType,
    DocumentTypeSuggestion,
    LegalAct,
    RuleExtractionResult,
    document_confirmed_types,
    legal_act_document_types,
    rule_document_types,
)
from edm_auditor.document_parser import parse_document
from edm_auditor.document_parser.exceptions import DocumentParserError
from edm_auditor.model_config import ModelSettings, detect_source_language
from edm_auditor.model_providers import (
    ModelRateLimited,
    ModelRequestTimeout,
    create_document_classification_provider,
    create_entity_extraction_provider,
    create_llm_provider,
    create_rule_extraction_provider,
)
from edm_auditor.model_providers import create_embedding_provider
from edm_auditor.report_export import (
    EXPORT_FORMATS,
    ExportedDocument,
    export_report,
)
from edm_auditor.rule_validation import (
    RuleValidationError,
    validate_generated_rule,
    validate_manual_rule_parameters,
)
from edm_auditor.rag import (
    DatabaseIndexSourceLoader,
    RAGIndexer,
    RAGSearch,
    SQLiteVectorStore,
    chunk_text,
    normalize_source_text,
)

from .config import ApiSettings
from .errors import ApiError, parser_error
from .schemas import (
    AuditPreviewResponse,
    AuditRequestResponse,
    AuditSelectionRequest,
    ClassificationUpdate,
    DocumentDetailResponse,
    DocumentTypeCreate,
    DocumentTypeResponse,
    DocumentTypeSuggestionAccept,
    DocumentTypeSuggestionResponse,
    DocumentTypeUpdate,
    RagRecommendationResponse,
    RuleApplicabilityUpdate,
    RuleDecisionResponse,
    DocumentResponse,
    FindingResponse,
    LegalActResponse,
    LegalActCreate,
    LegalActDetailResponse,
    LegalActUpdate,
    LatestReportSummary,
    ReportResponse,
    ReportListResponse,
    RuleCreate,
    RuleResponse,
    RuleUpdate,
    LegalActDiagnosticsResponse,
    RuleExtractionDiagnosticResponse,
)
from .storage import store_upload

logger = logging.getLogger("edm_auditor.api")
trace_logger = logging.getLogger("edm_auditor.trace")

# A document without a stored result: it is classified again before an audit.
CLASSIFICATION_PENDING = "pending"
NEEDS_REPROCESSING = "needs_reprocessing"
RAG_RECOMMENDATION_THRESHOLD = 0.5
RAG_RECOMMENDATION_LIMIT = 5
RAG_QUERY_CHARS = 2000
RAG_INDEXED_RULE_FIELDS = ("name", "description", "is_active")


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
        _require_current_schema(engine)
        session_factory = create_session_factory(engine)
    ensure_default_document_types(session_factory)

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
        count = RAGIndexer(
            SQLiteVectorStore(
                ":memory:",
                embedding_model=provider.model_name,
                dimension=provider.dimension,
                chunking_version="paragraph-v1",
            ),
            provider,
            max_chars=model_settings.processing.chunking.max_chars,
            overlap_chars=model_settings.processing.chunking.overlap_chars,
        ).build_atomic(
            DatabaseIndexSourceLoader(session_factory).load(),
            config.rag_index_path,
        )
        logger.info("Rebuilt RAG index: %s chunks", count)

    app.state.rebuild_rag_index = rebuild_rag_index
    model_settings = ModelSettings.from_toml(
        config.model_config,
        source_language=config.source_language,
    )
    neural_interpreter = LLMInterpreter(create_llm_provider(model_settings.llm))
    if model_settings.extractor is None:
        raise ValueError("configured model preset must declare an online extractor")
    provider = create_entity_extraction_provider(model_settings.extractor)
    document_processing = model_settings.document_processing
    entity_extractor = ChunkedEntityExtractor(
        provider,
        max_chars=document_processing.entity_chunk_max_chars,
        overlap_chars=document_processing.entity_chunk_overlap_chars,
        max_chunks=document_processing.entity_max_chunks,
        delay_seconds=model_settings.extractor.inter_chunk_delay_seconds,
    )
    rule_extractor = create_rule_extraction_provider(model_settings.extractor)
    classification = DocumentClassificationService(
        session_factory,
        DocumentClassifier(
            create_document_classification_provider(model_settings.extractor),
            min_confidence=document_processing.classification_min_confidence,
            head_chars=document_processing.classification_head_chars,
            tail_chars=document_processing.classification_tail_chars,
        ),
    )

    def rag_recommendations(text: str) -> list[RagCandidate]:
        """Find related legal context; the resolver only reports these results."""
        if not config.rag_index_path.exists():
            return []
        embedding = create_embedding_provider(model_settings.embedding)
        store = SQLiteVectorStore(
            config.rag_index_path,
            embedding_model=embedding.model_name,
            dimension=embedding.dimension,
            chunking_version="paragraph-v1",
        )
        return [
            RagCandidate(
                legal_act_id=result.chunk.legal_act_id,
                rule_id=result.chunk.rule_id,
                score=result.score,
                threshold=RAG_RECOMMENDATION_THRESHOLD,
            )
            for result in RAGSearch(store, embedding).search(
                text[:RAG_QUERY_CHARS], k=RAG_RECOMMENDATION_LIMIT
            )
        ]

    def audit_persistence() -> AuditPersistence:
        return AuditPersistence(
            session_factory,
            engine=AuditEngine(entity_extractor=entity_extractor),
            neural_interpreter=neural_interpreter,
            rag_recommender=rag_recommendations,
        )

    def ensure_classified(document_id: int) -> None:
        """Rules depend on the document type, so a missing result stops the request."""
        try:
            classification.ensure_classified(document_id)
        except ClassificationModelError as exc:
            raise _classification_error(exc) from exc

    def process_legal_act(legal_act_id: int) -> None:
        """Extract, validate, and atomically publish generated rules."""
        with session_factory() as session:
            legal_act = session.get(LegalAct, legal_act_id)
            if legal_act is None:
                raise ApiError(404, "legal_act_not_found", "Legal act does not exist")
            source_text = legal_act.article_text
            source_code = legal_act.code
            source_title = legal_act.title
            catalog = document_type_options(session)
        catalog_codes = {item.code for item in catalog}

        source_language = model_settings.processing.source_language
        if source_language == "auto":
            source_language = detect_source_language(source_text)
        chunks = chunk_text(
            source_text,
            legal_act_id=legal_act_id,
            max_chars=model_settings.processing.chunking.max_chars,
            overlap_chars=model_settings.processing.chunking.overlap_chars,
        )
        processing_version = model_settings.processing.processing_version
        with session_factory.begin() as session:
            legal_act = session.get(LegalAct, legal_act_id)
            legal_act.processing_status = "processing"
            legal_act.processing_version = processing_version
            legal_act.chunks_total = len(chunks)
            legal_act.chunks_processed = 0
            legal_act.rules_accepted = 0
            legal_act.rules_rejected = 0
            session.execute(
                delete(RuleExtractionResult).where(
                    RuleExtractionResult.legal_act_id == legal_act_id
                )
            )

        validated_rules: list[dict[str, object]] = []
        failed_chunks = 0
        accepted_chunks = 0
        model_failure: Exception | None = None
        for chunk_index, chunk in enumerate(chunks):
            if chunk_index:
                delay = model_settings.extractor.inter_chunk_delay_seconds
                if delay:
                    time.sleep(delay)
            chunk_rules: list[dict[str, object]] = []
            chunk_error: RuleValidationError | None = None
            try:
                raw_extracted = rule_extractor.extract_rules(
                    chunk.text,
                    source_language=source_language,
                    source_location=chunk.chunk_id,
                    document_types=catalog,
                    legal_act_title=source_title,
                )
                for item in raw_extracted:
                    if not isinstance(item, dict):
                        chunk_error = RuleValidationError(
                            "invalid_schema", "provider returned a non-object rule"
                        )
                        break
                    rule_fields, model_applicability, suggestion = split_generated_rule(
                        item, catalog_codes
                    )
                    normalized = validate_generated_rule(
                        rule_fields,
                        source_text=chunk.text,
                        source_language=source_language,
                        source_location=chunk.chunk_id,
                        index=len(chunk_rules) + 1,
                    )
                    normalized["source_start"] = chunk.start_char + normalized["source_start"]
                    normalized["source_end"] = chunk.start_char + normalized["source_end"]
                    normalized["_chunk_id"] = chunk.chunk_id
                    normalized["_chunk_index"] = chunk_index
                    normalized["_applicability"] = model_applicability.to_json()
                    normalized["_suggestion"] = suggestion
                    chunk_rules.append(normalized)
            except (RuntimeError, ValueError, TypeError) as exc:
                chunk_error = (
                    exc if isinstance(exc, RuleValidationError)
                    else RuleValidationError("extraction_failed", type(exc).__name__)
                )
                if isinstance(exc, (ModelRateLimited, ModelRequestTimeout)):
                    model_failure = exc
                    chunk_error = RuleValidationError(
                        _model_failure(exc, ApiError(503, "", "")).code, str(exc)
                    )
            if chunk_error is not None:
                failed_chunks += 1
                with session_factory.begin() as session:
                    session.add(
                        RuleExtractionResult(
                            legal_act_id=legal_act_id,
                            chunk_id=chunk.chunk_id,
                            status="failed",
                            error_code=chunk_error.code,
                            diagnostic_message=str(chunk_error)[:1000],
                            rules_total=0,
                            processing_version=processing_version,
                        )
                    )
                if model_failure is not None:
                    # The remaining chunks would fail the same way and use up the limit.
                    break
                continue
            accepted_chunks += 1
            validated_rules.extend(chunk_rules)
            with session_factory.begin() as session:
                session.add(
                    RuleExtractionResult(
                        legal_act_id=legal_act_id,
                        chunk_id=chunk.chunk_id,
                        status="accepted",
                        rules_total=len(chunk_rules),
                        rules_accepted=len(chunk_rules),
                        processing_version=processing_version,
                    )
                )

        if failed_chunks:
            with session_factory.begin() as session:
                legal_act = session.get(LegalAct, legal_act_id)
                legal_act.processing_status = "failed"
                legal_act.chunks_processed = accepted_chunks
            raise _model_failure(
                model_failure,
                ApiError(
                    503,
                    "rule_extraction_error",
                    f"Online rule extraction failed for {failed_chunks} chunk(s)",
                ),
            )

        with session_factory.begin() as session:
            legal_act = session.get(LegalAct, legal_act_id)
            old_rule_ids = session.scalars(
                select(AuditRule.id).where(
                    AuditRule.legal_act_id == legal_act_id,
                    AuditRule.is_generated.is_(True),
                )
            ).all()
            if old_rule_ids:
                session.execute(
                    update(AuditFinding)
                    .where(AuditFinding.rule_id.in_(old_rule_ids))
                    .values(rule_id=None)
                )
                session.execute(
                    delete(AuditRule).where(AuditRule.id.in_(old_rule_ids))
                )
            published = 0
            duplicates = 0
            for index, generated in enumerate(validated_rules, start=1):
                parameters_json = generated["parameters_json"]
                deduplication_key = hashlib.sha256(
                    f"{legal_act_id}|{generated['source_start']}|{generated['source_end']}|"
                    f"{generated['check_type']}|{parameters_json}".encode("utf-8")
                ).hexdigest()
                existing = session.scalar(
                    select(AuditRule.id).where(
                        AuditRule.deduplication_key == deduplication_key
                    )
                )
                if existing is not None:
                    duplicates += 1
                    continue
                chunk_id = str(generated["_chunk_id"])
                rule_code = (
                    f"{source_code}-{chunk_id.rsplit(':', 1)[-1]}-{index:03d}-"
                    f"{deduplication_key[:8]}"
                )[:100]
                generated_rule = AuditRule(
                        legal_act_id=legal_act_id,
                        is_generated=True,
                        deduplication_key=deduplication_key,
                        source_quote=generated["source_quote"],
                        source_location=chunk_id,
                        source_start=generated["source_start"],
                        source_end=generated["source_end"],
                        rule_code=rule_code,
                        name=generated["name"],
                        severity=generated["severity"],
                        description=generated["description"],
                        check_type=generated["check_type"],
                        parameters_json=parameters_json,
                )
                generated_rule.applicability_auto = generated["_applicability"]
                apply_rule_applicability(
                    generated_rule,
                    generated_rule_applicability(
                        session,
                        legal_act,
                        generated["_applicability"],
                        min_confidence=document_processing.classification_min_confidence,
                    ),
                )
                session.add(generated_rule)
                if generated["_suggestion"] is not None:
                    record_type_suggestion(
                        session, generated["_suggestion"], legal_act_id=legal_act_id
                    )
                published += 1
            legal_act.processing_status = "completed" if duplicates == 0 else "partial"
            legal_act.chunks_processed = len(chunks)
            legal_act.rules_accepted = published
            legal_act.rules_rejected = duplicates
            if duplicates:
                session.execute(
                    update(RuleExtractionResult)
                    .where(RuleExtractionResult.legal_act_id == legal_act_id)
                    .values(
                        status="partial",
                        rules_rejected=duplicates,
                        diagnostic_message="duplicate generated rules were not published",
                    )
                )

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
        return _error_response(
            request, 422, "validation_error", _validation_message(exc.errors())
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request, exc):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request, exc):
        logger.exception("Unhandled error", exc_info=exc)
        return _error_response(request, 500, "internal_error", "Internal server error")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/document-types", response_model=list[DocumentTypeResponse])
    def list_document_types(
        include_inactive: bool = False,
    ) -> list[DocumentTypeResponse]:
        with session_factory() as session:
            statement = select(DocumentType).order_by(DocumentType.code)
            if not include_inactive:
                statement = statement.where(DocumentType.is_active.is_(True))
            return [
                DocumentTypeResponse.model_validate(item)
                for item in session.scalars(statement).all()
            ]

    @app.post("/api/document-types", response_model=DocumentTypeResponse, status_code=201)
    def create_document_type(payload: DocumentTypeCreate) -> DocumentTypeResponse:
        with session_factory.begin() as session:
            document_type = _save_document_type(
                session, payload.code, payload.name, payload.description
            )
            session.flush()
            return DocumentTypeResponse.model_validate(document_type)

    @app.patch("/api/document-types/{code}", response_model=DocumentTypeResponse)
    def update_document_type(code: str, payload: DocumentTypeUpdate) -> DocumentTypeResponse:
        """Models read the name and the description when they choose a type."""
        with session_factory.begin() as session:
            document_type = session.get(DocumentType, code)
            if document_type is None:
                raise ApiError(404, "document_type_not_found", "Document type does not exist")
            for field, value in payload.model_dump(exclude_unset=True).items():
                setattr(document_type, field, value)
            session.flush()
            return DocumentTypeResponse.model_validate(document_type)

    @app.get(
        "/api/document-type-suggestions",
        response_model=list[DocumentTypeSuggestionResponse],
    )
    def list_document_type_suggestions(
        status: str = "pending",
    ) -> list[DocumentTypeSuggestionResponse]:
        with session_factory() as session:
            return [
                DocumentTypeSuggestionResponse.model_validate(item)
                for item in session.scalars(
                    select(DocumentTypeSuggestion)
                    .where(DocumentTypeSuggestion.status == status)
                    .order_by(DocumentTypeSuggestion.id)
                ).all()
            ]

    @app.post(
        "/api/document-type-suggestions/{suggestion_id}/accept",
        response_model=DocumentTypeResponse,
        status_code=201,
    )
    def accept_document_type_suggestion(
        suggestion_id: int, payload: DocumentTypeSuggestionAccept
    ) -> DocumentTypeResponse:
        """Add the suggested type; existing documents and rules are classified again on request."""
        with session_factory.begin() as session:
            suggestion = _pending_suggestion(session, suggestion_id)
            document_type = _save_document_type(
                session,
                payload.code,
                payload.name or suggestion.name,
                payload.description or suggestion.reason or suggestion.name,
            )
            suggestion.status = "accepted"
            suggestion.accepted_code = payload.code
            session.flush()
            return DocumentTypeResponse.model_validate(document_type)

    @app.post(
        "/api/document-type-suggestions/{suggestion_id}/dismiss", status_code=204
    )
    def dismiss_document_type_suggestion(suggestion_id: int) -> None:
        with session_factory.begin() as session:
            _pending_suggestion(session, suggestion_id).status = "dismissed"

    @app.delete("/api/document-types/{code}", status_code=204)
    def delete_document_type(code: str) -> None:
        """Deactivate a type: historical links keep referring to a stable code."""
        with session_factory.begin() as session:
            document_type = session.get(DocumentType, code)
            if document_type is None:
                raise ApiError(404, "document_type_not_found", "Document type does not exist")
            dependencies = _document_type_dependencies(session, code)
            if dependencies:
                raise ApiError(
                    409,
                    "document_type_in_use",
                    f"Document type is used by: {', '.join(dependencies)}",
                )
            document_type.is_active = False

    @app.get("/api/documents", response_model=list[DocumentResponse])
    def list_documents(
        response: Response,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[DocumentResponse]:
        with session_factory() as session:
            statement = select(Document)
            _set_total_count(session, response, statement)
            statement = statement.order_by(Document.id.desc()).offset(offset).limit(limit)
            return [_document_response(item) for item in session.scalars(statement).all()]

    @app.post("/api/documents/upload", response_model=DocumentResponse, status_code=201)
    async def upload_document(
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
    ) -> DocumentResponse:
        try:
            path, _ = await store_upload(
                file, config.upload_dir, config.max_upload_bytes
            )
        except ValueError as exc:
            raise ApiError(413, "document_too_large", str(exc)) from exc
        try:
            parsed = parse_document(path, max_size_bytes=config.max_upload_bytes)
            if not parsed.text.strip():
                path.unlink(missing_ok=True)
                raise _empty_document_error()
            repository = DocumentRepository(session_factory)
            document = repository.save_parsed_document(
                parsed,
                title=title or Path(file.filename or path.name).stem,
                file_path=path,
            )
            document_id = document.id
        except DocumentParserError as exc:
            path.unlink(missing_ok=True)
            raise parser_error(exc) from exc
        try:
            await run_in_threadpool(classification.classify, document_id)
        except ClassificationModelError:
            # The upload itself succeeded; the type is requested again before an audit.
            logger.warning("Document %s was saved without a type", document_id)
        with session_factory() as session:
            return _document_response(session.get(Document, document_id))

    @app.get("/api/documents/{document_id}", response_model=DocumentDetailResponse)
    def get_document(document_id: int) -> DocumentDetailResponse:
        with session_factory() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise ApiError(404, "document_not_found", "Document does not exist")
            return DocumentDetailResponse(
                **_document_response(document).model_dump(), text=document.raw_text
            )

    @app.delete("/api/documents/{document_id}", status_code=204)
    def delete_document(document_id: int) -> None:
        """Delete the document with its reports; the file goes once the data is gone."""
        with session_factory.begin() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise ApiError(404, "document_not_found", "Document does not exist")
            file_path = Path(document.file_path)
            session.delete(document)
        _remove_upload(file_path, config.upload_dir)

    @app.post(
        "/api/documents/{document_id}/classify",
        response_model=DocumentResponse,
    )
    def classify_document_endpoint(document_id: int) -> DocumentResponse:
        try:
            classification.classify(document_id)
        except LookupError as exc:
            raise ApiError(404, "document_not_found", "Document does not exist") from exc
        except ClassificationModelError as exc:
            raise _classification_error(exc) from exc
        with session_factory() as session:
            return _document_response(session.get(Document, document_id))

    @app.patch(
        "/api/documents/{document_id}/classification",
        response_model=DocumentResponse,
    )
    def update_classification(
        document_id: int, payload: ClassificationUpdate
    ) -> DocumentResponse:
        with session_factory.begin() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise ApiError(404, "document_not_found", "Document does not exist")
            types = _active_document_types(session, payload.confirmed_document_types)
            override_classification(session, document, [item.code for item in types])
            session.flush()
            return _document_response(document)

    @app.post(
        "/api/documents/{document_id}/audit/preview",
        response_model=AuditPreviewResponse,
    )
    def preview_audit(
        document_id: int, selection: AuditSelectionRequest | None = None
    ) -> AuditPreviewResponse:
        ensure_classified(document_id)
        requested = _selection_config(session_factory, selection)
        try:
            resolution = audit_persistence().preview(document_id, requested)
        except LookupError as exc:
            raise ApiError(404, "document_not_found", str(exc)) from exc
        with session_factory() as session:
            classification = stored_classification(session.get(Document, document_id))
        return AuditPreviewResponse(
            document_id=document_id,
            status=resolution.status.value,
            selection_mode=requested.mode.value,
            classification_status=classification.status.value,
            classification_confidence=classification.confidence,
            confirmed_document_types=list(classification.confirmed_document_types),
            candidate_document_types=[
                item.as_dict() for item in classification.candidate_types
            ],
            selected_rule_ids=list(resolution.selected_rule_ids),
            decisions=[
                RuleDecisionResponse(
                    rule_id=item.rule_id,
                    rule_code=item.rule_code,
                    name=item.name,
                    legal_act_id=item.legal_act_id,
                    applicability_scope=item.applicability_scope,
                    document_types=list(item.document_types),
                    selected=item.selected,
                    reason=item.reason.value,
                )
                for item in resolution.decisions
            ],
            warnings=[item.value for item in resolution.warnings],
            rag_recommendations=[
                RagRecommendationResponse(
                    legal_act_id=item.legal_act_id,
                    rule_id=item.rule_id,
                    score=item.score,
                    threshold=item.threshold,
                    reason=item.reason,
                )
                for item in resolution.recommendations
            ],
        )

    @app.post(
        "/api/documents/{document_id}/audit",
        response_model=AuditRequestResponse,
    )
    def audit_document(
        document_id: int, selection: AuditSelectionRequest | None = None
    ) -> AuditRequestResponse:
        ensure_classified(document_id)
        try:
            report = audit_persistence().audit_document(
                document_id, _selection_config(session_factory, selection)
            )
        except LookupError as exc:
            raise ApiError(404, "document_not_found", str(exc)) from exc
        except AuditSelectionRequired as exc:
            raise _selection_error(exc.resolution) from exc
        except DocumentTooLargeForAudit as exc:
            raise ApiError(413, "document_too_large_for_audit", str(exc)) from exc
        except AuditModelError as exc:
            logger.exception("Audit of document %s failed", document_id)
            raise _model_failure(
                exc,
                ApiError(503, "model_provider_error", f"Audit was not completed: {exc}"),
            ) from exc
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
                statement = statement.order_by(
                    AuditReport.created_at.desc(), AuditReport.id.desc()
                )
            report = session.scalar(statement)
            if report is None:
                raise ApiError(404, "report_not_found", "Audit report does not exist")
            return _report_response(report)

    @app.get("/api/reports/{report_id}", response_model=ReportResponse)
    def get_report_by_id(report_id: int) -> ReportResponse:
        with session_factory() as session:
            report = session.get(AuditReport, report_id)
            if report is None:
                raise ApiError(404, "report_not_found", "Audit report does not exist")
            return _report_response(report)

    @app.get(
        "/api/reports/{report_id}/export",
        response_class=Response,
        responses={200: {"content": {"text/html": {}}, "description": "The report file"}},
    )
    def export_report_file(
        report_id: int,
        export_format: str = Query(default="html", alias="format"),
        timezone: str = Query(default="UTC", max_length=100),
    ) -> Response:
        """Download the report as a file; dates are shown in the given IANA time zone."""
        if export_format not in EXPORT_FORMATS:
            raise ApiError(
                422,
                "unsupported_export_format",
                f"Supported formats: {', '.join(EXPORT_FORMATS)}",
            )
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ApiError(422, "invalid_timezone", f"Unknown time zone: {timezone}") from exc
        with session_factory() as session:
            report = session.get(AuditReport, report_id)
            if report is None:
                raise ApiError(404, "report_not_found", "Audit report does not exist")
            document = ExportedDocument(
                title=report.document.title,
                file_type=report.document.file_type,
                text=report.document.raw_text,
            )
            exported = export_report(_report_response(report), document, export_format, zone)
        return Response(
            content=exported.content,
            media_type=exported.media_type,
            headers={"Content-Disposition": exported.content_disposition},
        )

    @app.get("/api/reports", response_model=list[ReportListResponse])
    def list_reports(
        response: Response,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        document_id: int | None = Query(default=None),
    ) -> list[ReportListResponse]:
        with session_factory() as session:
            statement = select(AuditReport, Document.title).join(
                Document, Document.id == AuditReport.document_id
            )
            if document_id is not None:
                statement = statement.where(AuditReport.document_id == document_id)
            _set_total_count(session, response, statement)
            statement = (
                statement.order_by(AuditReport.created_at.desc(), AuditReport.id.desc())
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
                        selection_mode=summary.get("selection", {}).get("selection_mode"),
                    )
                )
            return result

    @app.get("/api/rules", response_model=list[RuleResponse])
    def list_rules(
        response: Response,
        is_active: bool | None = None,
        document_type: str | None = None,
        check_type: str | None = None,
        applicability_scope: ApplicabilityScope | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[RuleResponse]:
        with session_factory() as session:
            statement = select(AuditRule)
            if is_active is not None:
                statement = statement.where(AuditRule.is_active.is_(is_active))
            if document_type is not None:
                statement = statement.join(rule_document_types).where(
                    rule_document_types.c.document_type_code == document_type
                )
            if check_type is not None:
                statement = statement.where(AuditRule.check_type == check_type)
            if applicability_scope is not None:
                statement = statement.where(
                    AuditRule.applicability_scope == applicability_scope.value
                )
            _set_total_count(session, response, statement)
            statement = statement.order_by(AuditRule.id).offset(offset).limit(limit)
            return [
                _rule_response(rule)
                for rule in session.scalars(statement).all()
            ]

    @app.post("/api/rules", response_model=RuleResponse, status_code=201)
    def create_rule(payload: RuleCreate) -> RuleResponse:
        _require_valid_severity(payload.severity)
        _require_valid_check(payload.check_type, payload.parameters)
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
                parameters_json=json.dumps(
                    payload.parameters, ensure_ascii=False, sort_keys=True
                ),
                legal_act_id=payload.legal_act_id,
            )
            apply_rule_applicability(
                rule,
                _manual_applicability(
                    session, payload.applicability_scope, payload.document_types
                ),
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

    @app.patch("/api/rules/{rule_id}", response_model=RuleResponse)
    def update_rule(rule_id: int, payload: RuleUpdate) -> RuleResponse:
        changes = payload.model_dump(exclude_unset=True)
        if "severity" in changes:
            _require_valid_severity(changes["severity"])
        with session_factory.begin() as session:
            rule = session.get(AuditRule, rule_id)
            if rule is None:
                raise ApiError(404, "rule_not_found", "Audit rule does not exist")
            if "check_type" in changes or "parameters" in changes:
                _require_valid_check(
                    changes.get("check_type", rule.check_type),
                    changes.get("parameters", _parse_parameters(rule.parameters_json)),
                )
            if changes.get("is_active") and not rule.is_active:
                _require_active_rule_types(rule)
            indexed_change = any(
                field in changes and changes[field] != getattr(rule, field)
                for field in RAG_INDEXED_RULE_FIELDS
            )
            if "parameters" in changes:
                rule.parameters_json = json.dumps(
                    changes.pop("parameters"), ensure_ascii=False, sort_keys=True
                )
            for field, value in changes.items():
                setattr(rule, field, value)
            session.flush()
            response = _rule_response(rule)
            rebuild_index = indexed_change and rule.legal_act_id is not None
        if rebuild_index:
            try:
                rebuild_rag_index()
            except Exception as exc:
                logger.exception("Could not rebuild RAG index after rule update")
                raise ApiError(
                    503, "rag_index_error", "Rule saved, but RAG index rebuild failed"
                ) from exc
        return response

    @app.patch("/api/rules/{rule_id}/applicability", response_model=RuleResponse)
    def update_rule_applicability(
        rule_id: int, payload: RuleApplicabilityUpdate
    ) -> RuleResponse:
        with session_factory.begin() as session:
            rule = session.get(AuditRule, rule_id)
            if rule is None:
                raise ApiError(404, "rule_not_found", "Audit rule does not exist")
            apply_rule_applicability(
                rule,
                _manual_applicability(
                    session, payload.applicability_scope, payload.document_types
                ),
            )
            session.flush()
            return _rule_response(rule)

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
        response: Response,
        search: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[LegalActResponse]:
        with session_factory() as session:
            statement = select(LegalAct)
            if search:
                pattern = f"%{search}%"
                statement = statement.where(
                    (LegalAct.code.ilike(pattern)) | (LegalAct.title.ilike(pattern))
                )
            _set_total_count(session, response, statement)
            statement = statement.order_by(LegalAct.id).offset(offset).limit(limit)
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

    @app.get(
        "/api/legal-acts/{legal_act_id}/diagnostics",
        response_model=LegalActDiagnosticsResponse,
    )
    def get_legal_act_diagnostics(
        legal_act_id: int,
    ) -> LegalActDiagnosticsResponse:
        with session_factory() as session:
            legal_act = session.get(LegalAct, legal_act_id)
            if legal_act is None:
                raise ApiError(404, "legal_act_not_found", "Legal act does not exist")
            results = session.scalars(
                select(RuleExtractionResult)
                .where(RuleExtractionResult.legal_act_id == legal_act_id)
                .order_by(RuleExtractionResult.id)
            ).all()
            return LegalActDiagnosticsResponse(
                legal_act_id=legal_act.id,
                processing_status=legal_act.processing_status,
                chunks_total=legal_act.chunks_total,
                chunks_processed=legal_act.chunks_processed,
                rules_accepted=legal_act.rules_accepted,
                rules_rejected=legal_act.rules_rejected,
                diagnostics=[
                    RuleExtractionDiagnosticResponse.model_validate(result)
                    for result in results
                ],
            )

    @app.post("/api/legal-acts", response_model=LegalActResponse, status_code=201)
    def create_legal_act(payload: LegalActCreate) -> LegalActResponse:
        with session_factory.begin() as session:
            _require_free_legal_act_code(session, payload.code)
            values = payload.model_dump()
            values["article_text"] = normalize_source_text(values["article_text"])
            values["document_types"] = _active_document_types(
                session, values["document_types"]
            )
            legal_act = LegalAct(**values)
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
        document_types: str | None = Form(default=None),
    ) -> LegalActResponse:
        try:
            path, _ = await store_upload(file, config.upload_dir, config.max_upload_bytes)
        except ValueError as exc:
            raise ApiError(413, "document_too_large", str(exc)) from exc
        try:
            parsed = parse_document(path, max_size_bytes=config.max_upload_bytes)
        except DocumentParserError as exc:
            raise parser_error(exc) from exc
        finally:
            # The text is stored in the database, so the uploaded file is not needed.
            path.unlink(missing_ok=True)
        if parsed.source.format != "txt":
            raise ApiError(415, "unsupported_legal_act_format", "Legal acts must be TXT files")
        if not parsed.text.strip():
            raise _empty_document_error()
        logger.info(
            "Upload legal act: code='%s', title='%s', number='%s', neural_mode='required'",
            code, title, number,
        )
        with session_factory.begin() as session:
            _require_free_legal_act_code(session, code)
            legal_act = LegalAct(
                code=code,
                title=title,
                number=number,
                source_url=source_url,
                article_text=normalize_source_text(parsed.text),
                document_types=_active_document_types(
                    session,
                    [
                        item.strip()
                        for item in (document_types or "").split(",")
                        if item.strip()
                    ],
                ),
            )
            session.add(legal_act)
            session.flush()
            legal_act_id = legal_act.id
        logger.info("Saved legal act id=%d. Extracting rules...", legal_act_id)
        # Model and index calls block, so they must not stop the event loop.
        await run_in_threadpool(process_legal_act, legal_act_id)
        await run_in_threadpool(_rebuild_after_mutation, rebuild_rag_index)
        with session_factory() as session:
            return LegalActResponse.model_validate(session.get(LegalAct, legal_act_id))

    @app.post("/api/legal-acts/{legal_act_id}/reprocess", response_model=LegalActResponse)
    def reprocess_legal_act(legal_act_id: int) -> LegalActResponse:
        with session_factory() as session:
            if session.get(LegalAct, legal_act_id) is None:
                raise ApiError(404, "legal_act_not_found", "Legal act does not exist")
        process_legal_act(legal_act_id)
        _rebuild_after_mutation(rebuild_rag_index)
        with session_factory() as session:
            return LegalActResponse.model_validate(session.get(LegalAct, legal_act_id))

    @app.patch("/api/legal-acts/{legal_act_id}", response_model=LegalActResponse)
    def update_legal_act(
        legal_act_id: int, payload: LegalActUpdate
    ) -> LegalActResponse:
        with session_factory.begin() as session:
            legal_act = session.get(LegalAct, legal_act_id)
            if legal_act is None:
                raise ApiError(404, "legal_act_not_found", "Legal act does not exist")
            if payload.code is not None and payload.code != legal_act.code:
                _require_free_legal_act_code(session, payload.code)
            for field, value in payload.model_dump(exclude_unset=True).items():
                if field == "article_text":
                    value = normalize_source_text(value)
                    # Rules quote the old text until the act is processed again.
                    if value != legal_act.article_text and legal_act.processing_status != "uploaded":
                        legal_act.processing_status = NEEDS_REPROCESSING
                if field == "document_types":
                    value = _active_document_types(session, value or [])
                setattr(legal_act, field, value)
            session.flush()
            if payload.document_types is not None:
                _refresh_generated_rule_applicability(
                    session,
                    legal_act,
                    min_confidence=document_processing.classification_min_confidence,
                )
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


def _error_response(request, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )


def _validation_message(errors) -> str:
    """Name the field and the problem without internal details of the server."""
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in errors
    )


def _set_total_count(session: Session, response: Response, statement) -> None:
    """The body stays a plain list; a paginated client reads the total from a header."""
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    response.headers["X-Total-Count"] = str(total)


def _remove_upload(file_path: Path, upload_dir: Path) -> None:
    """Delete only inside the upload directory; a leftover file does not fail the request."""
    if not file_path.resolve().is_relative_to(upload_dir.resolve()):
        logger.warning("Document file outside the upload directory was kept")
        return
    try:
        file_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not delete a document file: %s", type(exc).__name__)


def _require_valid_severity(severity: str) -> None:
    if severity not in {item.value for item in AuditSeverity}:
        raise ApiError(422, "invalid_severity", "Unsupported severity")


def _require_active_rule_types(rule: AuditRule) -> None:
    """A deactivated type keeps its links, so enabling such a rule would bypass the deactivation."""
    if rule.applicability_scope != ApplicabilityScope.TYPED.value or not rule.document_types:
        return
    if not any(item.is_active for item in rule.document_types):
        codes = ", ".join(item.code for item in rule.document_types)
        raise ApiError(
            409,
            "rule_document_types_inactive",
            f"All document types of the rule are deactivated: {codes}. "
            "Change its applicability or reactivate a type first",
        )


def _require_valid_check(check_type: str, parameters: dict) -> None:
    if check_type not in {item.value for item in CheckType}:
        raise ApiError(422, "invalid_check_type", "Unsupported check type")
    if check_type == CheckType.SEMANTIC.value:
        raise ApiError(
            422, "unsupported_check_type", "Semantic rules are not executed by the audit"
        )
    try:
        validate_manual_rule_parameters(check_type, parameters)
    except RuleValidationError as exc:
        raise ApiError(422, "invalid_rule_parameters", str(exc)) from exc


def _report_response(report: AuditReport) -> ReportResponse:
    summary = _parse_summary(report.summary)
    contexts = summary.get("rag_contexts", [])
    neural = summary.get("neural", {})
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
        findings=[
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
                source_context=contexts[index] if index < len(contexts) else None,
                finding_key=finding.finding_key,
                rule_code=finding.rule_code,
                rule_name=finding.rule_name,
                legal_act_code=finding.legal_act_code,
                legal_act_title=finding.legal_act_title,
                norm_quote=finding.norm_quote,
            )
            for index, finding in enumerate(report.findings)
        ],
        neural_status=neural.get("status", "not_requested"),
        neural_analyses=neural.get("analyses", []),
        selection=summary.get("selection"),
    )


def _document_response(document: Document) -> DocumentResponse:
    classification = stored_classification(document)
    return DocumentResponse(
        id=document.id,
        title=document.title,
        file_type=document.file_type,
        status=document.status,
        classified_type=document.classified_type,
        classification_status=document.classification_status or CLASSIFICATION_PENDING,
        classification_confidence=document.classification_confidence,
        classification_source=document.classification_source,
        confirmed_document_types=list(classification.confirmed_document_types),
        candidate_document_types=[
            item.as_dict() for item in classification.candidate_types
        ],
        automatic_classification=(
            json.loads(document.classification_auto)
            if document.classification_auto
            else None
        ),
        needs_configuration=(
            classification.status is not ClassificationStatus.CLASSIFIED
        ),
        created_at=document.created_at,
        latest_report=_latest_report_summary(document),
    )


def _latest_report_summary(document: Document) -> LatestReportSummary | None:
    """Summarize the newest report so a document list needs no request per document."""
    session = object_session(document)
    if session is None:
        return None
    report = session.scalar(
        select(AuditReport)
        .where(AuditReport.document_id == document.id)
        .order_by(AuditReport.created_at.desc(), AuditReport.id.desc())
        .limit(1)
    )
    if report is None:
        return None
    return LatestReportSummary(
        id=report.id,
        total_findings=report.total_findings,
        critical_count=report.critical_count,
        high_count=report.high_count,
        medium_count=report.medium_count,
        low_count=report.low_count,
        created_at=report.created_at,
    )


def _save_document_type(
    session: Session, code: str, name: str, description: str
) -> DocumentType:
    """Add a type or bring back a deactivated one under the same stable code."""
    if code == "unknown":
        raise ApiError(
            422,
            "reserved_document_type",
            "'unknown' is a classification state, not a document type",
        )
    document_type = session.get(DocumentType, code)
    if document_type is not None and document_type.is_active:
        raise ApiError(409, "document_type_conflict", "Document type already exists")
    if document_type is None:
        document_type = DocumentType(code=code)
        session.add(document_type)
    document_type.name = name
    document_type.description = description
    document_type.is_active = True
    return document_type


def _require_free_legal_act_code(session: Session, code: str) -> None:
    if session.scalar(select(LegalAct.id).where(LegalAct.code == code)) is not None:
        raise ApiError(409, "legal_act_conflict", f"Legal act code already exists: {code}")


def _empty_document_error() -> ApiError:
    return ApiError(400, "empty_document", "The document contains no text")


def _pending_suggestion(session: Session, suggestion_id: int) -> DocumentTypeSuggestion:
    suggestion = session.get(DocumentTypeSuggestion, suggestion_id)
    if suggestion is None:
        raise ApiError(
            404, "document_type_suggestion_not_found", "Suggestion does not exist"
        )
    if suggestion.status != "pending":
        raise ApiError(
            409, "document_type_suggestion_closed", "Suggestion was already decided"
        )
    return suggestion


def _classification_error(error: ClassificationModelError) -> ApiError:
    return _model_failure(
        error,
        ApiError(503, "classification_model_error", f"Document type is not known: {error}"),
    )


def _model_failure(error: BaseException | None, fallback: ApiError) -> ApiError:
    """Report a limit or a timeout separately: the client can repeat the same request."""
    while error is not None:
        if isinstance(error, ModelRateLimited):
            return ApiError(
                429, "model_rate_limited", "Model request limit reached; try again in a minute"
            )
        if isinstance(error, ModelRequestTimeout):
            return ApiError(504, "model_timeout", "The model did not respond in time; try again")
        error = error.__cause__
    return fallback


def _document_type_dependencies(session: Session, code: str) -> list[str]:
    dependencies = []
    if session.scalar(
        select(func.count())
        .select_from(rule_document_types)
        .join(AuditRule, AuditRule.id == rule_document_types.c.rule_id)
        .where(
            rule_document_types.c.document_type_code == code,
            AuditRule.is_active.is_(True),
        )
    ):
        dependencies.append("active rules")
    if session.scalar(
        select(func.count())
        .select_from(document_confirmed_types)
        .where(document_confirmed_types.c.document_type_code == code)
    ):
        dependencies.append("documents")
    if session.scalar(
        select(func.count())
        .select_from(legal_act_document_types)
        .where(legal_act_document_types.c.document_type_code == code)
    ):
        dependencies.append("legal acts")
    return dependencies


def _refresh_generated_rule_applicability(
    session: Session, legal_act: LegalAct, *, min_confidence: float
) -> None:
    """Update rules derived from the act; manual decisions stay as they are."""
    for rule in legal_act.rules:
        if rule.is_generated and rule.applicability_source in (
            SOURCE_LEGAL_ACT,
            SOURCE_LLM,
            SOURCE_MIGRATION,
        ):
            apply_rule_applicability(
                rule,
                generated_rule_applicability(
                    session,
                    legal_act,
                    rule.applicability_auto,
                    min_confidence=min_confidence,
                ),
            )


def _require_current_schema(engine) -> None:
    """``create_all`` cannot add columns, so report an outdated database at startup."""
    columns = {item["name"] for item in inspect_schema(engine).get_columns("audit_rules")}
    finding_columns = {
        item["name"] for item in inspect_schema(engine).get_columns("audit_findings")
    }
    if "applicability_auto" not in columns or "finding_key" not in finding_columns:
        raise RuntimeError(
            "The database schema is outdated. Back it up and run "
            "'alembic upgrade head' (for a database that has no alembic_version table, "
            "run 'alembic stamp 0005_rule_publication_metadata' first)."
        )


def _selection_config(
    session_factory, selection: AuditSelectionRequest | None
) -> SelectionConfig:
    """Reject identifiers that do not exist instead of silently ignoring them."""
    selection = selection or AuditSelectionRequest()
    rule_ids = {*selection.included_rule_ids, *selection.excluded_rule_ids}
    with session_factory() as session:
        known_rules = set(
            session.scalars(select(AuditRule.id).where(AuditRule.id.in_(rule_ids))).all()
        )
        known_acts = set(
            session.scalars(
                select(LegalAct.id).where(LegalAct.id.in_(selection.legal_act_ids))
            ).all()
        )
    if missing := rule_ids - known_rules:
        raise ApiError(422, "unknown_rule", f"Unknown rules: {sorted(missing)}")
    if missing := set(selection.legal_act_ids) - known_acts:
        raise ApiError(422, "unknown_legal_act", f"Unknown legal acts: {sorted(missing)}")
    try:
        return SelectionConfig(
            mode=SelectionMode(selection.selection_mode),
            legal_act_ids=frozenset(selection.legal_act_ids),
            included_rule_ids=frozenset(selection.included_rule_ids),
            excluded_rule_ids=frozenset(selection.excluded_rule_ids),
            confirm_all=selection.confirm_all,
        )
    except InvalidSelection as exc:
        raise ApiError(422, "all_mode_not_confirmed", str(exc)) from exc


def _selection_error(resolution: ResolutionResult) -> ApiError:
    warnings = ", ".join(item.value for item in resolution.warnings)
    if resolution.status is ResolutionStatus.NO_APPLICABLE_RULES:
        return ApiError(409, "no_applicable_rules", f"No rules apply: {warnings}")
    return ApiError(
        409,
        "audit_configuration_required",
        f"Confirm the document type or select rules: {warnings}",
    )


def _active_document_types(session: Session, codes: list[str]) -> list[DocumentType]:
    rows = []
    for code in dict.fromkeys(codes):
        row = session.get(DocumentType, code)
        if row is None or not row.is_active:
            raise ApiError(
                422, "unknown_document_type", f"Unknown or inactive document type: {code}"
            )
        rows.append(row)
    return rows


def _manual_applicability(
    session: Session, scope: str | None, codes: list[str]
) -> RuleApplicability:
    """A rule without a type applies everywhere, as manual rules always have."""
    types = _active_document_types(session, codes)
    try:
        resolved = ApplicabilityScope(
            scope
            or (ApplicabilityScope.TYPED if types else ApplicabilityScope.UNIVERSAL)
        )
    except ValueError as exc:
        raise ApiError(
            422, "invalid_applicability_scope", "Unsupported applicability scope"
        ) from exc
    if (resolved is ApplicabilityScope.TYPED) != bool(types):
        raise ApiError(
            422,
            "invalid_applicability_scope",
            "Document types are required for the typed scope and only allowed for it",
        )
    return RuleApplicability(resolved, tuple(types), 1.0, SOURCE_MANUAL)


def _rule_response(rule: AuditRule) -> RuleResponse:
    return RuleResponse(
        id=rule.id,
        rule_code=rule.rule_code,
        name=rule.name,
        applicability_scope=rule.applicability_scope,
        document_types=[item.code for item in rule.document_types],
        applicability_confidence=rule.applicability_confidence,
        applicability_source=rule.applicability_source,
        automatic_applicability=(
            json.loads(rule.applicability_auto) if rule.applicability_auto else None
        ),
        severity=rule.severity,
        description=rule.description,
        check_type=rule.check_type,
        parameters=_parse_parameters(rule.parameters_json),
        is_active=rule.is_active,
        legal_act_id=rule.legal_act_id,
        is_generated=rule.is_generated,
        source_quote=rule.source_quote,
        source_location=rule.source_location,
        source_start=rule.source_start,
        source_end=rule.source_end,
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

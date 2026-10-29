"""Consistent API error responses."""

from fastapi import Request
from fastapi.responses import JSONResponse

from edm_auditor.document_parser.exceptions import (
    DocumentAccessError,
    DocumentTooLarge,
    InvalidDocument,
    TextLayerRequired,
    UnsupportedDocumentFormat,
)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


def api_error_response(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )


def parser_error(error: Exception) -> ApiError:
    if isinstance(error, DocumentTooLarge):
        return ApiError(413, "document_too_large", str(error))
    if isinstance(error, UnsupportedDocumentFormat):
        return ApiError(415, "unsupported_document_format", str(error))
    if isinstance(error, (InvalidDocument, TextLayerRequired)):
        return ApiError(400, "invalid_document", str(error))
    if isinstance(error, DocumentAccessError):
        return ApiError(400, "document_access_error", str(error))
    return ApiError(400, "document_parse_error", str(error))

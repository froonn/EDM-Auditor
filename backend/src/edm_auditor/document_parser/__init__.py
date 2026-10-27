"""Document parsing public API."""

from .exceptions import (
    DocumentAccessError,
    DocumentNotFound,
    DocumentTooLarge,
    InvalidDocument,
    TextLayerRequired,
    UnsupportedDocumentFormat,
)
from .models import DocumentMetadata, ParsedDocument, ParsedParagraph
from .service import DocumentParserService, parse_document

__all__ = [
    "DocumentAccessError",
    "DocumentNotFound",
    "DocumentParserService",
    "DocumentMetadata",
    "DocumentTooLarge",
    "InvalidDocument",
    "ParsedDocument",
    "ParsedParagraph",
    "TextLayerRequired",
    "UnsupportedDocumentFormat",
    "parse_document",
]

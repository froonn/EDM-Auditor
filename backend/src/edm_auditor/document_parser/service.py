"""Format selection and common document input handling."""

from os import PathLike
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from .docx_parser import DOCX_MEDIA_TYPE, DocxParser
from .exceptions import (
    DocumentAccessError,
    DocumentNotFound,
    DocumentTooLarge,
    UnsupportedDocumentFormat,
)
from .models import ParsedDocument
from .pdf_parser import PDF_MEDIA_TYPE, PdfParser

SUPPORTED_FORMATS = {
    ".docx": (DocxParser, DOCX_MEDIA_TYPE),
    ".pdf": (PdfParser, PDF_MEDIA_TYPE),
}


class DocumentParserService:
    def __init__(self, *, max_size_bytes: int | None = None) -> None:
        self.max_size_bytes = max_size_bytes

    def parse(
        self,
        source: str | PathLike[str] | BinaryIO,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> ParsedDocument:
        source_path, resolved_filename, size_bytes, temporary = self._prepare_source(
            source, filename=filename
        )
        try:
            suffix = Path(resolved_filename).suffix.lower()
            parser_info = SUPPORTED_FORMATS.get(suffix)
            if parser_info is None:
                raise UnsupportedDocumentFormat(
                    f"Unsupported document format: {suffix or '<none>'}"
                )
            parser_class, default_media_type = parser_info
            parser = parser_class()
            return parser.parse(
                source_path,
                filename=resolved_filename,
                media_type=media_type or default_media_type,
                size_bytes=size_bytes,
            )
        finally:
            if temporary:
                source_path.unlink(missing_ok=True)

    def _prepare_source(
        self,
        source: str | PathLike[str] | BinaryIO,
        *,
        filename: str | None,
    ) -> tuple[Path, str, int, bool]:
        if isinstance(source, (str, PathLike)):
            path = Path(source)
            if not path.exists():
                raise DocumentNotFound(f"Document does not exist: {path.name}")
            if not path.is_file():
                raise DocumentAccessError(f"Document is not a file: {path.name}")
            try:
                size = path.stat().st_size
            except OSError as exc:
                raise DocumentAccessError("Unable to access document") from exc
            self._check_size(size)
            return path, filename or path.name, size, False

        resolved_filename = filename or getattr(source, "name", None)
        if not resolved_filename:
            raise UnsupportedDocumentFormat(
                "A filename with a supported extension is required"
            )
        try:
            with NamedTemporaryFile(suffix=Path(resolved_filename).suffix) as temp:
                total = 0
                while chunk := source.read(1024 * 1024):
                    total += len(chunk)
                    self._check_size(total)
                    temp.write(chunk)
                temp.flush()
                temp_path = Path(temp.name)
                # The named file must remain available after this context exits.
                with NamedTemporaryFile(
                    suffix=Path(resolved_filename).suffix, delete=False
                ) as persistent:
                    temp.seek(0)
                    persistent.write(temp.read())
                    persistent.flush()
                    return Path(persistent.name), resolved_filename, total, True
        except DocumentTooLarge:
            raise
        except (OSError, AttributeError) as exc:
            raise DocumentAccessError("Unable to read document") from exc

    def _check_size(self, size: int) -> None:
        if self.max_size_bytes is not None and size > self.max_size_bytes:
            raise DocumentTooLarge("Document exceeds the configured size limit")


def parse_document(
    source: str | PathLike[str] | BinaryIO,
    *,
    filename: str | None = None,
    media_type: str | None = None,
    max_size_bytes: int | None = None,
) -> ParsedDocument:
    return DocumentParserService(max_size_bytes=max_size_bytes).parse(
        source, filename=filename, media_type=media_type
    )

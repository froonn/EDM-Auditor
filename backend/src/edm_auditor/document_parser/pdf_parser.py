"""PDF text extraction."""

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ._common import build_document
from .exceptions import InvalidDocument, TextLayerRequired
from .models import ParsedDocument

PDF_MEDIA_TYPE = "application/pdf"


class PdfParser:
    def parse(
        self,
        source: Path,
        *,
        filename: str,
        media_type: str,
        size_bytes: int,
    ) -> ParsedDocument:
        try:
            reader = PdfReader(source)
            blocks: list[tuple[str, int | None]] = []
            extracted_text = False
            for page_number, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted_text = True
                    blocks.extend(
                        (paragraph, page_number)
                        for paragraph in page_text.splitlines()
                    )
        except (PdfReadError, ValueError, OSError) as exc:
            raise InvalidDocument(f"Invalid PDF document: {filename}") from exc

        if not extracted_text:
            raise TextLayerRequired(
                f"PDF document has no extractable text layer: {filename}"
            )

        return build_document(
            filename=filename,
            media_type=media_type or PDF_MEDIA_TYPE,
            format="pdf",
            size_bytes=size_bytes,
            blocks=blocks,
        )

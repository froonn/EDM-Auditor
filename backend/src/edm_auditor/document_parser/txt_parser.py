"""UTF-8 plain-text extraction."""

from pathlib import Path

from ._common import build_document
from .exceptions import InvalidDocument
from .models import ParsedDocument

TXT_MEDIA_TYPE = "text/plain"


class TxtParser:
    """Parse UTF-8 text files into indexed paragraphs."""

    def parse(
        self,
        source: Path,
        *,
        filename: str,
        media_type: str,
        size_bytes: int,
    ) -> ParsedDocument:
        try:
            text = source.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            raise InvalidDocument(f"Invalid UTF-8 text document: {filename}") from exc

        return build_document(
            filename=filename,
            media_type=media_type or TXT_MEDIA_TYPE,
            format="txt",
            size_bytes=size_bytes,
            blocks=[(line, None) for line in text.splitlines()],
        )

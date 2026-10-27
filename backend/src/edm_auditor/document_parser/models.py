"""Data models returned by document parsers."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    filename: str
    media_type: str
    size_bytes: int
    format: str
    processed_at: datetime


@dataclass(frozen=True, slots=True)
class ParsedParagraph:
    index: int
    text: str
    start_char: int
    end_char: int
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source: DocumentMetadata
    text: str
    paragraphs: tuple[ParsedParagraph, ...]

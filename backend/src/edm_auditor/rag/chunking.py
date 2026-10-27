"""Deterministic source-preserving text chunking."""

from collections.abc import Iterator
from dataclasses import dataclass
import re

from .exceptions import InvalidChunkingConfiguration
from .models import TextChunk

CHUNKING_VERSION = "paragraph-v1"
_NON_EMPTY_LINE = re.compile(r"[^\n]*\S[^\n]*")


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int


def _spans(text: str) -> list[_Span]:
    return [_Span(match.start(), match.end()) for match in _NON_EMPTY_LINE.finditer(text)]


def _split_long_span(text: str, span: _Span, max_chars: int) -> Iterator[_Span]:
    start = span.start
    while start < span.end:
        limit = min(start + max_chars, span.end)
        if limit < span.end:
            boundary = text.rfind(" ", start, limit + 1)
            if boundary > start:
                limit = boundary
        yield _Span(start, limit)
        start = limit
        while start < span.end and text[start].isspace():
            start += 1


def chunk_text(
    source_text: str,
    *,
    legal_act_id: int,
    rule_id: int | None = None,
    max_chars: int = 1200,
    overlap_chars: int = 120,
    chunking_version: str = CHUNKING_VERSION,
) -> list[TextChunk]:
    """Split text while retaining exact source ranges."""
    if max_chars <= 0 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise InvalidChunkingConfiguration(
            "max_chars must be positive and overlap_chars must be in [0, max_chars)"
        )
    if not source_text.strip():
        return []

    units: list[_Span] = []
    for span in _spans(source_text):
        units.extend(_split_long_span(source_text, span, max_chars))

    chunks: list[TextChunk] = []
    cursor = 0
    while cursor < len(units):
        start = units[cursor].start
        end = units[cursor].end
        last = cursor
        while last + 1 < len(units):
            candidate_end = units[last + 1].end
            if candidate_end - start > max_chars:
                break
            end = candidate_end
            last += 1

        chunks.append(
            TextChunk(
                chunk_id=f"legal-act-{legal_act_id}:{chunking_version}:{len(chunks)}",
                legal_act_id=legal_act_id,
                rule_id=rule_id,
                text=source_text[start:end],
                chunk_index=len(chunks),
                start_char=start,
                end_char=end,
                chunking_version=chunking_version,
            )
        )

        if last == len(units) - 1:
            break
        next_cursor = last + 1
        overlap_start = end - overlap_chars
        while next_cursor > cursor and units[next_cursor - 1].start >= overlap_start:
            next_cursor -= 1
        cursor = max(cursor + 1, next_cursor)

    return chunks

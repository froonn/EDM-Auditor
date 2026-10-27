"""Helpers shared by format-specific parsers."""

from datetime import datetime, timezone

from .models import DocumentMetadata, ParsedDocument, ParsedParagraph


def build_document(
    *,
    filename: str,
    media_type: str,
    format: str,
    size_bytes: int,
    blocks: list[tuple[str, int | None]],
) -> ParsedDocument:
    """Build normalized text and source-relative paragraph coordinates."""
    paragraphs: list[ParsedParagraph] = []
    text_parts: list[str] = []
    position = 0

    for block, page_number in blocks:
        normalized = " ".join(block.split())
        if not normalized:
            continue
        if text_parts:
            text_parts.append("\n\n")
            position += 2
        start = position
        text_parts.append(normalized)
        position += len(normalized)
        paragraphs.append(
            ParsedParagraph(
                index=len(paragraphs),
                text=normalized,
                start_char=start,
                end_char=position,
                page_number=page_number,
            )
        )

    return ParsedDocument(
        source=DocumentMetadata(
            filename=filename,
            media_type=media_type,
            size_bytes=size_bytes,
            format=format,
            processed_at=datetime.now(timezone.utc),
        ),
        text="".join(text_parts),
        paragraphs=tuple(paragraphs),
    )

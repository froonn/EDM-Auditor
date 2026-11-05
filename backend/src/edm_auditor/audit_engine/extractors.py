"""Deterministic entity extraction with source-preserving ranges."""

from collections.abc import Iterable
from dataclasses import replace
import re
import time

from edm_auditor.model_providers import EntityExtractionProvider
from edm_auditor.rag.chunking import chunk_text

from .models import ExtractedEntity
from .neural_errors import DocumentTooLargeForAudit

_PATTERNS = {
    "date": re.compile(r"\b(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+"
                       r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
                       r"сентября|октября|ноября|декабря)\s+\d{4})\b", re.IGNORECASE),
    "duration": re.compile(
        # "5 числа следующего месяца" is a day of the month, not a period of five months.
        r"\b\d+(?:[.,]\d+)?(?!\s+числ)(?:\s+\S+){0,3}\s+"
        r"(?:дн(?:я|ей)?|месяц(?:а|ев)?|лет?|год(?:а|ов)?)\b",
        re.IGNORECASE,
    ),
    "money": re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:руб(?:лей|ля)?|BYN|р\.)\b", re.IGNORECASE),
    "percent": re.compile(r"\b\d+(?:[.,]\d+)?\s*%", re.IGNORECASE),
    "number": re.compile(r"\b\d+(?:[.,]\d+)?\b"),
}


_DAY_OF_MONTH = re.compile(r"\d+\s+числ", re.IGNORECASE)


def extract_entities(text: str, kinds: Iterable[str] | None = None) -> tuple[ExtractedEntity, ...]:
    """Extract configured entity types while preserving offsets."""
    selected = tuple(kinds) if kinds is not None else tuple(_PATTERNS)
    entities: list[ExtractedEntity] = []
    for kind in selected:
        try:
            pattern = _PATTERNS[kind]
        except KeyError as exc:
            raise ValueError(f"unsupported entity kind: {kind}") from exc
        entities.extend(
            ExtractedEntity(kind, match.group(), match.start(), match.end())
            for match in pattern.finditer(text)
        )
    return tuple(sorted(entities, key=lambda entity: (entity.start_char, entity.kind)))


def entities_from_provider(
    text: str, extracted: Iterable[dict[str, str]]
) -> tuple[ExtractedEntity, ...]:
    """Convert provider values into source-preserving entities."""
    entities: list[ExtractedEntity] = []
    valid_kinds = set(_PATTERNS)
    for item in extracted:
        kind = item.get("kind")
        value = item.get("value")
        if kind not in valid_kinds or not value:
            continue
        if kind == "duration" and _DAY_OF_MONTH.match(value):
            continue
        start = text.find(value)
        if start < 0:
            continue
        end = start + len(value)
        entities.append(ExtractedEntity(kind, value, start, end))
    unique = {
        (entity.kind, entity.start_char, entity.end_char): entity for entity in entities
    }
    return tuple(
        sorted(unique.values(), key=lambda entity: (entity.start_char, entity.kind))
    )


class ChunkedEntityExtractor:
    """Send a long document to the model in parts and restore document offsets."""

    def __init__(
        self,
        provider: EntityExtractionProvider,
        *,
        max_chars: int = 4000,
        overlap_chars: int = 200,
        max_chunks: int = 100,
        delay_seconds: float = 0.0,
    ) -> None:
        self._provider = provider
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars
        self._max_chunks = max_chunks
        self._delay_seconds = delay_seconds

    def __call__(self, text: str) -> tuple[ExtractedEntity, ...]:
        chunks = chunk_text(
            text,
            legal_act_id=0,
            max_chars=self._max_chars,
            overlap_chars=self._overlap_chars,
        )
        if len(chunks) > self._max_chunks:
            raise DocumentTooLargeForAudit(
                f"Document needs {len(chunks)} entity extraction requests; "
                f"the limit is {self._max_chunks}"
            )
        unique: dict[tuple[str, int, int], ExtractedEntity] = {}
        for index, chunk in enumerate(chunks):
            if index and self._delay_seconds:
                time.sleep(self._delay_seconds)
            for entity in entities_from_provider(
                chunk.text, self._provider.extract(chunk.text)
            ):
                located = replace(
                    entity,
                    start_char=entity.start_char + chunk.start_char,
                    end_char=entity.end_char + chunk.start_char,
                )
                unique[(located.kind, located.start_char, located.end_char)] = located
        return tuple(
            sorted(unique.values(), key=lambda entity: (entity.start_char, entity.kind))
        )

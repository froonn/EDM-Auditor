"""Deterministic entity extraction with source-preserving ranges."""

from collections.abc import Iterable
import re

from .models import ExtractedEntity

_PATTERNS = {
    "date": re.compile(r"\b(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+"
                       r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
                       r"сентября|октября|ноября|декабря)\s+\d{4})\b", re.IGNORECASE),
    "duration": re.compile(
        r"\b\d+(?:[.,]\d+)?\s*(?:дн(?:я|ей)?|месяц(?:а|ев)?|лет?|год(?:а|ов)?)\b",
        re.IGNORECASE,
    ),
    "money": re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:руб(?:лей|ля)?|BYN|р\.)\b", re.IGNORECASE),
    "percent": re.compile(r"\b\d+(?:[.,]\d+)?\s*%", re.IGNORECASE),
    "number": re.compile(r"\b\d+(?:[.,]\d+)?\b"),
}


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

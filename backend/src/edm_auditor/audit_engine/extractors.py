"""Deterministic entity and document statement extraction with source-preserving ranges."""

from collections.abc import Iterable, Sequence
from dataclasses import replace
import re
import time
from typing import Any

from edm_auditor.model_config import detect_source_language
from edm_auditor.model_providers import EntityExtractionProvider, StatementExtractionProvider
from edm_auditor.rag.chunking import chunk_text
from edm_auditor.rule_validation import (
    RuleValidationError,
    parse_constraint_from_text,
    validate_generated_statement,
)

from .models import ExtractedEntity, StatementSpec
from .neural_errors import DocumentTooLargeForAudit

_PATTERNS = {
    "date": re.compile(r"\b(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+"
                       r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
                       r"сентября|октября|ноября|декабря)\s+\d{4})\b", re.IGNORECASE),
    "duration": re.compile(
        # "5 числа следующего месяца" is a day of the month, not a period of five months.
        r"\b\d+(?:[.,]\d+)?(?!\s+числ)(?:\s+\S+){0,3}\s+"
        r"(?:дн(?:я|ей)?|день|месяц(?:а|ев)?|лет?|год(?:а|ов)?|days?)\b",
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


def statements_from_provider(
    text: str,
    extracted: Iterable[dict[str, Any]],
    *,
    source_language: str = "auto",
    prompt_version: str = "1",
) -> tuple[StatementSpec, ...]:
    """Validate provider-extracted statements against the chunk text and resolve offsets."""
    if source_language == "auto":
        source_language = detect_source_language(text)
    statements: list[StatementSpec] = []
    for index, item in enumerate(extracted, start=1):
        try:
            validated = validate_generated_statement(
                item,
                source_text=text,
                source_language=source_language,
                index=index,
            )
        except (RuleValidationError, ValueError, TypeError):
            continue
        statements.append(
            StatementSpec(
                subject=str(validated["subject"]),
                statement_text=str(validated["statement_text"]),
                source_quote=str(validated["source_quote"]),
                start_char=int(validated["start_char"]),
                end_char=int(validated["end_char"]),
                constraint_json=validated["constraint_json"],
                prompt_version=prompt_version,
            )
        )
    unique = {
        (item.subject.casefold(), item.start_char, item.end_char): item
        for item in statements
    }
    return tuple(
        sorted(unique.values(), key=lambda item: (item.start_char, item.end_char, item.subject))
    )


class ChunkedStatementExtractor:
    """Extract document statements chunk by chunk (one request per chunk) and restore offsets."""

    def __init__(
        self,
        provider: StatementExtractionProvider | Any,
        *,
        max_chars: int = 4000,
        overlap_chars: int = 200,
        max_chunks: int = 100,
        delay_seconds: float = 0.0,
        source_language: str = "auto",
        prompt_version: str = "1",
    ) -> None:
        self._provider = provider
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars
        self._max_chunks = max_chunks
        self._delay_seconds = delay_seconds
        self._source_language = source_language
        self._prompt_version = prompt_version

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    def __call__(self, text: str) -> tuple[StatementSpec, ...]:
        chunks = chunk_text(
            text,
            legal_act_id=0,
            max_chars=self._max_chars,
            overlap_chars=self._overlap_chars,
        )
        if len(chunks) > self._max_chunks:
            raise DocumentTooLargeForAudit(
                f"Document needs {len(chunks)} statement extraction requests; "
                f"the limit is {self._max_chunks}"
            )
        lang = (
            detect_source_language(text)
            if self._source_language == "auto"
            else self._source_language
        )
        unique: dict[tuple[str, int, int], StatementSpec] = {}
        for index, chunk in enumerate(chunks):
            if index and self._delay_seconds:
                time.sleep(self._delay_seconds)
            if hasattr(self._provider, "extract_statements"):
                raw_items = self._provider.extract_statements(
                    chunk.text, source_language=lang
                )
                chunk_statements = statements_from_provider(
                    chunk.text,
                    raw_items,
                    source_language=lang,
                    prompt_version=self._prompt_version,
                )
            else:
                raw_entities = self._provider.extract(chunk.text)
                chunk_statements = _statements_from_legacy_entities(
                    chunk.text, raw_entities, prompt_version=self._prompt_version
                )
            for statement in chunk_statements:
                located = replace(
                    statement,
                    start_char=statement.start_char + chunk.start_char,
                    end_char=statement.end_char + chunk.start_char,
                )
                unique[(located.subject.casefold(), located.start_char, located.end_char)] = located
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (item.start_char, item.end_char, item.subject),
            )
        )


def _statements_from_legacy_entities(
    text: str,
    extracted: Sequence[dict[str, str]],
    *,
    prompt_version: str = "1",
) -> tuple[StatementSpec, ...]:
    """Convert legacy entity extraction output into document statements when using a legacy fake."""
    statements: list[StatementSpec] = []
    for entity in entities_from_provider(text, extracted):
        constraint = parse_constraint_from_text(entity.value)
        statements.append(
            StatementSpec(
                subject=entity.kind,
                statement_text=entity.value,
                source_quote=entity.value,
                start_char=entity.start_char,
                end_char=entity.end_char,
                constraint_json=constraint,
                prompt_version=prompt_version,
            )
        )
    return tuple(statements)

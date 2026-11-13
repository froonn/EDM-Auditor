"""Labelled corpus of legal acts and documents for measuring extraction and audit quality."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

NORM_KINDS = frozenset({"value", "frequency", "day_of_month", "text"})


class CorpusError(ValueError):
    """The labels do not match the corpus files."""


@dataclass(frozen=True, slots=True)
class Norm:
    id: str
    quote: str
    kind: str
    checkable: bool = True


@dataclass(frozen=True, slots=True)
class ActCase:
    id: str
    path: Path
    code: str
    title: str
    norms: tuple[Norm, ...]

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class Violation:
    norm: str
    quote: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentCase:
    id: str
    path: Path
    acts: tuple[str, ...]
    document_types: tuple[str, ...]
    violations: tuple[Violation, ...]
    note: str = ""

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class Corpus:
    root: Path
    acts: tuple[ActCase, ...]
    documents: tuple[DocumentCase, ...]

    def act(self, act_id: str) -> ActCase:
        for act in self.acts:
            if act.id == act_id:
                return act
        raise KeyError(act_id)

    def norm(self, norm_id: str) -> Norm:
        for act in self.acts:
            for norm in act.norms:
                if norm.id == norm_id:
                    return norm
        raise KeyError(norm_id)


def find_quote(text: str, quote: str) -> list[tuple[int, int]]:
    """Find a labelled quote; any whitespace run in it matches any whitespace run in the text."""
    parts = [re.escape(part) for part in quote.split()]
    if not parts:
        return []
    pattern = re.compile(r"\s+".join(parts), re.IGNORECASE)
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def locate_quote(text: str, quote: str, *, where: str) -> tuple[int, int]:
    """Return the only position of a quote or explain why the label is wrong."""
    matches = find_quote(text, quote)
    if len(matches) != 1:
        found = "not found" if not matches else f"found {len(matches)} times"
        raise CorpusError(f"{where}: quote {quote!r} is {found}")
    return matches[0]


def load_corpus(root: Path) -> Corpus:
    """Load labels.toml and check that every label points at real text."""
    labels_path = root / "labels.toml"
    with labels_path.open("rb") as file:
        data = tomllib.load(file)

    acts: list[ActCase] = []
    norm_ids: dict[str, str] = {}
    for raw in data.get("acts", []):
        norms = tuple(
            Norm(
                id=item["id"],
                quote=item["quote"],
                kind=item["kind"],
                checkable=item.get("checkable", True),
            )
            for item in raw["norms"]
        )
        act = ActCase(
            id=raw["id"],
            path=root / raw["file"],
            code=raw["code"],
            title=raw["title"],
            norms=norms,
        )
        text = act.text()
        for norm in norms:
            if norm.kind not in NORM_KINDS:
                raise CorpusError(f"norm {norm.id}: unknown kind {norm.kind!r}")
            if norm.id in norm_ids:
                raise CorpusError(f"norm {norm.id} is defined twice")
            norm_ids[norm.id] = act.id
            locate_quote(text, norm.quote, where=f"norm {norm.id}")
        acts.append(act)
    act_ids = {act.id for act in acts}

    documents: list[DocumentCase] = []
    for raw in data.get("documents", []):
        document = DocumentCase(
            id=raw["id"],
            path=root / raw["file"],
            acts=tuple(raw["acts"]),
            document_types=tuple(raw.get("document_types", ())),
            violations=tuple(
                Violation(norm=item["norm"], quote=item.get("quote"))
                for item in raw.get("violations", [])
            ),
            note=raw.get("note", ""),
        )
        if unknown := set(document.acts) - act_ids:
            raise CorpusError(f"document {document.id}: unknown acts {sorted(unknown)}")
        text = document.text()
        for violation in document.violations:
            if norm_ids.get(violation.norm) not in document.acts:
                raise CorpusError(
                    f"document {document.id}: norm {violation.norm} is not in its acts"
                )
            if violation.quote is not None:
                locate_quote(text, violation.quote, where=f"document {document.id}")
        documents.append(document)

    ids = [act.id for act in acts] + [document.id for document in documents]
    if len(ids) != len(set(ids)):
        raise CorpusError("act and document ids must be unique")
    return Corpus(root=root, acts=tuple(acts), documents=tuple(documents))

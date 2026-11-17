"""Structure of a legal act: blocks, headings, numbered units and model chunks.

A legal act is split into blocks: a block is a paragraph whose hard-wrapped lines are joined, a
heading, or a numbered unit. Blocks form a tree of chapters, articles, points and subpoints. Chunks for
the model are packed from whole units, so a boundary never falls inside a sentence, and every chunk
carries the headings and list lead-ins it needs as separate context.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
import sys

from edm_auditor.document_parser.exceptions import DocumentParserError

STRUCTURE_VERSION = "structure-v1"

# Lower rank is higher in the tree.
_RANKS = {"section": 0, "chapter": 1, "article": 2, "point": 3, "subpoint": 5, "paragraph": 6}
_SECTION = re.compile(r"^\s*раздел\s+([IVXLC\d]+)\.?(?:\s+|$)", re.IGNORECASE)
_CHAPTER = re.compile(r"^\s*глава\s+(\d+|[IVXLC]+)\.?(?:\s+|$)", re.IGNORECASE)
_ARTICLE = re.compile(r"^\s*(?:статья|ст\.)\s+(\d+(?:\.\d+)*)\.?(?:\s+|$)", re.IGNORECASE)
_POINT = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){0,2})\.(?:\s+|$)|"
    r"^\s*(\d{1,3}\.\d{1,3}(?:\.\d{1,3})*)\s+"
)
_SUBPOINT = re.compile(r"^\s*(\d+|[а-яё])\)\s+", re.IGNORECASE)
_LINE_END = re.compile(r"[.;:!?]\s*$")
_SENTENCE_END = re.compile(r"(?<=[.;!?])\s+")
_PDF_HEADER = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{4},\s+\d{1,2}:\d{2}")
_PDF_URL = re.compile(r"^\s*https?://", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Block:
    """A paragraph, heading or numbered unit with its exact source range."""

    start: int
    end: int
    kind: str
    label: str | None
    rank: int
    path: tuple[str, ...]
    parent: int | None
    heading: bool = False
    category: str = "normative"


@dataclass(frozen=True, slots=True)
class LegalActStructure:
    text: str
    blocks: tuple[Block, ...]
    normative_start: int = 0

    def location(self, start: int, end: int) -> str:
        """The deepest common unit of a range, such as «гл. 2, п. 6, подп. 2)»."""
        first = self._block_at(start)
        last = self._block_at(max(start, end - 1))
        if first is None:
            return "текст акта"
        path = first.path
        if last is not None and last is not first:
            common = []
            for own, other in zip(first.path, last.path):
                if own != other:
                    break
                common.append(own)
            path = tuple(common) or first.path
        return ", ".join(path) if path else "текст акта"

    def context(self, index: int) -> tuple[str, ...]:
        """Headings and list lead-ins of a block's ancestors, outermost first."""
        lines = []
        parent = self.blocks[index].parent
        while parent is not None:
            block = self.blocks[parent]
            lines.append(_one_line(self.text[block.start:block.end]))
            parent = block.parent
        return tuple(reversed(lines))

    def _block_at(self, offset: int) -> Block | None:
        for block in self.blocks:
            if block.start <= offset < block.end:
                return block
        following = [block for block in self.blocks if block.start >= offset]
        return following[0] if following else (self.blocks[-1] if self.blocks else None)


@dataclass(frozen=True, slots=True)
class LegalActChunk:
    """A contiguous part of the act for one model request, with context it cannot quote."""

    chunk_id: str
    chunk_index: int
    start_char: int
    end_char: int
    text: str
    context: tuple[str, ...] = field(default_factory=tuple)

    @property
    def context_text(self) -> str:
        return "\n".join(self.context)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _marker(line: str, after_break: bool) -> tuple[str, str] | None:
    """The kind and label of a unit that starts on this line."""
    if match := _SECTION.match(line):
        return "section", f"разд. {match.group(1)}"
    if match := _CHAPTER.match(line):
        return "chapter", f"гл. {match.group(1)}"
    if match := _ARTICLE.match(line):
        return "article", f"ст. {match.group(1)}"
    if not after_break:
        # A wrapped line may start with a number that is not a point: «15 календарных дней».
        return None
    if match := _POINT.match(line):
        return "point", f"п. {match.group(1) or match.group(2)}"
    if match := _SUBPOINT.match(line):
        return "subpoint", f"подп. {match.group(1)})"
    return None


def _raw_blocks(text: str) -> list[tuple[int, int, str | None, str | None]]:
    """Join wrapped lines into blocks and note the unit each block starts."""
    blocks: list[list] = []
    previous_ended = True
    offset = 0
    for line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        content = line.rstrip("\r\n")
        if not content.strip():
            previous_ended = True
            if blocks:
                blocks[-1][4] = True
            continue
        start = line_start + len(content) - len(content.lstrip())
        end = line_start + len(content.rstrip())
        marker = _marker(content, previous_ended)
        current = blocks[-1] if blocks else None
        continues = (
            current is not None
            and not current[4]
            and marker is None
            and not previous_ended
        )
        if continues:
            current[1] = end
        else:
            kind, label = marker if marker else (None, None)
            blocks.append([start, end, kind, label, False])
        previous_ended = bool(_LINE_END.search(content))
    return [(start, end, kind, label) for start, end, kind, label, _ in blocks]


def parse_legal_act(text: str) -> LegalActStructure:
    """Build the block tree of a legal act; offsets refer to the given text."""
    raw = _raw_blocks(text)
    blocks: list[Block] = []
    stack: list[int] = []
    paragraph_number = 0
    for position, (start, end, kind, label) in enumerate(raw):
        body = text[start:end]
        next_start = raw[position + 1][0] if position + 1 < len(raw) else len(text)
        blank_after = "\n\n" in text[end:next_start] or position + 1 == len(raw)
        heading = kind in {"section", "chapter", "article"} or (
            kind is None and not _LINE_END.search(body) and blank_after
        )
        if kind is None:
            kind = "heading" if heading else "paragraph"
        rank = _rank(kind, label)
        if kind == "heading":
            # A wrapped heading can be part of the current chapter or article.
            if _one_line(body).upper() == "ИНСТРУКЦИЯ":
                stack.clear()
            parent = stack[-1] if stack else None
            path = blocks[parent].path if parent is not None else ()
            blocks.append(
                Block(start, end, kind, None, rank, path, parent, heading=True)
            )
            continue
        while stack and blocks[stack[-1]].rank >= rank and not _contains_paragraph(
            blocks[stack[-1]], kind
        ):
            stack.pop()
        parent = stack[-1] if stack else None
        if kind == "paragraph":
            # Plain text belongs to the enclosing unit; numbered acts give it no label.
            if parent is not None and blocks[parent].kind == "subpoint":
                parent = blocks[parent].parent
            path = blocks[parent].path if parent is not None else ()
            if not path:
                paragraph_number += 1
                path = (f"абз. {paragraph_number}",)
            lead_in = parent
            while lead_in is not None and not _is_context(text, blocks[lead_in]):
                lead_in = blocks[lead_in].parent
            blocks.append(Block(start, end, kind, None, rank, path, lead_in))
            if body.rstrip().endswith(":"):
                stack.append(len(blocks) - 1)
            continue
        own_parent = parent
        while own_parent is not None and not _is_context(text, blocks[own_parent]):
            own_parent = blocks[own_parent].parent
        path = (blocks[parent].path if parent is not None else ()) + (label,)
        blocks.append(
            Block(start, end, kind, label, rank, path, own_parent, heading=heading)
        )
        stack.append(len(blocks) - 1)
    normative_start = _find_normative_start(text, blocks)
    categorized = tuple(
        replace(
            block,
            category=(
                "normative"
                if block.start >= normative_start
                and not _is_transport_metadata(text, block)
                else "metadata"
            ),
        )
        for block in blocks
    )
    return LegalActStructure(
        text=text,
        blocks=categorized,
        normative_start=normative_start,
    )


def _find_normative_start(text: str, blocks: list[Block]) -> int:
    """Find the first actual provision after publication metadata and contents."""
    article_indexes = [index for index, block in enumerate(blocks) if block.kind == "article"]
    for position, index in enumerate(article_indexes):
        next_article = (
            article_indexes[position + 1] if position + 1 < len(article_indexes) else len(blocks)
        )
        body_blocks = blocks[index + 1:next_article]
        if any(block.kind in {"paragraph", "point", "subpoint"} for block in body_blocks):
            return blocks[index].start

    instruction = re.search(r"(?im)^[ \t]*ИНСТРУКЦИЯ[ \t]*$", text)
    if instruction:
        return instruction.start()
    return 0


def _is_transport_metadata(text: str, block: Block) -> bool:
    """Recognize repeated PDF headers and page markers inside the source text."""
    value = _one_line(text[block.start:block.end])
    return bool(_PDF_HEADER.match(value) or _PDF_URL.match(value) or value.isdigit())


def _rank(kind: str, label: str | None) -> int:
    if kind == "point" and label:
        # «п. 1.1» is inside «п. 1».
        return _RANKS["point"] + label.count(".") - 1
    return _RANKS.get(kind, _RANKS["paragraph"])


def _contains_paragraph(block: Block, kind: str) -> bool:
    """A paragraph that ends with a colon opens a list of subpoints."""
    return block.kind == "paragraph" and kind == "subpoint"


def _is_context(text: str, block: Block) -> bool:
    """Headings and list lead-ins explain the units below them."""
    body = text[block.start:block.end].rstrip()
    return block.heading or block.kind in {"section", "chapter", "article"} or body.endswith(":")


def chunk_legal_act(
    structure: LegalActStructure,
    *,
    legal_act_id: int,
    max_chars: int,
) -> list[LegalActChunk]:
    """Pack whole blocks into chunks; split a block only between sentences."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    text = structure.text
    pieces: list[tuple[int, int, int]] = []
    for index, block in enumerate(structure.blocks):
        if block.category != "normative":
            continue
        for start, end in _split_block(text, block.start, block.end, max_chars):
            pieces.append((start, end, index))
    source_hash = sha256(text.encode("utf-8")).hexdigest()

    groups: list[list[tuple[int, int, int]]] = []
    for piece in pieces:
        previous_piece = groups[-1][-1] if groups else None
        consecutive = previous_piece is not None and (
            piece[2] == previous_piece[2]
            or piece[2] == previous_piece[2] + 1
        )
        if (
            groups
            and consecutive
            and piece[1] - groups[-1][0][0] <= max_chars
            and not _starts_top_unit(structure, piece, groups[-1], max_chars)
        ):
            groups[-1].append(piece)
        else:
            # A heading or a lead-in at the end of a chunk belongs with the text below it.
            moved: list[tuple[int, int, int]] = []
            while (
                groups
                and len(groups[-1]) > 1
                and groups[-1][-1][2] + 1 == piece[2]
                and _explains_next(structure, groups[-1][-1])
            ):
                moved.insert(0, groups[-1].pop())
            if moved and piece[1] - moved[0][0] > max_chars:
                groups[-1].extend(moved)
                moved = []
            groups.append([*moved, piece])

    chunks = []
    for chunk_index, group in enumerate(groups):
        start, end = group[0][0], group[-1][1]
        first_block = group[0][2]
        inside = {index for _, _, index in group}
        context = tuple(
            line for line, ancestor in zip(
                structure.context(first_block), _ancestors(structure, first_block)
            )
            if ancestor not in inside
        )
        if group[0][0] != structure.blocks[first_block].start:
            # The chunk starts in the middle of a long block.
            context += (_one_line(text[structure.blocks[first_block].start:group[0][0]]),)
        chunks.append(
            LegalActChunk(
                chunk_id=(
                    f"legal-act-{legal_act_id}:base:{source_hash[:16]}:"
                    f"{STRUCTURE_VERSION}:{chunk_index}"
                ),
                chunk_index=chunk_index,
                start_char=start,
                end_char=end,
                text=text[start:end],
                context=context,
            )
        )
    return chunks


def _explains_next(structure: LegalActStructure, piece: tuple[int, int, int]) -> bool:
    block = structure.blocks[piece[2]]
    return piece[1] == block.end and _is_context(structure.text, block)


def _ancestors(structure: LegalActStructure, index: int) -> list[int]:
    result = []
    parent = structure.blocks[index].parent
    while parent is not None:
        result.append(parent)
        parent = structure.blocks[parent].parent
    return list(reversed(result))


def _starts_top_unit(
    structure: LegalActStructure,
    piece: tuple[int, int, int],
    group: list[tuple[int, int, int]],
    max_chars: int,
) -> bool:
    """Start a new chunk at a unit that does not fit whole into the current one."""
    block = structure.blocks[piece[2]]
    if piece[0] != block.start or block.kind not in {"section", "chapter", "article", "point"}:
        return False
    unit_end = block.end
    for later in structure.blocks[piece[2] + 1:]:
        if later.kind in {"section", "chapter", "article", "point", "heading"} and later.rank <= block.rank:
            break
        unit_end = later.end
    return unit_end - group[0][0] > max_chars and unit_end - block.start <= max_chars


def _split_block(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split a block longer than the limit between sentences, words as the last resort."""
    if end - start <= max_chars:
        return [(start, end)]
    parts: list[tuple[int, int]] = []
    # The number of a point, «1.», is not the end of a sentence.
    marker = _POINT.match(text[start:end]) or _SUBPOINT.match(text[start:end])
    search_from = start + marker.end() if marker else start
    sentences = [start] + [
        search_from + match.end()
        for match in _SENTENCE_END.finditer(text[search_from:end])
    ]
    sentence_ends = sentences[1:] + [end]
    current_start = start
    current_end = start
    for sentence_start, sentence_end in zip(sentences, sentence_ends):
        sentence_text_end = sentence_end
        if sentence_text_end - current_start <= max_chars:
            current_end = sentence_text_end
            continue
        if current_end > current_start:
            parts.append((current_start, _trim_end(text, current_start, current_end)))
        current_start = sentence_start
        current_end = sentence_text_end
        while current_end - current_start > max_chars:
            boundary = text.rfind(" ", current_start, current_start + max_chars)
            boundary = boundary if boundary > current_start else current_start + max_chars
            parts.append((current_start, boundary))
            current_start = boundary + 1
    if current_end > current_start:
        parts.append((current_start, _trim_end(text, current_start, current_end)))
    return parts


def _trim_end(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def _block_to_json(structure: LegalActStructure, block: Block) -> dict[str, object]:
    return {
        "start_char": block.start,
        "end_char": block.end,
        "kind": block.kind,
        "label": block.label,
        "path": list(block.path),
        "parent": block.parent,
        "heading": block.heading,
        "category": block.category,
        "text": structure.text[block.start:block.end],
    }


def _chunk_to_json(chunk: LegalActChunk) -> dict[str, object]:
    return {
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "start_char": chunk.start_char,
        "end_char": chunk.end_char,
        "text": chunk.text,
        "context": list(chunk.context),
    }


def build_fragments_json(
    input_dir: Path,
    *,
    max_chars: int = 4000,
) -> dict[str, object]:
    """Build a reviewable JSON representation of legal-act structures and chunks."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if not input_dir.is_dir():
        raise ValueError(f"input directory does not exist: {input_dir}")

    documents: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for legal_act_id, path in enumerate(
        sorted(
            item
            for item in input_dir.iterdir()
            if item.is_file() and item.suffix.lower() in {".pdf", ".txt"}
        ),
        start=1,
    ):
        try:
            if path.suffix.lower() == ".txt":
                text = path.read_text(encoding="utf-8")
                file_format = "txt"
                size_bytes = path.stat().st_size
            else:
                from edm_auditor.document_parser import parse_document

                parsed = parse_document(path)
                text = parsed.text
                file_format = parsed.source.format
                size_bytes = parsed.source.size_bytes
            structure = parse_legal_act(text)
            chunks = chunk_legal_act(
                structure,
                legal_act_id=legal_act_id,
                max_chars=max_chars,
            )
            documents.append(
                {
                    "legal_act_id": legal_act_id,
                    "filename": path.name,
                    "format": file_format,
                    "size_bytes": size_bytes,
                    "text_length": len(text),
                    "structure_version": STRUCTURE_VERSION,
                    "normative_start": structure.normative_start,
                    "text": text,
                    "blocks": [
                        _block_to_json(structure, block) for block in structure.blocks
                    ],
                    "chunks": [
                        _chunk_to_json(chunk)
                        | {
                            "location": structure.location(
                                chunk.start_char, chunk.end_char
                            )
                        }
                        for chunk in chunks
                    ],
                }
            )
        except (DocumentParserError, OSError, UnicodeError, ValueError) as exc:
            errors.append({"filename": path.name, "error": str(exc)})

    return {
        "structure_version": STRUCTURE_VERSION,
        "max_chars": max_chars,
        "documents": documents,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    """Write structural fragments for local manual inspection."""
    backend_dir = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        prog="python -m edm_auditor.legal_structure",
        description="Split legal-act files into structure-aware JSON fragments",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=backend_dir / "data" / "legal-acts",
        help="directory containing TXT and PDF legal acts",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=backend_dir / "data" / "legal-act-fragments.json",
        help="JSON file to write",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=4000,
        help="maximum number of source characters in a chunk",
    )
    args = parser.parse_args(argv)
    try:
        result = build_fragments_json(args.input_dir, max_chars=args.max_chars)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"saved {len(result['documents'])} documents and "
        f"{sum(len(document['chunks']) for document in result['documents'])} chunks "
        f"to {args.output}"
    )
    if result["errors"]:
        print(f"skipped {len(result['errors'])} files with errors", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from pathlib import Path

import pytest

from edm_auditor.document_parser import DocumentParserService, InvalidDocument


def test_txt_parser_returns_indexed_paragraphs(tmp_path: Path) -> None:
    path = tmp_path / "labour-code.txt"
    path.write_text("Статья 1. Термины\n\nТекст статьи.", encoding="utf-8")

    result = DocumentParserService().parse(path)

    assert result.source.format == "txt"
    assert result.source.media_type == "text/plain"
    assert [paragraph.text for paragraph in result.paragraphs] == [
        "Статья 1. Термины",
        "Текст статьи.",
    ]
    assert all(result.text[item.start_char : item.end_char] == item.text for item in result.paragraphs)


def test_txt_parser_rejects_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(InvalidDocument):
        DocumentParserService().parse(path)

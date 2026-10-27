from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from edm_auditor.document_parser import (
    DocumentNotFound,
    DocumentParserService,
    DocumentTooLarge,
    InvalidDocument,
    ParsedDocument,
    TextLayerRequired,
    UnsupportedDocumentFormat,
)


def create_docx(path: Path) -> None:
    document = Document()
    document.add_paragraph("Первый абзац.")
    document.add_paragraph("Сумма: 1 250 BYN.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Сторона"
    table.rows[0].cells[1].text = "Заказчик"
    document.save(path)


def create_text_pdf(path: Path) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length 44 >>\nstream\nBT /F1 12 Tf 20 150 Td "
        b"(First paragraph.) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode())
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        body.extend(f"{offset:010} 00000 n \n".encode())
    body.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.write_bytes(body)


def test_docx_parser_returns_indexed_paragraphs(tmp_path: Path) -> None:
    path = tmp_path / "contract.docx"
    create_docx(path)

    result = DocumentParserService().parse(path)

    assert isinstance(result, ParsedDocument)
    assert result.source.format == "docx"
    assert [paragraph.text for paragraph in result.paragraphs] == [
        "Первый абзац.",
        "Сумма: 1 250 BYN.",
        "Сторона | Заказчик",
    ]
    assert all(
        result.text[item.start_char : item.end_char] == item.text
        for item in result.paragraphs
    )


def test_pdf_parser_preserves_page_number(tmp_path: Path) -> None:
    path = tmp_path / "contract.pdf"
    create_text_pdf(path)

    result = DocumentParserService().parse(path)

    assert result.source.format == "pdf"
    assert result.paragraphs[0].page_number == 1
    assert "First paragraph." in result.text


def test_file_like_input_requires_filename() -> None:
    with pytest.raises(UnsupportedDocumentFormat):
        DocumentParserService().parse(BytesIO(b"content"))


def test_missing_and_invalid_documents_raise_explicit_errors(tmp_path: Path) -> None:
    with pytest.raises(DocumentNotFound):
        DocumentParserService().parse(tmp_path / "missing.pdf")

    invalid = tmp_path / "broken.docx"
    invalid.write_bytes(b"not a docx")
    with pytest.raises(InvalidDocument):
        DocumentParserService().parse(invalid)


def test_pdf_without_text_layer_raises_explicit_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    with path.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(TextLayerRequired):
        DocumentParserService().parse(path)


def test_size_limit_applies_to_paths_and_file_like_inputs(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"12345")
    with pytest.raises(DocumentTooLarge):
        DocumentParserService(max_size_bytes=4).parse(path)

    with pytest.raises(DocumentTooLarge):
        DocumentParserService(max_size_bytes=4).parse(
            BytesIO(b"12345"), filename="large.pdf"
        )

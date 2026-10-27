# Backend

## Document parser

The parser supports `.docx` files and text-layer `.pdf` files. Scanned PDFs
without an extractable text layer require OCR, which is not implemented yet.

### 1. Install the backend dependencies

Run the commands from the `backend/` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
```

On Windows PowerShell, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Run the automated checks

The parser test suite creates synthetic DOCX and PDF documents, so no
additional documents are required:

```python
pytest tests/document_parser -q
```

All tests should pass:

```text
6 passed
```

The test suite checks DOCX paragraphs and tables, PDF page numbers, file-like
input, missing or damaged files, PDFs without a text layer, and the size limit.

### 3. Check a real document manually

Place a document in `backend/` or provide an absolute path, then run:

```bash
python - <<'PY'
from edm_auditor.document_parser import parse_document

document = parse_document("contract.pdf")  # or "contract.docx"

print(f"File: {document.source.filename}")
print(f"Format: {document.source.format}")
print(f"Size: {document.source.size_bytes} bytes")
print(f"Paragraphs: {len(document.paragraphs)}")
print("Text:")
print(document.text)

for paragraph in document.paragraphs:
    print(
        f"[{paragraph.index}] "
        f"chars {paragraph.start_char}:{paragraph.end_char} "
        f"page={paragraph.page_number}: {paragraph.text}"
    )
PY
```

For a successful parse, the command prints the document metadata and extracted
text. For PDF files, `page` starts at `1`; for DOCX files it is `None`.

The parser can also read a binary file-like object:

```bash
python - <<'PY'
from pathlib import Path

from edm_auditor.document_parser import parse_document

path = Path("contract.pdf")
with path.open("rb") as file:
    document = parse_document(file, filename=path.name)

print(document.text)
PY
```

### Expected errors

The following input conditions are reported as explicit parser exceptions:

- unsupported extension: `UnsupportedDocumentFormat`;
- missing path: `DocumentNotFound`;
- damaged DOCX/PDF: `InvalidDocument`;
- scanned PDF without text: `TextLayerRequired`;
- configured size limit exceeded: `DocumentTooLarge`.

These errors are expected behavior and should be handled by the API layer when
the parser is integrated into file uploads.

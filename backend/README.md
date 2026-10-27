# Backend

The document parser is available from `edm_auditor.document_parser`:

```python
from edm_auditor.document_parser import parse_document

document = parse_document("contract.docx")
print(document.text)
```

It supports DOCX and text-layer PDF files. Scanned PDFs require OCR and raise
`TextLayerRequired` until OCR support is added.

Run parser tests from this directory:

```bash
pytest tests/document_parser -q
```

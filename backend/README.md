# Backend

## Document parser

The parser supports `.docx`, UTF-8 `.txt`, and text-layer `.pdf` files. Scanned PDFs
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

```bash
pytest tests/document_parser -q
```

The test suite checks DOCX paragraphs and tables, PDF page numbers, file-like
input, missing or damaged files, PDFs without a text layer, and the size limit.
UTF-8 `.txt` files are also supported and are parsed into indexed paragraphs.

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

## Database

The database layer uses SQLAlchemy 2.x and Alembic with SQLite. The default
development database is `backend/data/edm_auditor.sqlite3`; its contents are
not committed to Git.

Apply the current schema from the `backend/` directory:

```bash
alembic upgrade head
```

Revert the schema to an empty database:

```bash
alembic downgrade base
```

Run all backend checks, including database integration tests:

```bash
pytest tests/database tests/document_parser -q
```

The database repository accepts a `ParsedDocument` returned by
`parse_document` and stores its normalized text and paragraphs in one
transaction:

```bash
python - <<'PY'
from edm_auditor.database import (
    DocumentRepository,
    create_engine_for,
    create_session_factory,
)
from edm_auditor.document_parser import parse_document

engine = create_engine_for("sqlite:///data/edm_auditor.sqlite3")
repository = DocumentRepository(create_session_factory(engine))
parsed = parse_document("contract.pdf")
document = repository.save_parsed_document(parsed)
PY
```

Foreign keys are enabled for every SQLite connection. Deleting a document
cascades to its paragraphs, audit reports, and findings. The repository does
not store binary document contents; `file_path` points to the external file
storage.

## RAG indexer

The RAG layer splits legal-act text into source-preserving chunks and stores
their deterministic embeddings in a local SQLite vector index. The default
provider is intentionally offline and is suitable for tests; a production
embedding provider can implement the same `EmbeddingProvider` protocol later.
The first version is intentionally limited to the offline deterministic
provider and a local SQLite index. A production embedding provider and a larger
legal-act corpus should be added separately; they must not become requirements
for the ordinary test suite. If the corpus grows beyond local SQLite usage, the
vector store can be replaced behind the existing RAG interfaces.

The production embedding provider and the starter legal-act dataset are not
implemented yet. Until those decisions are made, use
`DeterministicEmbeddingProvider` and local or synthetic test texts only.

The following example creates an index in a temporary directory and searches
it without network access or API keys:

```bash
python - <<'PY'
from pathlib import Path

from edm_auditor.rag import (
    DeterministicEmbeddingProvider,
    IndexSource,
    RAGIndexer,
    RAGSearch,
    SQLiteVectorStore,
)

provider = DeterministicEmbeddingProvider()
store = SQLiteVectorStore(
    Path("data/rag-index.sqlite3"),
    embedding_model=provider.model_name,
    dimension=provider.dimension,
    chunking_version="paragraph-v1",
)
RAGIndexer(store, provider).build(
    [IndexSource(legal_act_id=1, text="Annual leave is granted every year.")]
)

for result in RAGSearch(store, provider).search("annual leave", k=3):
    chunk = result.chunk
    print(
        result.score,
        chunk.legal_act_id,
        f"chars {chunk.start_char}:{chunk.end_char}",
        chunk.text,
    )
PY
```

Run the RAG tests with:

```bash
pytest tests/rag -q
```

The index stores source ranges and metadata, replaces stale entries on a full
rebuild, and rejects incompatible embedding models or vector dimensions.

To load a local UTF-8 legal-act text file into the database, use the separate
ingestion adapter after applying the database migration:

```bash
python - <<'PY'
from edm_auditor.database import create_engine_for, create_session_factory
from edm_auditor.rag import TextLegalActIngestor

engine = create_engine_for("sqlite:///data/edm_auditor.sqlite3")
ingestor = TextLegalActIngestor(create_session_factory(engine))
ingestor.ingest(
    "data/legal-acts/trudovoi-kodeks-rb.txt",
    code="TK-RB",
    title="Трудовой кодекс Республики Беларусь",
)
PY
```

The adapter accepts only `.txt` files, decodes them as UTF-8, preserves the
normalized text and paragraph boundaries, and stores the result in `legal_acts`.

Build and query the index from the database with the local offline provider:

```bash
python -m edm_auditor.rag build
python -m edm_auditor.rag count
python -m edm_auditor.rag search "annual leave" --threshold 0.1
```

The commands use `data/edm_auditor.sqlite3` and
`data/rag-index.sqlite3` by default. Override them with
`EDM_DATABASE_PATH`, `RAG_INDEX_PATH`, and `RAG_EMBEDDING_DIMENSION`.
`RAG_EMBEDDING_MODEL` currently supports only `deterministic-v1`; no network
service or API key is required.

Run all backend tests with:

```bash
pytest -q
```

The current suite contains 24 tests and does not require network access,
credentials, or real legal documents.

## Audit engine

The audit engine currently supports deterministic keyword, regular-expression,
and numeric rules. It extracts source-preserving ranges from document text,
creates `AuditFinding` entries, and stores an atomic `AuditReport`. Rule
parameters are JSON objects, for example:

```json
{"keywords": ["14 дней"], "recommendation": "Check the leave duration."}
```

The implementation does not require Natasha, an external embedding provider, or
an LLM. Semantic RAG validation and optional NLP enrichment remain separate
follow-up integrations.

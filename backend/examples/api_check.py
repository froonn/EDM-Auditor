"""Load a legal act, upload a document, run an API audit, and print the report."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from edm_auditor.database import create_engine_for, create_session_factory
from edm_auditor.model_config import ModelSettings
from edm_auditor.model_providers import create_embedding_provider
from edm_auditor.rag import (
    IndexSource,
    RAGIndexer,
    SQLiteVectorStore,
    TextLegalActIngestor,
)
from edm_auditor.rag.config import RAGSettings


def _multipart(file_path: Path, field: str = "file") -> tuple[bytes, str]:
    boundary = f"----edm-auditor-{uuid.uuid4().hex}"
    content = file_path.read_bytes()
    body = b"\r\n".join(
        [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{field}"; '
            f'filename="{file_path.name}"'.encode(),
            b"Content-Type: application/octet-stream",
            b"",
            content,
            f"--{boundary}--".encode(),
            b"",
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    content_type: str | None = None,
) -> dict:
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot connect to {base_url}: {exc.reason}") from exc


def _load_legal_act(args: argparse.Namespace) -> int:
    database = create_engine_for(args.database_url)
    session_factory = create_session_factory(database)
    legal_act = TextLegalActIngestor(session_factory).ingest(
        args.legal_act,
        code=args.legal_code,
        title=args.legal_title,
        number=args.legal_number,
        source_url=args.legal_source_url,
    )

    os.environ["EDM_DATABASE_PATH"] = args.database_path
    os.environ["RAG_INDEX_PATH"] = args.index_path
    if args.model_config:
        os.environ["EDM_MODEL_CONFIG"] = args.model_config
    if args.model_preset:
        os.environ["EDM_MODEL_PRESET"] = args.model_preset
    model = create_embedding_provider(ModelSettings.from_env().embedding)
    rag_settings = RAGSettings.from_env()
    store = SQLiteVectorStore(
        rag_settings.index_path,
        embedding_model=model.model_name,
        dimension=model.dimension,
        chunking_version="paragraph-v1",
    )
    count = RAGIndexer(store, model).build_atomic(
        [IndexSource(legal_act_id=legal_act.id, text=legal_act.article_text)],
        rag_settings.index_path,
    )
    print(f"loaded legal act {legal_act.id} and indexed {count} chunks", file=sys.stderr)
    return legal_act.id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one complete EDM-Auditor API check."
    )
    parser.add_argument("document", type=Path, help="DOCX, text-layer PDF, or UTF-8 TXT")
    parser.add_argument("--legal-act", type=Path, help="UTF-8 TXT legal act to ingest")
    parser.add_argument("--legal-code", default="LOCAL-EXAMPLE")
    parser.add_argument("--legal-title", default="Example legal act")
    parser.add_argument("--legal-number")
    parser.add_argument("--legal-source-url")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--database-url", default="sqlite:///data/edm_auditor.sqlite3")
    parser.add_argument("--database-path", default="data/edm_auditor.sqlite3")
    parser.add_argument("--index-path", default="data/rag-index.sqlite3")
    parser.add_argument("--model-config")
    parser.add_argument("--model-preset")
    args = parser.parse_args()

    if args.legal_act:
        _load_legal_act(args)

    body, content_type = _multipart(args.document)
    uploaded = _request(
        args.base_url,
        "POST",
        "/api/documents/upload",
        body=body,
        content_type=content_type,
    )
    document_id = uploaded["id"]
    audit = _request(args.base_url, "POST", f"/api/documents/{document_id}/audit")
    report = _request(args.base_url, "GET", f"/api/documents/{document_id}/report")

    print(
        json.dumps(
            {
                "document": uploaded,
                "audit": audit,
                "report": report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

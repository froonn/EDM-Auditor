from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.database import Base, create_session_factory
from edm_auditor.database.models import LegalAct


def make_client(tmp_path: Path) -> TestClient:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    settings = ApiSettings(upload_dir=tmp_path / "uploads", max_upload_bytes=1024)
    return TestClient(create_app(settings=settings, session_factory=session_factory))


def test_health_and_upload_document(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    assert client.get("/health").json() == {"status": "ok"}
    response = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"Employee receives 14 days leave.", "text/plain")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "contract"
    assert body["file_type"] == "txt"
    assert body["status"] == "uploaded"
    assert client.get(f"/api/documents/{body['id']}").status_code == 200


def test_upload_maps_parser_errors_and_size_limit(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    unsupported = client.post(
        "/api/documents/upload",
        files={"file": ("contract.doc", b"not supported", "application/msword")},
    )
    oversized = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"x" * 1025, "text/plain")},
    )

    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "unsupported_document_format"
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "document_too_large"


def test_create_rule_audit_and_get_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("contract.txt", b"Employee receives 14 days leave.", "text/plain")},
    )
    document_id = upload.json()["id"]

    rule = client.post(
        "/api/rules",
        json={
            "rule_code": "leave-short",
            "name": "Short leave",
            "severity": "high",
            "check_type": "keyword",
            "parameters": {"keywords": ["14 days"]},
        },
    )
    assert rule.status_code == 201
    assert client.get("/api/rules?check_type=keyword").json()[0]["rule_code"] == "leave-short"

    audit = client.post(f"/api/documents/{document_id}/audit")
    assert audit.status_code == 200
    report = client.get(f"/api/documents/{document_id}/report")

    assert report.status_code == 200
    assert report.json()["total_findings"] == 1
    assert report.json()["findings"][0]["quote"] == "14 days"


def test_list_legal_acts_does_not_expose_article_text(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    with client.app.state.session_factory.begin() as session:
        session.add(
            LegalAct(
                code="TK-RB",
                title="Labour Code",
                number="155",
                article_text="Private normative text",
            )
        )

    response = client.get("/api/legal-acts?search=labour")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "code": "TK-RB",
            "title": "Labour Code",
            "number": "155",
            "source_url": None,
        }
    ]

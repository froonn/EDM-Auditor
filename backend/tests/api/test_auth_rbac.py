"""End-to-end RBAC matrix, document isolation (IDOR), and auditor resolutions tests."""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.database.models import Document
from fakes import patch_fake_providers


@pytest.fixture(autouse=True)
def fake_model_providers(monkeypatch) -> None:
    patch_fake_providers(monkeypatch)


def _setup_app(tmp_path: Path):
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'rbac.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024 * 1024,
        rag_index_path=tmp_path / "rag-index.sqlite3",
        log_file=tmp_path / "debug.log",
        initial_admin_username="root",
        initial_admin_email="root@example.com",
        initial_admin_password="super-secret-password",
    )
    return create_app(settings=settings)


def _login(app, username: str, password: str) -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return client


def _create_user_with_groups(
    root_client: TestClient,
    *,
    username: str,
    full_name: str,
    group_ids: list[int],
) -> dict:
    resp = root_client.post(
        "/api/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": f"{username}-pass-123",
            "full_name": full_name,
            "custom_group_ids": group_ids,
            "must_change_password": False,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload_doc(client: TestClient, title: str, text: str) -> dict:
    resp = client.post(
        "/api/documents/upload",
        data={"title": title},
        files={"file": (f"{title}.txt", text.encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_anonymous_cannot_access_any_business_endpoint(tmp_path: Path) -> None:
    app = _setup_app(tmp_path)
    with TestClient(app) as anon:
        assert anon.get("/health").status_code == 200
        for method, path in (
            ("GET", "/api/documents"),
            ("POST", "/api/documents/upload"),
            ("GET", "/api/documents/1"),
            ("DELETE", "/api/documents/1"),
            ("POST", "/api/documents/1/audit"),
            ("GET", "/api/reports"),
            ("GET", "/api/reports/1"),
            ("GET", "/api/reports/1/export"),
            ("GET", "/api/reports/1/resolutions"),
            ("POST", "/api/reports/1/resolutions"),
            ("GET", "/api/rules"),
            ("POST", "/api/rules"),
            ("GET", "/api/legal-acts"),
            ("POST", "/api/legal-acts"),
            ("GET", "/api/document-types"),
            ("POST", "/api/document-types"),
            ("GET", "/api/document-type-suggestions"),
        ):
            resp = anon.request(method, path)
            assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"


def test_rbac_matrix_isolation_resolutions_and_linux_group_union(tmp_path: Path) -> None:
    app = _setup_app(tmp_path)

    # Seed a legacy unassigned document (user_id=None).
    with app.state.session_factory.begin() as session:
        legacy_doc = Document(
            user_id=None,
            title="Legacy Contract",
            file_type="txt",
            file_path="legacy.txt",
            raw_text="Приказ о предоставлении отпуска.\n\nОтпуск составляет 10 дней.",
            status="uploaded",
        )
        session.add(legacy_doc)
        session.flush()
        legacy_doc_id = legacy_doc.id

    root = _login(app, "root", "super-secret-password")
    groups = {
        g["name"]: g["id"]
        for g in root.get("/api/groups", params={"kind": "custom"}).json()
    }

    emp1_data = _create_user_with_groups(
        root, username="emp1", full_name="Ivan Petrov", group_ids=[groups["employee"]]
    )
    emp2_data = _create_user_with_groups(
        root, username="emp2", full_name="Maria Sidorova", group_ids=[groups["employee"]]
    )
    _create_user_with_groups(
        root, username="auditor1", full_name="Elena Auditor", group_ids=[groups["auditor"]]
    )
    _create_user_with_groups(
        root, username="lawyer1", full_name="Pavel Lawyer", group_ids=[groups["lawyer"]]
    )
    _create_user_with_groups(
        root, username="admin1", full_name="Olga Admin", group_ids=[groups["admin"]]
    )
    combo_data = _create_user_with_groups(
        root,
        username="combo1",
        full_name="Combo User",
        group_ids=[groups["employee"], groups["auditor"]],
    )

    emp1 = _login(app, "emp1", "emp1-pass-123")
    emp2 = _login(app, "emp2", "emp2-pass-123")
    auditor = _login(app, "auditor1", "auditor1-pass-123")
    lawyer = _login(app, "lawyer1", "lawyer1-pass-123")
    admin = _login(app, "admin1", "admin1-pass-123")
    combo = _login(app, "combo1", "combo1-pass-123")

    try:
        # 1. Lawyer manages legal acts, rules, and document types; auditor gets read-only (403 on edit).
        act_payload = {
            "code": "ACT-TEST",
            "title": "Test Labour Act",
            "article_text": "Отпуск составляет не менее 24 дней.",
        }
        assert emp1.get("/api/legal-acts").status_code == 403
        assert emp1.post("/api/legal-acts", json=act_payload).status_code == 403
        assert auditor.post("/api/legal-acts", json=act_payload).status_code == 403

        act_resp = lawyer.post("/api/legal-acts", json=act_payload)
        assert act_resp.status_code == 201
        act_id = act_resp.json()["id"]
        assert auditor.get("/api/legal-acts").status_code == 200
        assert auditor.get(f"/api/legal-acts/{act_id}").status_code == 200
        assert auditor.get(f"/api/legal-acts/{act_id}/diagnostics").status_code == 200

        rule_payload = {
            "rule_code": "R-LEAVE",
            "subject": "Продолжительность отпуска",
            "constraint_text": "Отпуск не менее 24 дней",
            "severity": "high",
            "applicability_scope": "universal",
            "legal_act_id": act_id,
        }
        assert auditor.post("/api/rules", json=rule_payload).status_code == 403
        rule_resp = lawyer.post("/api/rules", json=rule_payload)
        assert rule_resp.status_code == 201
        assert auditor.get("/api/rules").status_code == 200

        # Document types: employee can read catalog, only lawyer/admin can edit.
        assert emp1.get("/api/document-types").status_code == 200
        assert emp1.get("/api/document-type-suggestions").status_code == 403
        assert auditor.get("/api/document-type-suggestions").status_code == 200
        assert auditor.post(
            "/api/document-types",
            json={"code": "memo", "name": "Memo", "description": "Internal memo"},
        ).status_code == 403
        assert lawyer.post(
            "/api/document-types",
            json={"code": "memo", "name": "Memo", "description": "Internal memo"},
        ).status_code == 201
        # Lawyer cannot manage users or groups.
        assert lawyer.get("/api/users").status_code == 403
        assert lawyer.get("/api/groups").status_code == 403

        # 2. Employee uploads own document, gets owner metadata, CANNOT run audit.
        doc1 = _upload_doc(
            emp1, "emp1_contract", "Приказ о предоставлении отпуска.\n\nОтпуск составляет 10 дней."
        )
        doc2 = _upload_doc(
            emp2, "emp2_contract", "Приказ о предоставлении отпуска.\n\nОтпуск составляет 28 дней."
        )
        assert doc1["owner_id"] == emp1_data["id"]
        assert doc1["owner_name"] == "Ivan Petrov"
        assert emp1.post(f"/api/documents/{doc1['id']}/audit").status_code == 403
        assert emp1.post(f"/api/documents/{doc1['id']}/audit/preview").status_code == 403
        assert emp1.post(f"/api/documents/{doc1['id']}/classify").status_code == 403

        # 3. Document isolation (IDOR returns 404 for employee).
        emp1_docs = emp1.get("/api/documents").json()
        assert [d["id"] for d in emp1_docs] == [doc1["id"]]
        assert emp1.get(f"/api/documents/{doc2['id']}").status_code == 404
        assert emp1.get(f"/api/documents/{legacy_doc_id}").status_code == 404
        assert emp1.delete(f"/api/documents/{doc2['id']}").status_code == 404

        # 4. Auditor sees all docs (including legacy), can filter status=uploaded, runs audit & writes resolution.
        uploaded_docs = auditor.get("/api/documents", params={"status": "uploaded"}).json()
        assert {d["id"] for d in uploaded_docs} == {legacy_doc_id, doc1["id"], doc2["id"]}
        doc1_from_auditor = next(d for d in uploaded_docs if d["id"] == doc1["id"])
        assert doc1_from_auditor["owner_name"] == "Ivan Petrov"
        legacy_from_auditor = next(d for d in uploaded_docs if d["id"] == legacy_doc_id)
        assert legacy_from_auditor["owner_name"] is None

        audit_resp = auditor.post(f"/api/documents/{doc1['id']}/audit")
        assert audit_resp.status_code == 200
        report_id = audit_resp.json()["report_id"]

        # Employee cannot write resolutions, but CAN view and export own report + read auditor's resolution.
        assert (
            emp1.post(
                f"/api/reports/{report_id}/resolutions",
                json={"decision": "approved", "comment": "Self approve"},
            ).status_code
            == 403
        )
        res_resp = auditor.post(
            f"/api/reports/{report_id}/resolutions",
            json={"decision": "needs_revision", "comment": "Fix annual leave duration"},
        )
        assert res_resp.status_code == 201
        res_body = res_resp.json()
        assert res_body["author_name"] == "Elena Auditor"
        assert res_body["decision"] == "needs_revision"

        # Employee reads own report, resolution list, latest_resolution on doc & report, and exports HTML.
        own_report = emp1.get(f"/api/reports/{report_id}").json()
        assert own_report["latest_resolution"]["decision"] == "needs_revision"
        assert len(emp1.get(f"/api/reports/{report_id}/resolutions").json()) == 1
        assert emp1.get(f"/api/reports/{report_id}/export").status_code == 200
        own_doc_after = emp1.get("/api/documents").json()[0]
        assert own_doc_after["latest_report"]["latest_resolution"]["decision"] == "needs_revision"

        # Employee 2 gets 404 on emp1's report, resolutions, export, and sees empty /api/reports.
        assert emp2.get(f"/api/reports/{report_id}").status_code == 404
        assert emp2.get(f"/api/reports/{report_id}/resolutions").status_code == 404
        assert emp2.get(f"/api/reports/{report_id}/export").status_code == 404
        assert emp2.get("/api/reports").json() == []

        # 5. Deletion permissions: auditor cannot delete emp1's doc (403); admin CAN delete any doc.
        assert auditor.delete(f"/api/documents/{doc1['id']}").status_code == 403
        assert lawyer.delete(f"/api/documents/{doc1['id']}").status_code == 403

        # 6. Multi-group union (employee + auditor): combo user sees all docs and can run audit.
        assert combo.get(f"/api/documents/{doc2['id']}").status_code == 200
        assert combo.post(f"/api/documents/{doc2['id']}/audit").status_code == 200

        # 7. Personal group point-grant: grant audit.run only to emp2's personal group.
        assert emp2.post(f"/api/documents/{doc2['id']}/audit/preview").status_code == 403
        assert (
            root.put(
                f"/api/groups/{emp2_data['personal_group_id']}/permissions",
                json={"permissions": ["audit.run"]},
            ).status_code
            == 200
        )
        # Now emp2 CAN preview/audit own doc2, STILL gets 404 on doc1, and emp1 still gets 403 on own doc1!
        assert emp2.post(f"/api/documents/{doc2['id']}/audit/preview").status_code == 200
        assert emp2.post(f"/api/documents/{doc1['id']}/audit/preview").status_code == 404
        assert emp1.post(f"/api/documents/{doc1['id']}/audit/preview").status_code == 403

        # Admin deletes emp1's document (documents.delete_any).
        assert admin.delete(f"/api/documents/{doc1['id']}").status_code == 204
        # Employee 2 deletes own document (documents.delete_own).
        assert emp2.delete(f"/api/documents/{doc2['id']}").status_code == 204
    finally:
        for c in (root, emp1, emp2, auditor, lawyer, admin, combo):
            c.close()

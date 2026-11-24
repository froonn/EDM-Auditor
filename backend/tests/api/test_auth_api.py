from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from edm_auditor.api import create_app
from edm_auditor.api.config import ApiSettings
from edm_auditor.auth.permissions import Permission
from edm_auditor.auth.rate_limit import LoginRateLimiter
from fakes import patch_fake_providers


@pytest.fixture(autouse=True)
def fake_model_providers(monkeypatch) -> None:
    patch_fake_providers(monkeypatch)


def _make_app(tmp_path: Path, **overrides):
    settings = ApiSettings(
        database_url=f"sqlite:///{tmp_path / 'auth_api.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024 * 1024,
        rag_index_path=tmp_path / "rag-index.sqlite3",
        log_file=tmp_path / "debug.log",
        initial_admin_username="root",
        initial_admin_email="root@example.com",
        initial_admin_password="super-secret-password",
        **overrides,
    )
    return create_app(settings=settings), settings


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def test_login_cookie_me_logout_and_logout_all(tmp_path: Path) -> None:
    app, settings = _make_app(tmp_path)

    with TestClient(app) as client1, TestClient(app) as client2:
        # Unauthenticated calls return 401.
        assert client1.get("/api/auth/me").status_code == 401
        assert client1.get("/api/users").status_code == 401
        assert client1.get("/api/groups").status_code == 401
        assert client1.get("/api/permissions").status_code == 401
        assert client1.get("/api/auth/audit-log").status_code == 401

        # Failed login returns 401 and persists login_failed in audit log.
        bad = _login(client1, "root", "wrong-password")
        assert bad.status_code == 401
        assert bad.json()["error"]["code"] == "invalid_credentials"

        # Valid login sets HttpOnly cookie and returns profile + all 16 permissions.
        ok1 = _login(client1, "root", "super-secret-password")
        assert ok1.status_code == 200
        set_cookie = ok1.headers.get("set-cookie", "")
        assert settings.auth_cookie_name in set_cookie
        assert "httponly" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower()
        body = ok1.json()
        assert body["username"] == "root"
        assert body["is_super_admin"] is True
        assert body["must_change_password"] is False
        assert len(body["permissions"]) == len(Permission)

        assert client1.get("/api/auth/me").status_code == 200

        # Second session on another client.
        assert _login(client2, "root", "super-secret-password").status_code == 200
        assert client2.get("/api/auth/me").status_code == 200

        # Single logout invalidates only client2.
        assert client2.post("/api/auth/logout").status_code == 204
        assert client2.get("/api/auth/me").status_code == 401
        assert client1.get("/api/auth/me").status_code == 200

        # Audit log recorded the failed login.
        log_resp = client1.get("/api/auth/audit-log", params={"action": "login_failed"})
        assert log_resp.status_code == 200
        assert int(log_resp.headers["X-Total-Count"]) >= 1
        assert log_resp.json()[0]["action"] == "login_failed"

        # Log in client2 again, then logout-all from client1 invalidates both.
        assert _login(client2, "root", "super-secret-password").status_code == 200
        assert client1.post("/api/auth/logout-all").status_code == 204
        assert client1.get("/api/auth/me").status_code == 401
        assert client2.get("/api/auth/me").status_code == 401


def test_must_change_password_blocks_api_until_changed(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)

    with TestClient(app) as root_client, TestClient(app) as user_client, TestClient(app) as other_session:
        assert _login(root_client, "root", "super-secret-password").status_code == 200
        groups = {g["name"]: g["id"] for g in root_client.get("/api/groups", params={"kind": "custom"}).json()}

        created = root_client.post(
            "/api/users",
            json={
                "username": "orgadmin",
                "email": "orgadmin@example.com",
                "password": "temp-password-1",
                "full_name": "Org Admin",
                "custom_group_ids": [groups["admin"]],
            },
        )
        assert created.status_code == 201
        assert created.json()["must_change_password"] is True

        # User logs in on two sessions; protected endpoints return 403 password_change_required.
        assert _login(user_client, "orgadmin", "temp-password-1").status_code == 200
        assert _login(other_session, "orgadmin", "temp-password-1").status_code == 200

        me = user_client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["must_change_password"] is True

        blocked = user_client.get("/api/users")
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "password_change_required"

        # Changing password clears the flag, keeps current session, revokes other session.
        changed = user_client.post(
            "/api/auth/change-password",
            json={
                "current_password": "temp-password-1",
                "new_password": "new-personal-password-1",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["must_change_password"] is False
        assert user_client.get("/api/users").status_code == 200
        assert other_session.get("/api/auth/me").status_code == 401


def test_groups_users_delegation_ceiling_revoke_and_transfer(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)

    with TestClient(app) as root_client, TestClient(app) as admin_client, TestClient(app) as emp_client:
        assert _login(root_client, "root", "super-secret-password").status_code == 200

        # Permissions catalog exposes 16 permissions; groups.manage is super_admin_only.
        perms_catalog = root_client.get("/api/permissions").json()
        assert len(perms_catalog) == len(Permission)
        gm_entry = next(p for p in perms_catalog if p["code"] == "groups.manage")
        assert gm_entry["super_admin_only"] is True

        # Custom and personal groups are cleanly filterable by kind.
        custom_groups = root_client.get("/api/groups", params={"kind": "custom"}).json()
        custom_by_name = {g["name"]: g for g in custom_groups}
        assert set(custom_by_name) == {"employee", "auditor", "lawyer", "admin"}
        personal_groups = root_client.get("/api/groups", params={"kind": "personal"}).json()
        assert any(g["name"] == "root" and g["owner_username"] == "root" for g in personal_groups)

        # Create admin and employee users.
        admin_resp = root_client.post(
            "/api/users",
            json={
                "username": "alice_admin",
                "email": "alice@example.com",
                "password": "alice-password-1",
                "custom_group_ids": [custom_by_name["admin"]["id"]],
                "must_change_password": False,
            },
        )
        assert admin_resp.status_code == 201
        admin_id = admin_resp.json()["id"]

        emp_resp = root_client.post(
            "/api/users",
            json={
                "username": "bob_emp",
                "email": "bob@example.com",
                "password": "bob-password-1",
                "custom_group_ids": [custom_by_name["employee"]["id"]],
                "must_change_password": False,
            },
        )
        assert emp_resp.status_code == 201
        emp_id = emp_resp.json()["id"]
        emp_personal_group_id = emp_resp.json()["personal_group_id"]
        assert emp_personal_group_id is not None

        assert _login(admin_client, "alice_admin", "alice-password-1").status_code == 200
        assert _login(emp_client, "bob_emp", "bob-password-1").status_code == 200

        # Admin does NOT have groups.manage by default -> 403.
        assert (
            admin_client.post(
                "/api/groups",
                json={"name": "qa-team", "permissions": ["reports.read"]},
            ).status_code
            == 403
        )

        # Super-admin delegates groups.manage to 'admin' group.
        admin_perms = sorted(set(custom_by_name["admin"]["permissions"]) | {"groups.manage"})
        assert (
            root_client.put(
                f"/api/groups/{custom_by_name['admin']['id']}/permissions",
                json={"permissions": admin_perms},
            ).status_code
            == 200
        )

        # Now admin CAN create a custom group and customize Bob's personal group...
        qa = admin_client.post(
            "/api/groups",
            json={"name": "qa-team", "description": "QA", "permissions": ["reports.read"]},
        )
        assert qa.status_code == 201
        qa_id = qa.json()["id"]

        # ...rename/edit description...
        assert (
            admin_client.patch(f"/api/groups/{qa_id}", json={"description": "QA Reviewers"}).status_code
            == 200
        )

        # ...assign Bob to qa-team + employee (multi-group) -> cannot delete non-empty group.
        assert (
            admin_client.put(
                f"/api/users/{emp_id}/groups",
                json={"custom_group_ids": [custom_by_name["employee"]["id"], qa_id]},
            ).status_code
            == 200
        )
        non_empty = admin_client.delete(f"/api/groups/{qa_id}")
        assert non_empty.status_code == 409
        assert non_empty.json()["error"]["code"] == "group_not_empty"

        # Remove Bob from qa-team -> deletion succeeds.
        assert (
            admin_client.put(
                f"/api/users/{emp_id}/groups",
                json={"custom_group_ids": [custom_by_name["employee"]["id"]]},
            ).status_code
            == 200
        )
        assert admin_client.delete(f"/api/groups/{qa_id}").status_code == 204

        # Point-grant audit.run via Bob's personal group.
        assert (
            admin_client.put(
                f"/api/groups/{emp_personal_group_id}/permissions",
                json={"permissions": ["audit.run"]},
            ).status_code
            == 200
        )
        assert "audit.run" in emp_client.get("/api/auth/me").json()["permissions"]

        # Admin STILL cannot grant groups.manage (super-admin only).
        esc = admin_client.put(
            f"/api/groups/{emp_personal_group_id}/permissions",
            json={"permissions": ["audit.run", "groups.manage"]},
        )
        assert esc.status_code == 403
        assert esc.json()["error"]["code"] == "privilege_escalation"

        # Admin revokes Bob's active sessions -> Bob is immediately logged out.
        revoked = admin_client.post(f"/api/users/{emp_id}/revoke-sessions")
        assert revoked.status_code == 200
        assert revoked.json()["revoked_count"] == 1
        assert emp_client.get("/api/auth/me").status_code == 401

        # Transfer super-admin from root to alice_admin.
        transfer = root_client.post(
            "/api/auth/transfer-super-admin",
            json={
                "current_password": "super-secret-password",
                "target_user_id": admin_id,
            },
        )
        assert transfer.status_code == 200
        assert transfer.json()["new_super_admin_username"] == "alice_admin"

        assert root_client.get("/api/auth/me").json()["is_super_admin"] is False
        assert admin_client.get("/api/auth/me").json()["is_super_admin"] is True

        # Audit log contains transfer and session revocation events.
        audit_actions = {row["action"] for row in admin_client.get("/api/auth/audit-log").json()}
        assert {"super_admin_transferred", "user_sessions_revoked", "group_deleted"} <= audit_actions


def test_login_rate_limiting_csrf_origin_log_redaction_and_docs_toggle(tmp_path: Path) -> None:
    app, settings = _make_app(
        tmp_path,
        expose_docs=False,
        trace_log_bodies=False,
        trusted_origins=("https://trusted.example",),
    )
    app.state.login_rate_limiter = LoginRateLimiter(max_attempts=3, window_seconds=300)

    with TestClient(app) as client:
        # Docs disabled when expose_docs=False.
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404

        # Untrusted Origin on state-changing request is blocked by CSRF guard.
        csrf_bad = client.post(
            "/api/auth/login",
            json={"username": "root", "password": "super-secret-password"},
            headers={"Origin": "https://evil.example"},
        )
        assert csrf_bad.status_code == 403
        assert csrf_bad.json()["error"]["code"] == "csrf_origin_mismatch"

        # Trusted Origin is allowed.
        csrf_ok = client.post(
            "/api/auth/login",
            json={"username": "root", "password": "super-secret-password"},
            headers={"Origin": "https://trusted.example"},
        )
        assert csrf_ok.status_code == 200
        session_cookie_value = client.cookies.get(settings.auth_cookie_name)
        assert session_cookie_value

        # Trigger rate limit with 3 failed attempts on another username.
        for _ in range(3):
            resp = _login(client, "nobody", "wrong-pass-123")
            assert resp.status_code == 401
        limited = _login(client, "nobody", "wrong-pass-123")
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "too_many_requests"

        # Verify debug.log redacted cookies and never wrote passwords or raw tokens.
        log_text = settings.log_file.read_text(encoding="utf-8")
        assert "super-secret-password" not in log_text
        assert "wrong-pass-123" not in log_text
        assert session_cookie_value not in log_text
        assert "[REDACTED]" in log_text
        assert "[redacted sensitive payload]" in log_text

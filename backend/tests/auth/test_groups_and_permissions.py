from pathlib import Path

import pytest
from sqlalchemy import select

from edm_auditor.auth.audit_log import AuthAuditAction
from edm_auditor.auth.cli import main as cli_main
from edm_auditor.auth.errors import (
    AccountDisabledError,
    GroupNotEmptyError,
    InvalidCredentialsError,
    PermissionDeniedError,
    PrivilegeEscalationError,
    SuperAdminInvariantError,
)
from edm_auditor.auth.permissions import (
    ALL_PERMISSIONS,
    SUPER_ADMIN_GROUP_NAME,
    Permission,
    effective_permissions,
    ensure_default_groups,
    group_permissions,
)
from edm_auditor.auth.service import (
    authenticate_user,
    change_own_password,
    create_custom_group,
    create_super_admin,
    create_user,
    delete_custom_group,
    ensure_initial_super_admin,
    load_user_with_groups,
    revoke_target_user_sessions,
    set_group_permissions,
    set_user_groups,
    transfer_super_admin,
    update_user,
)
from edm_auditor.auth.sessions import authenticate_session, create_session
from edm_auditor.database import Base, create_engine_for, create_session_factory
from edm_auditor.database.enums import GroupKind
from edm_auditor.database.models import AuthAuditLog, Group, User


@pytest.fixture
def session_factory():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _bootstrap(session):
    groups = ensure_default_groups(session)
    super_admin = create_super_admin(
        session,
        username="root",
        email="root@example.com",
        password="super-secret-password",
        full_name="Root Admin",
    )
    return super_admin, groups


def test_default_groups_and_initial_super_admin_idempotency(session_factory) -> None:
    with session_factory.begin() as session:
        groups = ensure_default_groups(session)
        assert set(groups) == {SUPER_ADMIN_GROUP_NAME, "employee", "auditor", "lawyer", "admin"}

        # Employee does NOT have audit.run or documents.read_all by default.
        emp_perms = group_permissions(groups["employee"])
        assert Permission.DOCUMENTS_UPLOAD in emp_perms
        assert Permission.REPORTS_READ in emp_perms
        assert Permission.AUDIT_RUN not in emp_perms
        assert Permission.DOCUMENTS_READ_ALL not in emp_perms

        # Auditor has read-only legal acts/rules and resolutions.write, no *.edit.
        aud_perms = group_permissions(groups["auditor"])
        assert Permission.AUDIT_RUN in aud_perms
        assert Permission.RESOLUTIONS_WRITE in aud_perms
        assert Permission.LEGAL_ACTS_READ in aud_perms
        assert Permission.LEGAL_ACTS_EDIT not in aud_perms

        # Lawyer has *.edit, no users.manage.
        law_perms = group_permissions(groups["lawyer"])
        assert Permission.LEGAL_ACTS_EDIT in law_perms
        assert Permission.RULES_EDIT in law_perms
        assert Permission.DOCUMENT_TYPES_EDIT in law_perms
        assert Permission.USERS_MANAGE not in law_perms

        # Admin has users.manage, but groups.manage is off by default (delegatable by super-admin).
        adm_perms = group_permissions(groups["admin"])
        assert Permission.USERS_MANAGE in adm_perms
        assert Permission.GROUPS_MANAGE not in adm_perms

        sa1 = ensure_initial_super_admin(
            session,
            username="admin",
            email="admin@example.com",
            password="initial-password-1",
        )
        assert sa1 is not None
        assert sa1.is_super_admin is True
        assert sa1.must_change_password is False
        assert effective_permissions(sa1) == ALL_PERMISSIONS
        # Personal group 'admin' coexists with custom group 'admin'.
        assert sa1.personal_group is not None
        assert sa1.personal_group.name == "admin"
        assert sa1.personal_group.kind == GroupKind.PERSONAL.value

        # Second call is a no-op; direct create_super_admin raises.
        assert (
            ensure_initial_super_admin(
                session,
                username="other",
                email="other@example.com",
                password="another-password-1",
            )
            is None
        )
        with pytest.raises(SuperAdminInvariantError):
            create_super_admin(
                session,
                username="second",
                email="second@example.com",
                password="second-password-1",
            )


def test_linux_style_group_union_and_personal_group_override(session_factory) -> None:
    with session_factory.begin() as session:
        root, groups = _bootstrap(session)
        emp = create_user(
            session,
            actor=root,
            username="ivan",
            email="ivan@example.com",
            password="temp-password-1",
            custom_group_ids=[groups["employee"].id],
        )
        assert emp.must_change_password is True
        assert emp.personal_group is not None
        assert emp.personal_group.name == "ivan"
        assert group_permissions(emp.personal_group) == frozenset()
        assert Permission.AUDIT_RUN not in effective_permissions(emp)

        # Grant audit.run specifically via Ivan's personal group without touching 'employee'.
        set_group_permissions(
            session,
            actor=root,
            group_id=emp.personal_group.id,
            permissions=[Permission.AUDIT_RUN],
        )
        emp = load_user_with_groups(session, emp.id)
        assert Permission.AUDIT_RUN in effective_permissions(emp)
        assert Permission.AUDIT_RUN not in group_permissions(groups["employee"])

        # Add a second custom group ('lawyer'): permissions are additive union.
        set_user_groups(
            session,
            actor=root,
            target_user_id=emp.id,
            custom_group_ids=[groups["employee"].id, groups["lawyer"].id],
        )
        emp = load_user_with_groups(session, emp.id)
        perms = effective_permissions(emp)
        assert Permission.LEGAL_ACTS_EDIT in perms
        assert Permission.RULES_EDIT in perms
        assert Permission.DOCUMENTS_UPLOAD in perms


def test_custom_group_crud_and_non_empty_delete_guard(session_factory) -> None:
    with session_factory.begin() as session:
        root, groups = _bootstrap(session)
        # Starter custom groups (like employee) can be customized too.
        set_group_permissions(
            session,
            actor=root,
            group_id=groups["employee"].id,
            permissions=[Permission.DOCUMENTS_UPLOAD, Permission.REPORTS_READ, Permission.AUDIT_RUN],
        )
        assert Permission.AUDIT_RUN in group_permissions(groups["employee"])

        custom = create_custom_group(
            session,
            actor=root,
            name="reviewers",
            description="External reviewers",
            permissions=[Permission.REPORTS_READ, Permission.DOCUMENTS_READ_ALL],
        )
        user = create_user(
            session,
            actor=root,
            username="reviewer1",
            email="rev1@example.com",
            password="temp-password-1",
            custom_group_ids=[custom.id],
        )

        # Cannot delete while a user belongs to the group.
        with pytest.raises(GroupNotEmptyError):
            delete_custom_group(session, actor=root, group_id=custom.id)

        # Remove user from group -> deletion succeeds.
        set_user_groups(session, actor=root, target_user_id=user.id, custom_group_ids=[])
        delete_custom_group(session, actor=root, group_id=custom.id)
        assert session.get(Group, custom.id) is None


def test_privilege_ceiling_and_delegating_groups_manage(session_factory) -> None:
    with session_factory.begin() as session:
        root, groups = _bootstrap(session)

        # Create a narrow user-manager group (only users.manage + reports.read).
        narrow_mgr_group = create_custom_group(
            session,
            actor=root,
            name="hr-managers",
            permissions=[Permission.USERS_MANAGE, Permission.REPORTS_READ],
        )
        narrow_mgr = create_user(
            session,
            actor=root,
            username="hrmgr",
            email="hrmgr@example.com",
            password="temp-password-1",
            custom_group_ids=[narrow_mgr_group.id],
            must_change_password=False,
        )
        target = create_user(
            session,
            actor=root,
            username="alice",
            email="alice@example.com",
            password="temp-password-1",
            custom_group_ids=[groups["employee"].id],
        )

        # Narrow manager CANNOT assign 'admin' group (exceeds own ceiling).
        with pytest.raises(PrivilegeEscalationError):
            set_user_groups(
                session,
                actor=narrow_mgr,
                target_user_id=target.id,
                custom_group_ids=[groups["admin"].id],
            )

        # Create a full admin; by default admin has no groups.manage.
        admin_user = create_user(
            session,
            actor=root,
            username="orgadmin",
            email="orgadmin@example.com",
            password="temp-password-1",
            custom_group_ids=[groups["admin"].id],
            must_change_password=False,
        )
        with pytest.raises(PermissionDeniedError):
            create_custom_group(
                session, actor=admin_user, name="nope", permissions=[Permission.REPORTS_READ]
            )

        # Admin cannot edit or disable super-admin, nor disable self or drop own users.manage.
        with pytest.raises(PermissionDeniedError):
            update_user(session, actor=admin_user, target_user_id=root.id, full_name="Hacked")
        with pytest.raises(PermissionDeniedError):
            update_user(session, actor=admin_user, target_user_id=admin_user.id, is_active=False)
        with pytest.raises(PermissionDeniedError):
            set_user_groups(
                session, actor=admin_user, target_user_id=admin_user.id, custom_group_ids=[]
            )

        # Super-admin delegates groups.manage to 'admin' group.
        set_group_permissions(
            session,
            actor=root,
            group_id=groups["admin"].id,
            permissions=group_permissions(groups["admin"]) | {Permission.GROUPS_MANAGE},
        )
        admin_user = load_user_with_groups(session, admin_user.id)

        # Now admin CAN create custom groups with normal permissions...
        qa_group = create_custom_group(
            session,
            actor=admin_user,
            name="qa-viewers",
            permissions=[Permission.REPORTS_READ],
        )
        assert qa_group.name == "qa-viewers"

        # ...but still CANNOT grant or revoke groups.manage (super-admin only).
        with pytest.raises(PrivilegeEscalationError):
            set_group_permissions(
                session,
                actor=admin_user,
                group_id=qa_group.id,
                permissions=[Permission.REPORTS_READ, Permission.GROUPS_MANAGE],
            )
        # ...and cannot modify system super-admin group.
        with pytest.raises(PermissionDeniedError):
            set_group_permissions(
                session,
                actor=admin_user,
                group_id=groups[SUPER_ADMIN_GROUP_NAME].id,
                permissions=[],
            )


def test_transfer_super_admin_and_password_and_session_revocation(session_factory) -> None:
    with session_factory.begin() as session:
        root, groups = _bootstrap(session)
        successor = create_user(
            session,
            actor=root,
            username="successor",
            email="succ@example.com",
            password="temp-password-1",
            custom_group_ids=[groups["admin"].id],
        )
        disabled = create_user(
            session,
            actor=root,
            username="disabled_u",
            email="dis@example.com",
            password="temp-password-1",
            custom_group_ids=[groups["employee"].id],
        )
        update_user(session, actor=root, target_user_id=disabled.id, is_active=False)

        # Disabled user cannot log in.
        with pytest.raises(AccountDisabledError):
            authenticate_user(session, username="disabled_u", password="temp-password-1")

        # Cannot disable super-admin before transfer.
        with pytest.raises(SuperAdminInvariantError):
            update_user(session, actor=root, target_user_id=root.id, is_active=False)

        # Wrong password rejected for transfer.
        with pytest.raises(InvalidCredentialsError):
            transfer_super_admin(
                session,
                actor=root,
                current_password="wrong-password",
                target_user_id=successor.id,
            )

        # Disabled target rejected for transfer.
        with pytest.raises(SuperAdminInvariantError):
            transfer_super_admin(
                session,
                actor=root,
                current_password="super-secret-password",
                target_user_id=disabled.id,
            )

        # Valid transfer succeeds atomically.
        new_super = transfer_super_admin(
            session,
            actor=root,
            current_password="super-secret-password",
            target_user_id=successor.id,
        )
        root_after = load_user_with_groups(session, root.id)
        new_super = load_user_with_groups(session, new_super.id)
        assert root_after.is_super_admin is False
        assert new_super.is_super_admin is True
        assert SUPER_ADMIN_GROUP_NAME not in {g.name for g in root_after.groups}
        assert SUPER_ADMIN_GROUP_NAME in {g.name for g in new_super.groups}
        # Old super-admin still keeps their custom 'admin' group.
        assert "admin" in {g.name for g in root_after.groups}

        # Password change clears must_change_password and revokes other sessions.
        tok_keep, s_keep = create_session(session, new_super)
        tok_drop, _ = create_session(session, new_super)
        change_own_password(
            session,
            user=new_super,
            current_password="temp-password-1",
            new_password="brand-new-password-1",
            current_session_id=s_keep.id,
        )
        assert new_super.must_change_password is False
        assert authenticate_session(session, tok_keep) is not None
        assert authenticate_session(session, tok_drop) is None

        # Admin revokes target user sessions.
        tok_root, _ = create_session(session, root_after)
        revoked = revoke_target_user_sessions(
            session, actor=new_super, target_user_id=root_after.id
        )
        assert revoked == 1
        assert authenticate_session(session, tok_root) is None

        actions = session.scalars(select(AuthAuditLog.action)).all()
        assert AuthAuditAction.SUPER_ADMIN_TRANSFERRED.value in actions
        assert AuthAuditAction.PASSWORD_CHANGED.value in actions
        assert AuthAuditAction.USER_SESSIONS_REVOKED.value in actions


def test_auth_cli_seed_and_create_super_admin(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'cli.sqlite3'}"
    assert cli_main(["--database-url", db_url, "seed-groups"]) == 0
    assert (
        cli_main(
            [
                "--database-url",
                db_url,
                "create-super-admin",
                "--username",
                "cliadmin",
                "--email",
                "cliadmin@example.com",
                "--password",
                "super-cli-pass-1",
            ]
        )
        == 0
    )
    # Second super-admin fails with exit code 1.
    assert (
        cli_main(
            [
                "--database-url",
                db_url,
                "create-super-admin",
                "--username",
                "cliadmin2",
                "--email",
                "cliadmin2@example.com",
                "--password",
                "super-cli-pass-2",
            ]
        )
        == 1
    )

    engine = create_engine_for(db_url)
    try:
        with create_session_factory(engine)() as session:
            sa_user = session.scalar(select(User).where(User.username == "cliadmin"))
            assert sa_user is not None
            assert sa_user.is_super_admin is True
    finally:
        engine.dispose()

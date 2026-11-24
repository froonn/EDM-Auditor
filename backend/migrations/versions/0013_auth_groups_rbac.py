"""Add Linux-style group RBAC, sessions, auditor resolutions, and auth audit log."""

from collections.abc import Sequence
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

from edm_auditor.auth.permissions import (
    ALL_PERMISSIONS,
    DEFAULT_CUSTOM_GROUPS,
    LEGACY_ROLE_TO_GROUP,
    SUPER_ADMIN_GROUP_NAME,
)

revision: str = "0013_auth_groups_rbac"
down_revision: str | Sequence[str] | None = "0012_stage4_finding_statement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _create_users_table_if_missing(inspector: sa.Inspector) -> list[tuple[int, str, str]]:
    """Ensure `users` matches the new schema and return legacy (id, username, role) rows."""
    if not inspector.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(100), nullable=False, unique=True),
            sa.Column("email", sa.String(255), nullable=False, unique=True),
            sa.Column("full_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("hashed_password", sa.String(255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_super_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "uq_users_single_super_admin",
            "users",
            ["is_super_admin"],
            unique=True,
            sqlite_where=sa.text("is_super_admin = 1"),
            postgresql_where=sa.text("is_super_admin = true"),
        )
        return []

    bind = op.get_bind()
    columns = {col["name"] for col in inspector.get_columns("users")}
    legacy_rows: list[tuple[int, str, str]] = []
    if "role" in columns:
        rows = bind.execute(sa.text("SELECT id, username, role FROM users ORDER BY id")).fetchall()
        legacy_rows = [(int(r[0]), str(r[1]), str(r[2] or "employee")) for r in rows]

    needs_alter = (
        "role" in columns
        or "full_name" not in columns
        or "is_active" not in columns
        or "is_super_admin" not in columns
        or "must_change_password" not in columns
        or "updated_at" not in columns
        or "last_login_at" not in columns
    )
    if needs_alter:
        now_iso = _utc_now().isoformat()
        with op.batch_alter_table("users") as batch_op:
            if "full_name" not in columns:
                batch_op.add_column(
                    sa.Column("full_name", sa.String(255), nullable=False, server_default="")
                )
            if "is_active" not in columns:
                batch_op.add_column(
                    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
                )
            if "is_super_admin" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "is_super_admin", sa.Boolean(), nullable=False, server_default=sa.false()
                    )
                )
            if "must_change_password" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "must_change_password",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    )
                )
            if "updated_at" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "updated_at", sa.DateTime(), nullable=False, server_default=now_iso
                    )
                )
            if "last_login_at" not in columns:
                batch_op.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))
            if "role" in columns:
                batch_op.drop_column("role")

    existing_indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("users")}
    if "uq_users_single_super_admin" not in existing_indexes:
        op.create_index(
            "uq_users_single_super_admin",
            "users",
            ["is_super_admin"],
            unique=True,
            sqlite_where=sa.text("is_super_admin = 1"),
            postgresql_where=sa.text("is_super_admin = true"),
        )

    return legacy_rows


def _seed_groups_and_migrate_users(legacy_rows: list[tuple[int, str, str]]) -> None:
    bind = op.get_bind()
    now_str = _utc_now().replace(tzinfo=None).isoformat(sep=" ")

    def ensure_group(name: str, kind: str, description: str, perms: set[str]) -> int:
        row = bind.execute(
            sa.text("SELECT id FROM groups WHERE kind = :kind AND name = :name"),
            {"kind": kind, "name": name},
        ).fetchone()
        if row is not None:
            return int(row[0])
        res = bind.execute(
            sa.text(
                "INSERT INTO groups (name, kind, description, owner_user_id, created_at, updated_at) "
                "VALUES (:name, :kind, :description, NULL, :created_at, :updated_at)"
            ),
            {
                "name": name,
                "kind": kind,
                "description": description,
                "created_at": now_str,
                "updated_at": now_str,
            },
        )
        group_id = int(res.lastrowid)
        for perm in sorted(perms):
            bind.execute(
                sa.text(
                    "INSERT INTO group_permissions (group_id, permission) "
                    "VALUES (:group_id, :permission)"
                ),
                {"group_id": group_id, "permission": perm},
            )
        return group_id

    ensure_group(
        SUPER_ADMIN_GROUP_NAME,
        "system",
        "Single system super-administrator with unrestricted permissions",
        {p.value for p in ALL_PERMISSIONS},
    )
    custom_group_ids: dict[str, int] = {}
    for name, (description, perms) in DEFAULT_CUSTOM_GROUPS.items():
        custom_group_ids[name] = ensure_group(
            name, "custom", description, {p.value for p in perms}
        )

    for user_id, username, old_role in legacy_rows:
        personal = bind.execute(
            sa.text("SELECT id FROM groups WHERE owner_user_id = :uid"),
            {"uid": user_id},
        ).fetchone()
        if personal is None:
            res = bind.execute(
                sa.text(
                    "INSERT INTO groups (name, kind, description, owner_user_id, created_at, updated_at) "
                    "VALUES (:name, 'personal', :description, :uid, :created_at, :updated_at)"
                ),
                {
                    "name": username,
                    "description": f"Personal group for user {username}",
                    "uid": user_id,
                    "created_at": now_str,
                    "updated_at": now_str,
                },
            )
            personal_id = int(res.lastrowid)
        else:
            personal_id = int(personal[0])

        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO user_groups (user_id, group_id, assigned_at) "
                "VALUES (:uid, :gid, :assigned_at)"
            ),
            {"uid": user_id, "gid": personal_id, "assigned_at": now_str},
        )
        mapped_group_name = LEGACY_ROLE_TO_GROUP.get(old_role, "employee")
        mapped_group_id = custom_group_ids[mapped_group_name]
        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO user_groups (user_id, group_id, assigned_at) "
                "VALUES (:uid, :gid, :assigned_at)"
            ),
            {"uid": user_id, "gid": mapped_group_id, "assigned_at": now_str},
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    legacy_rows = _create_users_table_if_missing(inspector)

    if not inspector.has_table("groups"):
        op.create_table(
            "groups",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="custom"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "owner_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
                unique=True,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("kind", "name", name="uq_groups_kind_name"),
            sa.CheckConstraint(
                "kind IN ('system', 'custom', 'personal')",
                name="ck_groups_kind",
            ),
            sa.CheckConstraint(
                "(kind = 'personal' AND owner_user_id IS NOT NULL) "
                "OR (kind <> 'personal' AND owner_user_id IS NULL)",
                name="ck_groups_personal_owner",
            ),
        )

    if not inspector.has_table("group_permissions"):
        op.create_table(
            "group_permissions",
            sa.Column(
                "group_id",
                sa.Integer(),
                sa.ForeignKey("groups.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("permission", sa.String(64), primary_key=True),
        )

    if not inspector.has_table("user_groups"):
        op.create_table(
            "user_groups",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "group_id",
                sa.Integer(),
                sa.ForeignKey("groups.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("assigned_at", sa.DateTime(), nullable=False),
        )

    if not inspector.has_table("user_sessions"):
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("ip_address", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.String(500), nullable=True),
        )

    if not inspector.has_table("audit_resolutions"):
        op.create_table(
            "audit_resolutions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "report_id",
                sa.Integer(),
                sa.ForeignKey("audit_reports.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "author_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("author_name", sa.String(255), nullable=False),
            sa.Column("decision", sa.String(20), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "decision IN ('approved', 'needs_revision', 'rejected')",
                name="ck_audit_resolutions_decision",
            ),
        )

    if not inspector.has_table("auth_audit_log"):
        op.create_table(
            "auth_audit_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "actor_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("actor_username", sa.String(100), nullable=False, server_default=""),
            sa.Column("action", sa.String(50), nullable=False, index=True),
            sa.Column("target_type", sa.String(30), nullable=True),
            sa.Column("target_id", sa.String(100), nullable=True),
            sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("ip_address", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
            sa.CheckConstraint(
                "json_valid(details_json)",
                name="ck_auth_audit_log_details_json",
            ),
        )

    _seed_groups_and_migrate_users(legacy_rows)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name in (
        "auth_audit_log",
        "audit_resolutions",
        "user_sessions",
        "user_groups",
        "group_permissions",
        "groups",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)

    if inspector.has_table("users"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
        if "uq_users_single_super_admin" in existing_indexes:
            op.drop_index("uq_users_single_super_admin", table_name="users")
        columns = {col["name"] for col in inspector.get_columns("users")}
        with op.batch_alter_table("users") as batch_op:
            if "role" not in columns:
                batch_op.add_column(
                    sa.Column("role", sa.String(20), nullable=False, server_default="hr")
                )
            for col in (
                "full_name",
                "is_active",
                "is_super_admin",
                "must_change_password",
                "updated_at",
                "last_login_at",
            ):
                if col in columns:
                    batch_op.drop_column(col)

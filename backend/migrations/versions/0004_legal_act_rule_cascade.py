"""Delete audit rules when their legal act is deleted."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from edm_auditor.database.models import AuditRule, Base

revision: str = "0004_legal_act_rule_cascade"
down_revision: str | Sequence[str] | None = "0003_date_duration_rule_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _legal_act_ondelete() -> str | None:
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys("audit_rules"):
        if foreign_key.get("constrained_columns") == ["legal_act_id"]:
            options = foreign_key.get("options") or {}
            return options.get("ondelete")
    return None


def _rebuild_rules_table(ondelete: str) -> None:
    columns = [column.name for column in AuditRule.__table__.columns]
    metadata = sa.MetaData()
    Base.metadata.tables["legal_acts"].to_metadata(metadata)
    new_table = AuditRule.__table__.to_metadata(metadata, name="audit_rules_new")
    for foreign_key in new_table.foreign_keys:
        if foreign_key.parent.name == "legal_act_id":
            foreign_key.constraint.ondelete = ondelete

    with op.get_context().autocommit_block():
        bind = op.get_bind()
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        bind.exec_driver_sql("PRAGMA legacy_alter_table=ON")
        op.rename_table("audit_rules", "audit_rules_old")
        new_table.create(bind)
        column_list = ", ".join(columns)
        bind.exec_driver_sql(
            f"INSERT INTO audit_rules_new ({column_list}) "
            f"SELECT {column_list} FROM audit_rules_old"
        )
        op.drop_table("audit_rules_old")
        op.rename_table("audit_rules_new", "audit_rules")
        bind.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    if _legal_act_ondelete() != "CASCADE":
        _rebuild_rules_table("CASCADE")


def downgrade() -> None:
    if _legal_act_ondelete() != "SET NULL":
        _rebuild_rules_table("SET NULL")

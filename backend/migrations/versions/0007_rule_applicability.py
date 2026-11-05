"""Add rule and legal-act applicability and retire the single rule document type."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_rule_applicability"
down_revision: str | Sequence[str] | None = "0006_document_classification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("applicability_scope", sa.String(20), {"nullable": False, "server_default": "unknown"}),
    ("applicability_confidence", sa.Float(), {"nullable": True}),
    ("applicability_source", sa.String(50), {"nullable": True}),
)


def upgrade() -> None:
    op.create_table(
        "rule_document_types",
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("audit_rules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_type_code", sa.String(100), sa.ForeignKey("document_types.code", ondelete="RESTRICT"), primary_key=True),
        if_not_exists=True,
    )
    op.create_table(
        "legal_act_document_types",
        sa.Column("legal_act_id", sa.Integer(), sa.ForeignKey("legal_acts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_type_code", sa.String(100), sa.ForeignKey("document_types.code", ondelete="RESTRICT"), primary_key=True),
        if_not_exists=True,
    )
    bind = op.get_bind()
    existing = {item["name"] for item in sa.inspect(bind).get_columns("audit_rules")}
    for name, column_type, options in COLUMNS:
        if name not in existing:
            op.add_column("audit_rules", sa.Column(name, column_type, **options))

    if "document_type" in existing:
        # A stored type stays a typed rule; its value becomes a catalog entry if it is new.
        bind.exec_driver_sql(
            "INSERT OR IGNORE INTO document_types (code, name) "
            "SELECT DISTINCT document_type, document_type FROM audit_rules "
            "WHERE document_type IS NOT NULL AND document_type <> 'unknown'"
        )
        bind.exec_driver_sql(
            "INSERT OR IGNORE INTO rule_document_types (rule_id, document_type_code) "
            "SELECT id, document_type FROM audit_rules "
            "WHERE document_type IS NOT NULL AND document_type <> 'unknown'"
        )
        bind.exec_driver_sql(
            "UPDATE audit_rules SET applicability_scope = 'typed', "
            "applicability_confidence = 1.0, applicability_source = 'migration' "
            "WHERE document_type IS NOT NULL AND document_type <> 'unknown'"
        )
        # A manual rule without a type already applied to every document: keep that meaning.
        # A generated rule never received such a decision, so its scope stays unknown.
        bind.exec_driver_sql(
            "UPDATE audit_rules SET applicability_scope = 'universal', "
            "applicability_confidence = 1.0, applicability_source = 'migration' "
            "WHERE document_type IS NULL AND is_generated = 0"
        )
        bind.exec_driver_sql(
            "UPDATE audit_rules SET applicability_scope = 'unknown', "
            "applicability_source = 'migration' "
            "WHERE is_generated = 1 AND document_type IS NULL"
        )
        # A table rebuild here would fire ON DELETE SET NULL and erase findings' rule links.
        bind.exec_driver_sql("ALTER TABLE audit_rules DROP COLUMN document_type")


def downgrade() -> None:
    bind = op.get_bind()
    op.add_column("audit_rules", sa.Column("document_type", sa.String(100), nullable=True))
    bind.exec_driver_sql(
        "UPDATE audit_rules SET document_type = ("
        "SELECT MIN(document_type_code) FROM rule_document_types "
        "WHERE rule_document_types.rule_id = audit_rules.id)"
    )
    for name, _, _ in reversed(COLUMNS):
        bind.exec_driver_sql(f"ALTER TABLE audit_rules DROP COLUMN {name}")
    op.drop_table("legal_act_document_types")
    op.drop_table("rule_document_types")

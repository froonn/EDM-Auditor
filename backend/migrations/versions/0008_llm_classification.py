"""Store model answers for rules, add type suggestions, and retire classifier profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_llm_classification"
down_revision: str | Sequence[str] | None = "0007_rule_applicability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # The first migration builds a new database from the current models.
    rule_columns = {item["name"] for item in sa.inspect(bind).get_columns("audit_rules")}
    type_columns = {item["name"] for item in sa.inspect(bind).get_columns("document_types")}
    if "applicability_auto" not in rule_columns:
        op.add_column("audit_rules", sa.Column("applicability_auto", sa.Text(), nullable=True))
    op.create_table(
        "document_type_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False, unique=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("legal_act_id", sa.Integer(), sa.ForeignKey("legal_acts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("accepted_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'dismissed')",
            name="ck_document_type_suggestions_status",
        ),
        if_not_exists=True,
    )
    bind.exec_driver_sql(
        "UPDATE documents SET classification_source = 'legacy' "
        "WHERE classification_source = 'deterministic'"
    )
    # Earlier answers stay in force; they are replaced when the act is processed again.
    bind.exec_driver_sql(
        "UPDATE audit_rules SET applicability_source = 'migration' "
        "WHERE applicability_source = 'legal_act_classifier'"
    )
    if "classifier_profile" in type_columns:
        bind.exec_driver_sql("ALTER TABLE document_types DROP COLUMN classifier_profile")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE document_types ADD COLUMN classifier_profile TEXT NOT NULL DEFAULT '{}'"
    )
    op.drop_table("document_type_suggestions")
    bind.exec_driver_sql("ALTER TABLE audit_rules DROP COLUMN applicability_auto")

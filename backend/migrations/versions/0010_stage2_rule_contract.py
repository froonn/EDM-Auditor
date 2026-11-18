"""Reset audit data and replace legacy rule types with the stage 2 contract."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0010_stage2_rule_contract"
down_revision: str | Sequence[str] | None = "0009_finding_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Reports and generated rules are disposable by design; legal acts/documents remain.
    for table in ("audit_findings", "audit_reports", "rule_extraction_results", "rule_document_types", "audit_rules"):
        if sa.inspect(bind).has_table(table):
            op.drop_table(table)

    op.create_table(
        "audit_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_code", sa.String(100), nullable=False, unique=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("constraint_text", sa.Text(), nullable=False),
        sa.Column("constraint_json", sa.Text(), nullable=True),
        sa.Column("condition", sa.Text(), nullable=False, server_default=""),
        sa.Column("applicability_scope", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("applicability_confidence", sa.Float(), nullable=True),
        sa.Column("applicability_source", sa.String(50), nullable=True),
        sa.Column("applicability_auto", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("legal_act_id", sa.Integer(), sa.ForeignKey("legal_acts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("is_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deduplication_key", sa.String(64), unique=True, nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("source_location", sa.String(255), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=True),
        sa.Column("source_end", sa.Integer(), nullable=True),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_rules_severity"),
        sa.CheckConstraint("constraint_json IS NULL OR json_valid(constraint_json)", name="ck_rules_constraint_json"),
        sa.CheckConstraint("applicability_scope IN ('universal', 'typed', 'manual_only', 'unknown')", name="ck_rules_applicability_scope"),
    )
    op.create_table(
        "rule_document_types",
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("audit_rules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_type_code", sa.String(50), sa.ForeignKey("document_types.code", ondelete="RESTRICT"), primary_key=True),
    )
    # Recreate dependent tables from the current metadata without legacy data.
    from edm_auditor.database.models import AuditFinding, AuditReport, RuleExtractionResult
    for table in (AuditReport.__table__, AuditFinding.__table__, RuleExtractionResult.__table__):
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("stage 2 rule contract migration is destructive and cannot be downgraded")

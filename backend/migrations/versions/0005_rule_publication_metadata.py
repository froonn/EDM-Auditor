"""Store generated-rule provenance and extraction publication results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_rule_publication_metadata"
down_revision: str | Sequence[str] | None = "0004_legal_act_rule_cascade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # 0001 creates the schema from the current models, so these objects may already exist.
    existing = _columns("legal_acts")
    for name, column in (
        ("processing_status", sa.Column("processing_status", sa.String(20), nullable=False, server_default="uploaded")),
        ("processing_version", sa.Column("processing_version", sa.String(50), nullable=True)),
        ("chunks_total", sa.Column("chunks_total", sa.Integer(), nullable=False, server_default="0")),
        ("chunks_processed", sa.Column("chunks_processed", sa.Integer(), nullable=False, server_default="0")),
        ("rules_accepted", sa.Column("rules_accepted", sa.Integer(), nullable=False, server_default="0")),
        ("rules_rejected", sa.Column("rules_rejected", sa.Integer(), nullable=False, server_default="0")),
    ):
        if name not in existing:
            op.add_column("legal_acts", column)

    existing = _columns("audit_rules")
    for name, column in (
        ("is_generated", sa.Column("is_generated", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("deduplication_key", sa.Column("deduplication_key", sa.String(64), nullable=True)),
        ("source_quote", sa.Column("source_quote", sa.Text(), nullable=True)),
        ("source_location", sa.Column("source_location", sa.String(255), nullable=True)),
        ("source_start", sa.Column("source_start", sa.Integer(), nullable=True)),
        ("source_end", sa.Column("source_end", sa.Integer(), nullable=True)),
    ):
        if name not in existing:
            op.add_column("audit_rules", column)
    op.create_index(
        "uq_audit_rules_deduplication_key",
        "audit_rules",
        ["deduplication_key"],
        unique=True,
        if_not_exists=True,
    )

    op.create_table(
        "rule_extraction_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("legal_act_id", sa.Integer(), sa.ForeignKey("legal_acts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("diagnostic_message", sa.Text(), nullable=True),
        sa.Column("rules_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rules_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rules_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processing_version", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legal_act_id", "chunk_id", name="uq_extraction_result_chunk"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'failed', 'partial')",
            name="ck_extraction_result_status",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_rule_extraction_results_legal_act_id",
        "rule_extraction_results",
        ["legal_act_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_rule_extraction_results_legal_act_id", table_name="rule_extraction_results")
    op.drop_table("rule_extraction_results")
    op.drop_index("uq_audit_rules_deduplication_key", table_name="audit_rules")
    for name in ("source_end", "source_start", "source_location", "source_quote", "deduplication_key", "is_generated"):
        op.drop_column("audit_rules", name)
    for name in ("rules_rejected", "rules_accepted", "chunks_processed", "chunks_total", "processing_version", "processing_status"):
        op.drop_column("legal_acts", name)

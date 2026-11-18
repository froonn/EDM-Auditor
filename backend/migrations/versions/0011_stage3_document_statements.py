"""Add document statements storage and statement extraction version tracking."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0011_stage3_document_statements"
down_revision: str | Sequence[str] | None = "0010_stage2_rule_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    doc_columns = {item["name"] for item in inspector.get_columns("documents")}
    if "statements_version" not in doc_columns:
        op.add_column("documents", sa.Column("statements_version", sa.String(50), nullable=True))

    if not inspector.has_table("document_statements"):
        op.create_table(
            "document_statements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "document_id",
                sa.Integer(),
                sa.ForeignKey("documents.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("statement_text", sa.Text(), nullable=False),
            sa.Column("constraint_json", sa.Text(), nullable=True),
            sa.Column("source_quote", sa.Text(), nullable=False),
            sa.Column("start_char", sa.Integer(), nullable=False),
            sa.Column("end_char", sa.Integer(), nullable=False),
            sa.Column("prompt_version", sa.String(50), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.CheckConstraint(
                "start_char >= 0 AND end_char >= start_char",
                name="ck_document_statements_range",
            ),
            sa.CheckConstraint(
                "constraint_json IS NULL OR json_valid(constraint_json)",
                name="ck_document_statements_constraint_json",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("document_statements"):
        op.drop_table("document_statements")
    doc_columns = {item["name"] for item in inspector.get_columns("documents")}
    if "statements_version" in doc_columns:
        bind.exec_driver_sql("ALTER TABLE documents DROP COLUMN statements_version")

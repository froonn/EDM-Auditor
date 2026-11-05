"""Add the document type catalog and document classification fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_document_classification"
down_revision: str | Sequence[str] | None = "0005_rule_publication_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("classification_confidence", sa.Float()),
    ("classification_status", sa.String(20)),
    ("classification_candidates", sa.Text()),
    ("classification_source", sa.String(20)),
    ("classification_auto", sa.Text()),
)


def upgrade() -> None:
    op.create_table(
        "document_types",
        sa.Column("code", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("classifier_profile", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("code <> 'unknown'", name="ck_document_types_code"),
        if_not_exists=True,
    )
    op.create_table(
        "document_confirmed_types",
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_type_code", sa.String(100), sa.ForeignKey("document_types.code", ondelete="RESTRICT"), primary_key=True),
        if_not_exists=True,
    )
    bind = op.get_bind()
    existing = {item["name"] for item in sa.inspect(bind).get_columns("documents")}
    for name, column_type in COLUMNS:
        if name not in existing:
            op.add_column("documents", sa.Column(name, column_type, nullable=True))

    # Previously stored free-form types stay valid: they become catalog entries.
    bind.exec_driver_sql(
        "INSERT OR IGNORE INTO document_types (code, name) "
        "SELECT DISTINCT classified_type, classified_type FROM documents "
        "WHERE classified_type IS NOT NULL AND classified_type <> 'unknown'"
    )
    bind.exec_driver_sql(
        "INSERT OR IGNORE INTO document_confirmed_types (document_id, document_type_code) "
        "SELECT id, classified_type FROM documents "
        "WHERE classified_type IS NOT NULL AND classified_type <> 'unknown'"
    )
    bind.exec_driver_sql(
        "UPDATE documents SET classification_status = 'classified', classification_source = 'legacy' "
        "WHERE classified_type IS NOT NULL AND classified_type <> 'unknown' "
        "AND classification_status IS NULL"
    )


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("documents", name)
    op.drop_table("document_confirmed_types")
    op.drop_table("document_types")

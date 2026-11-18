"""Keep the document statement and the evaluation mode in a finding."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0012_stage4_finding_statement"
down_revision: str | Sequence[str] | None = "0011_stage3_document_statements"
branch_labels = None
depends_on = None

COLUMNS = {
    "statement_text": sa.Text(),
    "evaluation_mode": sa.String(20),
}


def upgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("audit_findings")}
    for name, column_type in COLUMNS.items():
        if name not in existing:
            op.add_column("audit_findings", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("audit_findings")}
    for name in COLUMNS:
        if name in existing:
            op.drop_column("audit_findings", name)

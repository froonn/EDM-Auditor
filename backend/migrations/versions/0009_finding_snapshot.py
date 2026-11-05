"""Keep the rule and legal act of a finding in the report itself."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_finding_snapshot"
down_revision: str | Sequence[str] | None = "0008_llm_classification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = {
    "finding_key": sa.String(255),
    "rule_code": sa.String(100),
    "rule_name": sa.String(255),
    "legal_act_code": sa.String(100),
    "legal_act_title": sa.String(500),
    "norm_quote": sa.Text(),
}


def upgrade() -> None:
    bind = op.get_bind()
    # The first migration builds a new database from the current models.
    existing = {item["name"] for item in sa.inspect(bind).get_columns("audit_findings")}
    for name, column_type in COLUMNS.items():
        if name not in existing:
            op.add_column("audit_findings", sa.Column(name, column_type, nullable=True))
    # Earlier findings get what is still known: their rule or act may already be deleted.
    bind.exec_driver_sql(
        """
        UPDATE audit_findings SET
            rule_code = (SELECT rule.rule_code FROM audit_rules rule WHERE rule.id = rule_id),
            rule_name = (SELECT rule.name FROM audit_rules rule WHERE rule.id = rule_id),
            norm_quote = (SELECT rule.source_quote FROM audit_rules rule WHERE rule.id = rule_id),
            legal_act_code = (SELECT act.code FROM legal_acts act WHERE act.id = legal_act_id),
            legal_act_title = (SELECT act.title FROM legal_acts act WHERE act.id = legal_act_id)
        """
    )
    bind.exec_driver_sql(
        """
        UPDATE audit_findings
        SET finding_key = rule_code || ':' || COALESCE(start_char, '') || ':' || COALESCE(end_char, '')
        WHERE rule_code IS NOT NULL
        """
    )


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("audit_findings", name)

"""Allow numeric audit rules."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_numeric_rule_type"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("audit_rules")}
    if "check_type" not in columns:
        return
    with op.batch_alter_table("audit_rules", recreate="always") as batch:
        batch.drop_constraint("ck_rules_check_type", type_="check")
        batch.create_check_constraint(
            "ck_rules_check_type",
            "check_type IN ('keyword', 'regex', 'numeric', 'semantic')",
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_rules", recreate="always") as batch:
        batch.drop_constraint("ck_rules_check_type", type_="check")
        batch.create_check_constraint(
            "ck_rules_check_type",
            "check_type IN ('keyword', 'regex', 'semantic')",
        )

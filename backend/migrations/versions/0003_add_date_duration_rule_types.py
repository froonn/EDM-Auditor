"""Allow date and duration audit rules."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_date_duration_rule_types"
down_revision: str | Sequence[str] | None = "0002_numeric_rule_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("audit_rules", recreate="always") as batch:
        batch.drop_constraint("ck_rules_check_type", type_="check")
        batch.create_check_constraint(
            "ck_rules_check_type",
            "check_type IN ('keyword', 'regex', 'numeric', 'date', 'duration', 'semantic')",
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_rules", recreate="always") as batch:
        batch.drop_constraint("ck_rules_check_type", type_="check")
        batch.create_check_constraint(
            "ck_rules_check_type",
            "check_type IN ('keyword', 'regex', 'numeric', 'semantic')",
        )

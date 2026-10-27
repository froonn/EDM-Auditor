"""Create the initial storage schema."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from edm_auditor.database.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from edm_auditor.database.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

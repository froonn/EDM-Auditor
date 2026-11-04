from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from edm_auditor.database.models import Base

MIGRATIONS = Path(__file__).parents[2] / "migrations"


def _config(path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    return config


def test_full_chain_upgrades_an_empty_database_to_the_model_schema(tmp_path: Path) -> None:
    path = tmp_path / "fresh.sqlite3"

    command.upgrade(_config(path), "head")

    inspector = inspect(create_engine(f"sqlite:///{path}"))
    for table in Base.metadata.sorted_tables:
        assert inspector.has_table(table.name)
        columns = {item["name"] for item in inspector.get_columns(table.name)}
        assert columns == {column.name for column in table.columns}

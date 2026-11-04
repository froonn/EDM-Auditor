from pathlib import Path
import sqlite3

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


LEGACY_SCHEMA = """
CREATE TABLE documents (
    id INTEGER PRIMARY KEY, user_id INTEGER, title VARCHAR(255) NOT NULL,
    file_type VARCHAR(20) NOT NULL, file_path VARCHAR(1000) NOT NULL,
    raw_text TEXT NOT NULL, classified_type VARCHAR(100), status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL
);
CREATE TABLE legal_acts (id INTEGER PRIMARY KEY, code VARCHAR(100) NOT NULL);
CREATE TABLE audit_rules (
    id INTEGER PRIMARY KEY, rule_code VARCHAR(100) NOT NULL UNIQUE,
    document_type VARCHAR(100), is_generated BOOLEAN NOT NULL,
    legal_act_id INTEGER REFERENCES legal_acts (id) ON DELETE CASCADE
);
CREATE TABLE audit_findings (
    id INTEGER PRIMARY KEY,
    rule_id INTEGER REFERENCES audit_rules (id) ON DELETE SET NULL
);
INSERT INTO documents VALUES
    (1, NULL, 'Typed', 'txt', 'a.txt', '', 'contract', 'audited', '2026-01-01'),
    (2, NULL, 'Plain', 'txt', 'b.txt', '', NULL, 'uploaded', '2026-01-01');
INSERT INTO audit_rules VALUES
    (1, 'typed', 'contract', 0, NULL),
    (2, 'manual', NULL, 0, NULL),
    (3, 'generated', NULL, 1, NULL);
INSERT INTO audit_findings VALUES (1, 3);
"""


def test_upgrade_preserves_legacy_rule_scope_and_finding_links(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SCHEMA)
    command.stamp(_config(path), "0005_rule_publication_metadata")

    command.upgrade(_config(path), "head")

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT rule_code, applicability_scope FROM audit_rules ORDER BY id"
        ).fetchall() == [
            ("typed", "typed"),
            ("manual", "universal"),
            ("generated", "unknown"),
        ]
        assert connection.execute(
            "SELECT rule_id, document_type_code FROM rule_document_types"
        ).fetchall() == [(1, "contract")]
        assert connection.execute(
            "SELECT document_id, document_type_code FROM document_confirmed_types"
        ).fetchall() == [(1, "contract")]
        assert connection.execute(
            "SELECT classification_status, classification_source FROM documents ORDER BY id"
        ).fetchall() == [("classified", "legacy"), (None, None)]
        assert connection.execute("SELECT rule_id FROM audit_findings").fetchall() == [(3,)]
        columns = [row[1] for row in connection.execute("PRAGMA table_info(audit_rules)")]
        assert "document_type" not in columns

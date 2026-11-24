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
CREATE TABLE legal_acts (
    id INTEGER PRIMARY KEY, code VARCHAR(100) NOT NULL, title VARCHAR(500)
);
CREATE TABLE audit_rules (
    id INTEGER PRIMARY KEY, rule_code VARCHAR(100) NOT NULL UNIQUE, name VARCHAR(255),
    source_quote TEXT, document_type VARCHAR(100), is_generated BOOLEAN NOT NULL,
    legal_act_id INTEGER REFERENCES legal_acts (id) ON DELETE CASCADE
);
CREATE TABLE audit_findings (
    id INTEGER PRIMARY KEY,
    rule_id INTEGER REFERENCES audit_rules (id) ON DELETE SET NULL,
    legal_act_id INTEGER, start_char INTEGER, end_char INTEGER
);
INSERT INTO documents VALUES
    (1, NULL, 'Typed', 'txt', 'a.txt', '', 'contract', 'audited', '2026-01-01'),
    (2, NULL, 'Plain', 'txt', 'b.txt', '', NULL, 'uploaded', '2026-01-01');
INSERT INTO audit_rules VALUES
    (1, 'typed', 'Typed', NULL, 'contract', 0, NULL),
    (2, 'manual', 'Manual', NULL, NULL, 0, NULL),
    (3, 'generated', 'Generated', 'Norm', NULL, 1, NULL);
INSERT INTO legal_acts VALUES (1, 'ACT', 'Act');
INSERT INTO audit_findings VALUES (1, 3, 1, 5, 9), (2, 3, NULL, NULL, NULL), (3, NULL, NULL, 1, 2);
"""


def test_upgrade_preserves_legacy_rule_scope_and_finding_links(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SCHEMA)
    command.stamp(_config(path), "0005_rule_publication_metadata")

    command.upgrade(_config(path), "0009_finding_snapshot")

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
        assert connection.execute(
            "SELECT rule_id, finding_key, rule_name, norm_quote, legal_act_code, legal_act_title "
            "FROM audit_findings ORDER BY id"
        ).fetchall() == [
            (3, "generated:5:9", "Generated", "Norm", "ACT", "Act"),
            (3, "generated::", "Generated", "Norm", None, None),
            (None, None, None, None, None, None),
        ]
        columns = [row[1] for row in connection.execute("PRAGMA table_info(audit_rules)")]
        assert "document_type" not in columns

    command.upgrade(_config(path), "head")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_rules").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_findings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM legal_acts").fetchone()[0] == 1
        head_columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_rules)")}
        assert {"subject", "constraint_text", "constraint_json", "condition"} <= head_columns


def test_migration_0013_migrates_legacy_users_and_supports_downgrade(tmp_path: Path) -> None:
    path = tmp_path / "legacy_users.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                hashed_password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY, user_id INTEGER, title VARCHAR(255) NOT NULL,
                file_type VARCHAR(20) NOT NULL, file_path VARCHAR(1000) NOT NULL,
                raw_text TEXT NOT NULL, status VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE audit_reports (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
                total_findings INTEGER NOT NULL DEFAULT 0,
                critical_count INTEGER NOT NULL DEFAULT 0,
                high_count INTEGER NOT NULL DEFAULT 0,
                medium_count INTEGER NOT NULL DEFAULT 0,
                low_count INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL
            );
            INSERT INTO users VALUES
                (1, 'alice', 'alice@example.com', 'hash1', 'hr', '2026-01-01'),
                (2, 'bob', 'bob@example.com', 'hash2', 'auditor', '2026-01-01'),
                (3, 'carol', 'carol@example.com', 'hash3', 'admin', '2026-01-01');
            """
        )

    cfg = _config(path)
    command.stamp(cfg, "0012_stage4_finding_statement")
    command.upgrade(cfg, "head")

    with sqlite3.connect(path) as connection:
        user_cols = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        assert "role" not in user_cols
        assert {"full_name", "is_active", "is_super_admin", "must_change_password"} <= user_cols

        custom_groups = {
            row[0]
            for row in connection.execute("SELECT name FROM groups WHERE kind = 'custom'")
        }
        assert custom_groups == {"employee", "auditor", "lawyer", "admin"}

        memberships = connection.execute(
            """
            SELECT u.username, g.kind, g.name
            FROM user_groups ug
            JOIN users u ON u.id = ug.user_id
            JOIN groups g ON g.id = ug.group_id
            ORDER BY u.username, g.kind, g.name
            """
        ).fetchall()
        assert memberships == [
            ("alice", "custom", "employee"),
            ("alice", "personal", "alice"),
            ("bob", "custom", "auditor"),
            ("bob", "personal", "bob"),
            ("carol", "custom", "admin"),
            ("carol", "personal", "carol"),
        ]

    # Verify clean downgrade to 0012 and re-upgrade to head.
    command.downgrade(cfg, "0012_stage4_finding_statement")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "groups" not in tables
        assert "auth_audit_log" not in tables
        user_cols = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        assert "role" in user_cols

    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"groups", "group_permissions", "user_groups", "user_sessions", "audit_resolutions", "auth_audit_log"} <= tables

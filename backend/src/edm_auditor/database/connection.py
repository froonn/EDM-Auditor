"""SQLAlchemy engine and session setup."""

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def create_engine_for(url: str, *, echo: bool = False) -> Engine:
    """Create an engine and enable SQLite foreign keys on every connection."""
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, echo=echo, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


def create_session_factory(engine: Engine) -> Callable[[], Session]:
    """Return a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_sqlite_parent(path: Path) -> None:
    """Create the parent directory for a file-backed SQLite database."""
    path.parent.mkdir(parents=True, exist_ok=True)

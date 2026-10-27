"""Database configuration."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Settings used to build a SQLAlchemy database URL."""

    path: Path = Path("data/edm_auditor.sqlite3")

    @property
    def url(self) -> str:
        return f"sqlite:///{self.path}"

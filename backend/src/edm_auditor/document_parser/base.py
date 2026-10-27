"""Shared parser protocol."""

from pathlib import Path
from typing import Protocol

from .models import ParsedDocument


class DocumentParser(Protocol):
    def parse(
        self,
        source: Path,
        *,
        filename: str,
        media_type: str,
        size_bytes: int,
    ) -> ParsedDocument:
        """Parse a document from a temporary source path."""

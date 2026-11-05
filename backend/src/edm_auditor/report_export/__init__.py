"""Export of an audit report to a file (FR-4.4).

Each format is one renderer in `_RENDERERS`. The coursework produces HTML; PDF and an annotated DOCX
are planned for the diploma project (docs/DIPLOMA.md) and plug in here without API changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from .html import render_html
from .labels import RU

if TYPE_CHECKING:
    from edm_auditor.api.schemas import ReportResponse


class UnsupportedExportFormat(ValueError):
    """The requested export format has no renderer."""


@dataclass(frozen=True)
class ExportedDocument:
    title: str
    file_type: str
    text: str


@dataclass(frozen=True)
class ExportedFile:
    content: bytes
    media_type: str
    file_name: str

    @property
    def content_disposition(self) -> str:
        """An ASCII name for old clients and the real one in RFC 5987 form."""
        extension = self.file_name.rsplit(".", 1)[-1]
        return (
            f'attachment; filename="audit-report.{extension}"; '
            f"filename*=UTF-8''{quote(self.file_name, safe='')}"
        )


@dataclass(frozen=True)
class _Renderer:
    media_type: str
    extension: str
    render: Callable[..., str]


_RENDERERS = {
    "html": _Renderer("text/html; charset=utf-8", "html", render_html),
}

EXPORT_FORMATS = tuple(_RENDERERS)


def export_report(
    report: ReportResponse,
    document: ExportedDocument,
    export_format: str,
    timezone: tzinfo = UTC,
    exported_at: datetime | None = None,
) -> ExportedFile:
    renderer = _RENDERERS.get(export_format)
    if renderer is None:
        raise UnsupportedExportFormat(export_format)
    labels = RU
    content = renderer.render(
        report, document, labels, timezone, exported_at or datetime.now(UTC)
    )
    return ExportedFile(
        content=content.encode("utf-8"),
        media_type=renderer.media_type,
        file_name=_file_name(labels["file_name"], document.title, report, renderer.extension),
    )


def _file_name(prefix: str, title: str, report: ReportResponse, extension: str) -> str:
    """For example `Отчёт аудита — договор — №12.html`."""
    stem = title.rsplit(".", 1)[0] if "." in title else title
    # Characters that are not allowed in file names on Windows, and control characters.
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", stem).strip(" .") or "document"
    return f"{prefix} — {stem[:100]} — №{report.id}.{extension}"


__all__ = [
    "EXPORT_FORMATS",
    "ExportedDocument",
    "ExportedFile",
    "UnsupportedExportFormat",
    "export_report",
]

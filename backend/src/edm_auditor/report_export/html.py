"""A self-contained HTML report: one file with its styles, readable offline and printable.

The report follows the audit screen: the document text with highlighted findings, the findings with
their norms and recommendations, and the applied rules that found nothing. The browser can print it
or save it as PDF.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from html import escape
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from edm_auditor.api.schemas import FindingResponse, ReportResponse

    from . import ExportedDocument

SEVERITIES = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class _Finding:
    number: int
    finding: FindingResponse
    analysis: Mapping[str, Any] | None
    positioned: bool

    @property
    def recommendation(self) -> str | None:
        return _text((self.analysis or {}).get("recommendation")) or _text(
            self.finding.recommendation
        )


def render_html(
    report: ReportResponse,
    document: ExportedDocument,
    labels: Mapping[str, str],
    timezone: tzinfo,
    exported_at: datetime,
) -> str:
    """Render the report; every value from the database is escaped."""
    text = document.text or ""
    findings = _findings(report, len(text))
    label = _Labels(labels)
    title = f"{label('title')} — {document.title}"
    body = "\n".join(
        (
            f"<header><h1>{_e(label('title'))}</h1><p class=\"document\">{_e(document.title)}</p>"
            "</header>",
            _overview(report, document, findings, label, timezone, exported_at),
            _summary(report, label),
            f"<section><h2>{_e(label('document_text'))}</h2>"
            f"{_document_text(text, findings, label)}</section>",
            _findings_section(findings, label),
            _passed_section(report, label),
            _extras(report, label),
            f"<footer>{_e(label('disclaimer'))}</footer>",
        )
    )
    return (
        "<!DOCTYPE html>\n"
        f"<html lang=\"{_e(label('lang'))}\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<meta name=\"generator\" content=\"EDM-Auditor\">\n"
        f"<title>{_e(title)}</title>\n<style>{_STYLE}</style>\n</head>\n"
        f"<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


class _Labels:
    def __init__(self, labels: Mapping[str, str]) -> None:
        self._labels = labels

    def __call__(self, key: str) -> str:
        return self._labels.get(key, key)

    def optional(self, key: str, fallback: str) -> str:
        return self._labels.get(key, fallback)


# Findings ------------------------------------------------------------------------------------


def _findings(report: ReportResponse, text_length: int) -> list[_Finding]:
    """Findings in the order of the audit screen: by position, unpositioned ones last."""
    analyses = {
        item.finding_key: item.model_dump() for item in report.neural_analyses if item.finding_key
    }
    items = [
        (
            finding,
            analyses.get(finding.finding_key) if finding.finding_key else None,
            _has_position(finding, text_length),
        )
        for finding in report.findings
    ]
    items.sort(
        key=lambda item: (
            not item[2],
            item[0].start_char if item[2] else 0,
            _severity_rank(item[0].severity),
            item[0].id,
        )
    )
    return [
        _Finding(number=index, finding=finding, analysis=analysis, positioned=positioned)
        for index, (finding, analysis, positioned) in enumerate(items, start=1)
    ]


def _has_position(finding: FindingResponse, text_length: int) -> bool:
    start, end = finding.start_char, finding.end_char
    return (
        isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start < end <= text_length
    )


def _severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)


def _severity_class(severity: str) -> str:
    return f"sev-{severity}" if severity in SEVERITIES else "sev-unknown"


def _severity_badge(severity: str, label: _Labels) -> str:
    return (
        f"<span class=\"badge {_severity_class(severity)}\">"
        f"{_e(label.optional(f'severity.{severity}', severity))}</span>"
    )


# Overview ------------------------------------------------------------------------------------


def _overview(
    report: ReportResponse,
    document: ExportedDocument,
    findings: Sequence[_Finding],
    label: _Labels,
    timezone: tzinfo,
    exported_at: datetime,
) -> str:
    selection = report.selection if isinstance(report.selection, dict) else None
    rows = [
        (label("file_type"), _e(document.file_type.upper())),
        (label("report"), f"№ {report.id}"),
        (label("audited_at"), _e(_format_date(report.created_at, timezone))),
        (label("exported_at"), _e(_format_date(exported_at, timezone))),
        (label("timezone"), _e(str(timezone))),
    ]
    if selection is None:
        rows.append((label("selection_mode"), _e(label("no_selection"))))
    else:
        mode = _text(selection.get("selection_mode"))
        if mode:
            rows.append((label("selection_mode"), _e(label.optional(f"mode.{mode}", mode))))
        applied = selection.get("applied_rule_ids")
        rows.append((label("applied_rules"), str(len(applied) if isinstance(applied, list) else 0)))
        acts = [_act_name(act) for act in _objects(selection.get("applied_legal_acts"))]
        if any(acts):
            rows.append((label("applied_acts"), _e("; ".join(act for act in acts if act))))
    rows.append(
        (
            label("neural_status"),
            _e(label.optional(f"neural.{report.neural_status}", report.neural_status)),
        )
    )
    table = "".join(f"<tr><th>{_e(name)}</th><td>{value}</td></tr>" for name, value in rows)

    counts = {
        "critical": report.critical_count,
        "high": report.high_count,
        "medium": report.medium_count,
        "low": report.low_count,
    }
    tiles = "".join(
        # A zero stays grey, so the colored tiles are the ones that need attention.
        f"<div class=\"tile {_severity_class(severity) if counts[severity] else 'sev-unknown'}\">"
        f"<span>{counts[severity]}</span>"
        f"{_e(label(f'severity.{severity}'))}</div>"
        for severity in SEVERITIES
    )
    total = (
        f"<p class=\"total\">{_e(label('findings_total'))}: <strong>{len(findings)}</strong></p>"
        if findings
        else f"<p class=\"total ok\">{_e(label('no_findings'))}</p>"
    )
    return (
        f"<section class=\"overview\"><table class=\"facts\">{table}</table>"
        f"<div>{total}<div class=\"tiles\" aria-label=\"{_e(label('findings_by_severity'))}\">"
        f"{tiles}</div></div></section>"
    )


def _summary(report: ReportResponse, label: _Labels) -> str:
    neural = report.summary.get("neural") if isinstance(report.summary, dict) else None
    summary = _text(neural.get("general_summary")) if isinstance(neural, dict) else None
    if summary is None and report.neural_status == "not_requested":
        return ""
    content = (
        f"<p>{_e(summary)}</p>" if summary else f"<p class=\"muted\">{_e(label('no_summary'))}</p>"
    )
    return f"<section><h2>{_e(label('summary'))}</h2>{content}</section>"


# Document text -------------------------------------------------------------------------------


def _document_text(text: str, findings: Sequence[_Finding], label: _Labels) -> str:
    if not text:
        return f"<p class=\"muted\">{_e(label('no_text'))}</p>"
    shown, positions = _with_paragraph_breaks(text)
    spans = [
        (positions[item.finding.start_char], positions[item.finding.end_char], item)
        for item in findings
        if item.positioned
    ]
    boundaries = sorted({0, len(shown), *(start for start, _, _ in spans), *(end for _, end, _ in spans)})
    parts: list[str] = []
    for start, end in zip(boundaries, boundaries[1:]):
        for span_start, _, item in spans:
            if span_start == start:
                parts.append(
                    f"<a class=\"ref\" id=\"text-{item.number}\" href=\"#finding-{item.number}\""
                    f" title=\"{_e(label('to_finding'))} {item.number}\">{item.number}</a>"
                )
        covering = [item for span_start, span_end, item in spans if span_start <= start and end <= span_end]
        piece = _e(shown[start:end])
        if covering:
            strongest = min(covering, key=lambda item: _severity_rank(item.finding.severity))
            numbers = ", ".join(str(item.number) for item in covering)
            parts.append(
                f"<mark class=\"{_severity_class(strongest.finding.severity)}\""
                f" title=\"{_e(label('findings'))}: {numbers}\">{piece}</mark>"
            )
        else:
            parts.append(piece)
    return f"<div class=\"text\">{''.join(parts)}</div>"


def _with_paragraph_breaks(text: str) -> tuple[str, list[int]]:
    """Show each paragraph break ("\\n\\n" from the parser) as one line break.

    Returns the shown text and, for every offset of the stored text, the matching shown offset, so
    the highlights stay on the same characters. It matches `withParagraphBreaks` of the frontend.
    """
    shown: list[str] = []
    positions = [0] * (len(text) + 1)
    index = 0
    while index < len(text):
        positions[index] = len(shown)
        if text.startswith("\n\n", index):
            positions[index + 1] = len(shown) + 1
            shown.append("\n")
            index += 2
        else:
            shown.append(text[index])
            index += 1
    positions[len(text)] = len(shown)
    return "".join(shown), positions


# Finding cards -------------------------------------------------------------------------------


def _findings_section(findings: Sequence[_Finding], label: _Labels) -> str:
    if not findings:
        return ""
    cards = "".join(_finding_card(item, label) for item in findings)
    return f"<section><h2>{_e(label('findings'))}</h2>{cards}</section>"


def _finding_card(item: _Finding, label: _Labels) -> str:
    finding = item.finding
    position = (
        f"<a class=\"back\" href=\"#text-{item.number}\">↑ {_e(label('to_text'))}</a>"
        if item.positioned
        else f"<span class=\"muted\">{_e(label('unpositioned'))}</span>"
    )
    name = _text(finding.rule_name) or _text(finding.rule_code) or label("rule")
    code = (
        f" <code>{_e(finding.rule_code)}</code>"
        if finding.rule_code and finding.rule_code != name
        else ""
    )
    fields: list[tuple[str, str]] = [(label("description"), _paragraph(finding.description))]
    if _text(finding.quote):
        fields.append((label("quote"), f"<blockquote>«{_e(_one_line(finding.quote))}»</blockquote>"))
    if item.analysis:
        explanation = _text(item.analysis.get("explanation"))
        confidence = item.analysis.get("confidence")
        if explanation:
            suffix = (
                f" <span class=\"muted\">({_e(label('confidence'))} {_percent(confidence)})</span>"
                if isinstance(confidence, (int, float))
                else ""
            )
            fields.append((label("explanation"), f"<p>{_e(explanation)}{suffix}</p>"))
    act = _act_name({"title": finding.legal_act_title, "code": finding.legal_act_code})
    if act or _text(finding.norm_quote):
        norm = f"<p class=\"act\">{_e(act)}</p>" if act else ""
        if _text(finding.norm_quote):
            norm += f"<blockquote>{_e(_one_line(finding.norm_quote))}</blockquote>"
        fields.append((label("norm"), norm))
    if item.recommendation:
        fields.append((label("recommendation"), _paragraph(item.recommendation)))
    details = "".join(f"<dt>{_e(name)}</dt><dd>{value}</dd>" for name, value in fields)
    return (
        f"<article class=\"finding {_severity_class(finding.severity)}\" id=\"finding-{item.number}\">"
        f"<h3><span class=\"number\">{item.number}</span>{_severity_badge(finding.severity, label)}"
        f"<span class=\"name\">{_e(name)}</span>{code}</h3>"
        f"<p class=\"position\">{position}</p><dl>{details}</dl></article>"
    )


# Passed rules and extras ---------------------------------------------------------------------


def _passed_section(report: ReportResponse, label: _Labels) -> str:
    rules = passed_rules(report)
    heading = f"<h2>{_e(label('passed'))}</h2>"
    if rules is None:
        return f"<section>{heading}<p class=\"muted\">{_e(label('passed_unknown'))}</p></section>"
    if not rules:
        return f"<section>{heading}<p class=\"muted\">{_e(label('passed_empty'))}</p></section>"
    items = []
    for rule in rules:
        line = f"<span class=\"name\">{_e(rule['name'] or rule['rule_code'] or label('rule'))}</span>"
        if rule["rule_code"] and rule["rule_code"] != rule["name"]:
            line += f" <code>{_e(rule['rule_code'])}</code>"
        if rule["legal_act"]:
            line += f"<br><span class=\"muted\">{_e(label('legal_act'))}: {_e(rule['legal_act'])}</span>"
        for candidate in rule["rejected"]:
            line += (
                f"<p class=\"rejected\">{_e(label('passed_rejected'))}: "
                f"«{_e(candidate['quote'] or '')}»"
                + (f" — {_e(candidate['reason'])}" if candidate["reason"] else "")
                + "</p>"
            )
        items.append(f"<li>{line}</li>")
    return f"<section>{heading}<ul class=\"passed\">{''.join(items)}</ul></section>"


def passed_rules(report: ReportResponse) -> list[dict[str, Any]] | None:
    """Applied rules minus those with findings and those that could not be evaluated.

    Rules are matched by code too, because a rule may have been deleted after the audit. The same
    logic as `toPassedRules` of the frontend; `None` for reports saved before the selection was.
    """
    selection = report.selection if isinstance(report.selection, dict) else None
    if selection is None or not isinstance(selection.get("selection_reasons"), list):
        return None
    summary = report.summary if isinstance(report.summary, dict) else {}
    violated_ids = {item.rule_id for item in report.findings if item.rule_id is not None}
    violated_codes = {item.rule_code for item in report.findings if item.rule_code}
    failed_codes = {_text(item.get("rule_code")) for item in _objects(summary.get("diagnostics"))}
    rejected = _rejected(summary)
    acts = {
        act.get("id"): _act_name(act) for act in _objects(selection.get("applied_legal_acts"))
    }
    result = []
    for item in _objects(selection.get("selection_reasons")):
        if item.get("selected") is not True:
            continue
        rule_id = item.get("rule_id") if isinstance(item.get("rule_id"), int) else None
        code = _text(item.get("rule_code"))
        if rule_id is not None and rule_id in violated_ids:
            continue
        if code is not None and (code in violated_codes or code in failed_codes):
            continue
        result.append(
            {
                "rule_id": rule_id,
                "rule_code": code,
                "name": _text(item.get("name")),
                "legal_act": acts.get(item.get("legal_act_id")) or None,
                "rejected": [
                    candidate for candidate in rejected if code and candidate["rule_code"] == code
                ],
            }
        )
    return result


def _rejected(summary: Mapping[str, Any]) -> list[dict[str, str | None]]:
    return [
        {
            "rule_code": _text(item.get("rule_code")),
            "quote": _text(item.get("quote")),
            "reason": _text(item.get("reason")),
        }
        for item in _objects(summary.get("rejected_candidates"))
    ]


def _extras(report: ReportResponse, label: _Labels) -> str:
    summary = report.summary if isinstance(report.summary, dict) else {}
    parts = []
    rejected = _rejected(summary)
    if rejected:
        items = "".join(
            "<li>"
            + (f"«{_e(item['quote'])}»" if item["quote"] else "")
            + (f" — {_e(item['reason'])}" if item["reason"] else "")
            + (f" <code>{_e(item['rule_code'])}</code>" if item["rule_code"] else "")
            + "</li>"
            for item in rejected
        )
        parts.append(
            f"<section><h2>{_e(label('rejected'))} ({len(rejected)})</h2>"
            f"<p class=\"muted\">{_e(label('rejected_hint'))}</p><ul>{items}</ul></section>"
        )
    diagnostics = _objects(summary.get("diagnostics"))
    if diagnostics:
        items = "".join(
            f"<li><code>{_e(_text(item.get('rule_code')) or '')}</code> "
            f"{_e(_text(item.get('message')) or '')}</li>"
            for item in diagnostics
        )
        parts.append(
            f"<section><h2>{_e(label('diagnostics'))} ({len(diagnostics)})</h2>"
            f"<ul>{items}</ul></section>"
        )
    return "".join(parts)


# Helpers -------------------------------------------------------------------------------------


def _e(value: str) -> str:
    return escape(value, quote=True)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _objects(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _one_line(value: str) -> str:
    """A norm quote keeps the line wrapping of the act file, so it is shown as one line."""
    return re.sub(r"\s+", " ", value).strip()


def _paragraph(value: str | None) -> str:
    return f"<p class=\"multiline\">{_e((value or '').replace(chr(10) * 2, chr(10)))}</p>"


def _act_name(act: Mapping[str, Any]) -> str:
    title, code = _text(act.get("title")), _text(act.get("code"))
    return " ".join(part for part in (title, f"({code})" if code else None) if part)


def _percent(value: float) -> str:
    return f"{round(value * 100)} %"


def _format_date(value: datetime, timezone: tzinfo) -> str:
    """The API stores UTC without a zone, as the frontend's `parseApiDate` expects."""
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(timezone).strftime("%d.%m.%Y %H:%M")


_STYLE = """
:root { color-scheme: light; --fg: #131922; --muted: #5d646f; --line: #dde2e6; --soft: #eff2f5;
  --link: #154fac; --ok: #1d7d3e;
  --critical: #a9000c; --critical-bg: #ffb8b0; --critical-line: #d40924;
  --high: #be222a; --high-bg: #ffdcd7; --high-line: #ed756e;
  --medium: #875800; --medium-bg: #ffeea0; --medium-line: #e3ae28;
  --low: #195daa; --low-bg: #d6efff; --low-line: #61a3e6; }
* { box-sizing: border-box; }
body { margin: 0; background: #f9fafb; color: var(--fg); font: 15px/1.5 system-ui, -apple-system,
  "Segoe UI", Roboto, Arial, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 32px 24px 48px; }
header h1 { margin: 0; font-size: 26px; }
header .document { margin: 4px 0 0; color: var(--muted); font-size: 17px; }
h2 { margin: 32px 0 12px; font-size: 19px; border-bottom: 1px solid var(--line); padding-bottom: 4px; }
h3 { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; font-size: 16px; }
a { color: var(--link); }
code { font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--muted); }
.muted { color: var(--muted); }
.overview { display: grid; grid-template-columns: 3fr 2fr; gap: 24px; margin-top: 24px; }
.facts { border-collapse: collapse; width: 100%; background: #fff; border: 1px solid var(--line); }
.facts th, .facts td { text-align: left; vertical-align: top; padding: 6px 10px;
  border-bottom: 1px solid var(--line); }
.facts th { width: 40%; font-weight: 500; color: var(--muted); }
.total { margin: 0 0 8px; font-size: 17px; }
.total.ok { color: var(--ok); font-weight: 600; }
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.tile { border: 1px solid; border-radius: 8px; padding: 8px 12px; font-size: 13px; }
.tile span { display: block; font-size: 24px; font-weight: 700; line-height: 1.2; }
.text { white-space: pre-wrap; overflow-wrap: anywhere; background: #fff; border: 1px solid var(--line);
  border-radius: 8px; padding: 16px 20px; line-height: 1.6; }
mark { border-bottom: 2px solid; border-radius: 2px; color: inherit; }
.ref { display: inline-block; min-width: 1.4em; margin-right: 2px; padding: 0 4px; border-radius: 9px;
  background: var(--fg); color: #fff; font-size: 11px; line-height: 1.5; text-align: center;
  text-decoration: none; vertical-align: super; }
.finding { background: #fff; border: 1px solid var(--line); border-left: 4px solid;
  border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; break-inside: avoid; }
.finding .number { font-weight: 700; }
.finding .position { margin: 4px 0 8px; font-size: 13px; }
.finding dl { margin: 0; display: grid; grid-template-columns: 170px 1fr; gap: 6px 12px; }
.finding dt { color: var(--muted); }
.finding dd { margin: 0; }
.finding dd p, .finding dd blockquote { margin: 0; }
blockquote { border-left: 3px solid var(--line); padding-left: 10px; color: var(--fg); }
.act { font-weight: 500; }
.multiline { white-space: pre-wrap; }
.badge { display: inline-block; border: 1px solid; border-radius: 999px; padding: 0 8px;
  font-size: 12px; font-weight: 600; }
.passed { padding-left: 20px; }
.passed li { margin-bottom: 8px; }
.rejected { margin: 2px 0 0; font-size: 13px; color: var(--muted); }
footer { margin-top: 40px; padding-top: 12px; border-top: 1px solid var(--line); color: var(--muted);
  font-size: 13px; }
.sev-critical { --tone: var(--critical); --tone-bg: var(--critical-bg); --tone-line: var(--critical-line); }
.sev-high { --tone: var(--high); --tone-bg: var(--high-bg); --tone-line: var(--high-line); }
.sev-medium { --tone: var(--medium); --tone-bg: var(--medium-bg); --tone-line: var(--medium-line); }
.sev-low { --tone: var(--low); --tone-bg: var(--low-bg); --tone-line: var(--low-line); }
.sev-unknown { --tone: var(--muted); --tone-bg: var(--soft); --tone-line: var(--line); }
mark, .badge, .tile { background: var(--tone-bg); border-color: var(--tone-line); }
.badge, .tile span { color: var(--tone); }
.finding { border-left-color: var(--tone-line); }
@media print {
  body { background: #fff; font-size: 12px; }
  main { max-width: none; padding: 0; }
  .text, .facts, .finding { border-color: #bbb; }
  .back { display: none; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""

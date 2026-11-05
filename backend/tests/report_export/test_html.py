from datetime import UTC, datetime
import re
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest

from edm_auditor.api.schemas import FindingResponse, NeuralAnalysisResponse, ReportResponse
from edm_auditor.report_export import (
    ExportedDocument,
    UnsupportedExportFormat,
    export_report,
)
from edm_auditor.report_export.html import _with_paragraph_breaks, passed_rules

TEXT = "Договор.\n\nАванс 35 рублей.\n\nСрок 5 дней."


def finding(**values) -> FindingResponse:
    defaults = {
        "id": 1,
        "rule_id": 1,
        "legal_act_id": 1,
        "severity": "high",
        "description": "Требование",
        "start_char": None,
        "end_char": None,
        "quote": None,
        "recommendation": None,
    }
    return FindingResponse(**{**defaults, **values})


def report(findings: list[FindingResponse], **values) -> ReportResponse:
    defaults = {
        "id": 7,
        "document_id": 3,
        "total_findings": len(findings),
        "critical_count": 0,
        "high_count": len(findings),
        "medium_count": 0,
        "low_count": 0,
        "summary": {},
        "created_at": datetime(2026, 11, 5, 9, 1),
        "findings": findings,
    }
    return ReportResponse(**{**defaults, **values})


def render(value: ReportResponse, text: str = TEXT, title: str = "договор.txt") -> str:
    exported = export_report(
        value,
        ExportedDocument(title=title, file_type="txt", text=text),
        "html",
        ZoneInfo("Europe/Minsk"),
        exported_at=datetime(2026, 11, 6, 10, 0, tzinfo=UTC),
    )
    return exported.content.decode("utf-8")


def test_paragraph_breaks_keep_offsets() -> None:
    shown, positions = _with_paragraph_breaks("a\n\nb\n\n\nc")

    assert shown == "a\nb\n\nc"
    assert positions[3] == 2  # "b"
    assert shown[positions[7]] == "c"
    assert positions[len("a\n\nb\n\n\nc")] == len(shown)


def test_highlight_marks_the_finding_text_after_paragraph_breaks() -> None:
    start = TEXT.index("35 рублей")
    html = render(report([finding(start_char=start, end_char=start + len("35 рублей"))]))

    assert '<a class="ref" id="text-1" href="#finding-1"' in html
    assert re.search(r'<mark class="sev-high"[^>]*>35 рублей</mark>', html)
    assert 'id="finding-1"' in html and 'href="#text-1"' in html
    assert "Договор.\nАванс " in html


def test_overlapping_findings_use_the_strongest_severity() -> None:
    html = render(
        report(
            [
                finding(id=1, severity="low", start_char=10, end_char=20),
                finding(id=2, severity="critical", start_char=15, end_char=25),
            ]
        )
    )

    assert re.search(r'<mark class="sev-low" title="[^"]*: 1">', html)
    assert re.search(r'<mark class="sev-critical" title="[^"]*: 1, 2">', html)
    assert re.search(r'<mark class="sev-critical" title="[^"]*: 2">', html)


def test_findings_without_valid_position_go_last_and_are_not_highlighted() -> None:
    html = render(
        report(
            [
                finding(id=1, start_char=None, end_char=None, rule_name="Без позиции"),
                finding(id=2, start_char=5, end_char=500, rule_name="Вне текста"),
                finding(id=3, start_char=0, end_char=7, rule_name="В тексте"),
            ]
        )
    )

    assert html.count("<mark") == 1
    assert html.index("В тексте") < html.index("Без позиции")
    assert html.count("без привязки к тексту") == 2


def test_database_values_are_escaped() -> None:
    html = render(
        report([finding(description="<script>alert(1)</script>", rule_name='"><img>')]),
        text="<b>текст</b>",
        title="<i>договор</i>.txt",
    )

    assert "<script>" not in html
    assert "<img>" not in html
    assert "<b>текст</b>" not in html
    assert "&lt;script&gt;" in html


def test_model_analysis_norm_and_recommendation_are_shown() -> None:
    html = render(
        report(
            [
                finding(
                    finding_key="k1",
                    recommendation="Из правила",
                    legal_act_code="ACT",
                    legal_act_title="Положение",
                    norm_quote="Не менее\n50 рублей.",
                )
            ],
            neural_status="completed",
            neural_analyses=[
                NeuralAnalysisResponse(
                    finding_key="k1",
                    explanation="Сумма ниже нормы",
                    recommendation="От модели",
                    confidence=0.9,
                    legal_basis=[],
                )
            ],
            summary={"neural": {"general_summary": "Общий вывод", "status": "completed"}},
        )
    )

    assert "Сумма ниже нормы" in html and "90 %" in html
    assert "От модели" in html and "Из правила" not in html
    assert "Положение (ACT)" in html
    assert "Не менее 50 рублей." in html
    assert "Общий вывод" in html


def test_dates_use_the_requested_time_zone() -> None:
    html = render(report([]))

    assert "05.11.2026 12:01" in html
    assert "06.11.2026 13:00" in html
    assert "Нарушений не найдено." in html


def test_passed_rules_exclude_violated_and_failed_rules() -> None:
    selection = {
        "selection_mode": "automatic",
        "applied_rule_ids": [1, 2, 3, 4],
        "applied_legal_acts": [{"id": 1, "code": "ACT", "title": "Положение"}],
        "selection_reasons": [
            {"rule_id": 1, "rule_code": "R1", "name": "Нарушено", "selected": True},
            {"rule_id": 2, "rule_code": "R2", "name": "Ошибка", "selected": True},
            {
                "rule_id": 3,
                "rule_code": "R3",
                "name": "Соблюдено",
                "legal_act_id": 1,
                "selected": True,
            },
            {"rule_id": 4, "rule_code": "R4", "name": "Не выбрано", "selected": False},
            {"rule_id": None, "rule_code": "R5", "name": "Удалено", "selected": True},
        ],
    }
    summary = {
        "diagnostics": [{"rule_code": "R2", "message": "сбой"}],
        "rejected_candidates": [{"rule_code": "R3", "quote": "50", "reason": "норма"}],
    }
    value = report(
        [finding(rule_id=1, rule_code="R1")], selection=selection, summary=summary
    )

    rules = passed_rules(value)

    assert [rule["rule_code"] for rule in rules] == ["R3", "R5"]
    assert rules[0]["legal_act"] == "Положение (ACT)"
    assert rules[0]["rejected"] == [{"rule_code": "R3", "quote": "50", "reason": "норма"}]
    html = render(value)
    assert "Соблюдено" in html and "Правила, которые не удалось проверить (1)" in html


def test_reports_without_selection_say_that_passed_rules_are_unknown() -> None:
    assert passed_rules(report([])) is None
    assert "список правил без нарушений недоступен" in render(report([]))


def test_file_name_and_disposition() -> None:
    exported = export_report(
        report([]), ExportedDocument(title='a/b:"c".docx', file_type="docx", text=""), "html"
    )

    assert exported.media_type.startswith("text/html")
    assert exported.file_name == "Отчёт аудита — a b c — №7.html"
    assert 'filename="audit-report.html"' in exported.content_disposition
    encoded = exported.content_disposition.split("filename*=UTF-8''")[1]
    assert unquote(encoded) == exported.file_name


def test_unknown_format_is_rejected() -> None:
    with pytest.raises(UnsupportedExportFormat):
        export_report(report([]), ExportedDocument(title="d", file_type="txt", text=""), "pdf")

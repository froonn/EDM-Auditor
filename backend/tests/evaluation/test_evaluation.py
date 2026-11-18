from pathlib import Path

import pytest

from edm_auditor.evaluation import CorpusError, load_corpus, score_run
from edm_auditor.evaluation.__main__ import DEFAULT_CORPUS
from edm_auditor.evaluation.corpus import find_quote
from edm_auditor.evaluation.scoring import render_markdown

ACT = """Положение.
1. Компенсация не может быть
меньше 50 рублей.
2. В соглашении указывается режим работы.
3. Контроль осуществляет бухгалтер.
"""
DOCUMENT = "Соглашение.\nКомпенсация составляет 35 рублей.\nДоставка стоит 20 рублей.\n"
LABELS = """
[[acts]]
id = "act"
file = "act.txt"
code = "EVAL-ACT"
title = "Положение"
norms = [
  { id = "money", quote = "Компенсация не может быть меньше 50 рублей", kind = "value" },
  { id = "schedule", quote = "указывается режим работы", kind = "text" },
  { id = "control", quote = "Контроль осуществляет бухгалтер", kind = "text", checkable = false },
]

[[documents]]
id = "doc"
file = "doc.txt"
acts = ["act"]
violations = [{ norm = "money", quote = "35 рублей" }, { norm = "schedule" }]
"""


def write_corpus(root: Path, labels: str = LABELS) -> None:
    (root / "act.txt").write_text(ACT, encoding="utf-8")
    (root / "doc.txt").write_text(DOCUMENT, encoding="utf-8")
    (root / "labels.toml").write_text(labels, encoding="utf-8")


def span(text: str, quote: str) -> tuple[int, int]:
    start = text.index(quote)
    return start, start + len(quote)


def rule(rule_id: int, quote: str) -> dict:
    start, end = find_quote(ACT, quote)[0]
    return {"id": rule_id, "name": quote, "source_quote": quote,
            "source_start": start, "source_end": end}


def finding(rule_id: int, quote: str | None) -> dict:
    start, end = span(DOCUMENT, quote) if quote else (None, None)
    return {"rule_id": rule_id, "rule_code": f"R{rule_id}", "quote": quote,
            "start_char": start, "end_char": end}


def test_repository_corpus_labels_are_valid() -> None:
    corpus = load_corpus(DEFAULT_CORPUS)

    assert len(corpus.acts) >= 3
    assert sum(len(item.violations) for item in corpus.documents) > 0


def test_quote_matches_across_line_breaks() -> None:
    assert find_quote(ACT, "может быть меньше 50 рублей") == [span(ACT, "может быть\nменьше 50 рублей")]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("меньше 50 рублей", "меньше 60 рублей", "not found"),
        ('quote = "35 рублей"', 'quote = "рублей"', "found 2 times"),
        ('norm = "schedule"', 'norm = "unknown"', "not in its acts"),
    ],
)
def test_wrong_labels_are_rejected(tmp_path: Path, old: str, new: str, message: str) -> None:
    write_corpus(tmp_path, LABELS.replace(old, new, 1))

    with pytest.raises(CorpusError, match=message):
        load_corpus(tmp_path)


def test_score_classifies_findings_and_misses(tmp_path: Path) -> None:
    write_corpus(tmp_path)
    corpus = load_corpus(tmp_path)
    run = {
        "acts": {"act": {"status": "ok", "text": ACT, "rules": [
            rule(1, "Компенсация не может быть\nменьше 50 рублей."),
            rule(2, "Контроль осуществляет бухгалтер."),
            rule(3, "Положение."),
        ]}},
        "documents": {"doc": {"status": "ok", "text": DOCUMENT, "findings": [
            finding(1, "35 рублей"),
            finding(1, "35 рублей"),
            finding(1, "20 рублей"),
            finding(3, "Соглашение."),
        ]}},
    }

    metrics = score_run(corpus, run)

    extraction = metrics["extraction"]
    assert (extraction["covered"], extraction["checkable_norms"]) == (1, 2)
    assert extraction["acts"][0]["missed"] == ["schedule"]
    assert extraction["not_checkable_with_rules"] == 1
    assert extraction["extra_rules"] == 1
    audit = metrics["audit"]
    assert (audit["true"], audit["false"], audit["missed"], audit["duplicates"]) == (1, 2, 1, 1)
    assert audit["false_reasons"] == {"wrong_place": 1, "rule_without_norm": 1}
    assert audit["miss_reasons"] == {"no_rule": 1}
    assert audit["recall_by_kind"] == {"text": 0.0, "value": 1.0}
    assert "| doc | ok | 1/2 |" in render_markdown(metrics, {"label": "test"})


def test_failed_audit_counts_every_violation_as_missed(tmp_path: Path) -> None:
    write_corpus(tmp_path)
    corpus = load_corpus(tmp_path)
    run = {
        "acts": {"act": {"status": "ok", "text": ACT, "rules": []}},
        "documents": {"doc": {"status": "error", "error": "HTTP 503", "findings": []}},
    }

    audit = score_run(corpus, run)["audit"]

    assert audit["miss_reasons"] == {"audit_failed": 2}
    assert audit["precision"] is None


def test_runner_records_rules_findings_and_requests(tmp_path: Path, monkeypatch) -> None:
    from fakes import patch_fake_providers
    from edm_auditor.api.config import ApiSettings
    from edm_auditor.evaluation.runner import run_corpus

    class RuleExtractor:
        model_name = "fake-extractor"

        def extract_rules(self, text, *, source_language, source_location, **_):
            return ({
                "subject": "Компенсация",
                "constraint_text": "Компенсация не меньше 50 рублей.",
                "constraint_json": {"kind": "value", "operator": "gte", "value": 50, "unit": "byn"},
                "condition": "",
                "severity": "high",
                "source_quote": "Компенсация не может быть\nменьше 50 рублей.",
                "applicability_scope": "universal",
                "document_types": [],
                "applicability_confidence": 0.9,
                "suggested_type_name": "",
                "suggested_type_reason": "",
            },)

    patch_fake_providers(monkeypatch, create_rule_extraction_provider=RuleExtractor)
    write_corpus(tmp_path)
    corpus = load_corpus(tmp_path)

    run = run_corpus(
        corpus, label="test", min_interval=0, base_settings=ApiSettings(),
        log_file=tmp_path / "debug.log",
    )

    assert run["acts"]["act"]["status"] == "ok"
    assert len(run["acts"]["act"]["rules"]) == 1
    assert run["documents"]["doc"]["status"] == "ok"
    assert run["requests"]["by_kind"]["rules"] == 1
    assert run["requests"]["by_kind"]["llm"] >= 1
    audit = score_run(corpus, run)["audit"]
    assert audit["true"] == 1
    assert audit["false"] == 0
    assert audit["false_reasons"] == {}

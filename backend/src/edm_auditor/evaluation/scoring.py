"""Compare a recorded run with the corpus labels.

Scoring works on plain data saved by the runner, so a saved run can be scored again after the labels
or the scoring change, without calling the model.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .corpus import Corpus, find_quote, locate_quote

Span = tuple[int, int]


def _overlaps(first: Span, second: Span) -> bool:
    return first[0] < second[1] and second[0] < first[1]


def _rule_span(rule: dict[str, Any], act_text: str) -> Span | None:
    start, end = rule.get("source_start"), rule.get("source_end")
    if start is not None and end is not None:
        return int(start), int(end)
    quote = rule.get("source_quote")
    if quote:
        matches = find_quote(act_text, quote)
        if matches:
            return matches[0]
    return None


def _finding_span(finding: dict[str, Any]) -> Span | None:
    start, end = finding.get("start_char"), finding.get("end_char")
    if start is None or end is None:
        return None
    return int(start), int(end)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def score_run(corpus: Corpus, run: dict[str, Any]) -> dict[str, Any]:
    """Return extraction and audit metrics with the reason for every miss and false finding."""
    rule_norms: dict[int, list[str]] = {}
    extraction_acts = []
    for act in corpus.acts:
        recorded = run["acts"].get(act.id, {})
        text = recorded.get("text") or act.text()
        norm_spans = {
            norm.id: locate_quote(text, norm.quote, where=f"norm {norm.id}")
            for norm in act.norms
        }
        rules_by_norm: dict[str, list[int]] = {norm.id: [] for norm in act.norms}
        extra_rules = []
        for rule in recorded.get("rules", []):
            span = _rule_span(rule, text)
            norms = [
                norm_id for norm_id, norm_span in norm_spans.items()
                if span is not None and _overlaps(span, norm_span)
            ]
            rule_norms[rule["id"]] = norms
            for norm_id in norms:
                rules_by_norm[norm_id].append(rule["id"])
            if not norms:
                extra_rules.append(rule.get("source_quote") or rule.get("name"))
        checkable = [norm for norm in act.norms if norm.checkable]
        covered = [norm.id for norm in checkable if rules_by_norm[norm.id]]
        extraction_acts.append({
            "act": act.id,
            "status": recorded.get("status", "missing"),
            "error": recorded.get("error"),
            "rules": len(recorded.get("rules", [])),
            "checkable_norms": len(checkable),
            "covered": len(covered),
            "missed": [norm.id for norm in checkable if not rules_by_norm[norm.id]],
            "not_checkable_with_rules": [
                norm.id for norm in act.norms
                if not norm.checkable and rules_by_norm[norm.id]
            ],
            "extra_rules": extra_rules,
            "duplicated_norms": [
                norm.id for norm in checkable if len(rules_by_norm[norm.id]) > 1
            ],
        })
    rules_cover = {norm_id for norms in rule_norms.values() for norm_id in norms}

    audit_documents = []
    totals: Counter[str] = Counter()
    kind_totals: dict[str, Counter[str]] = {}
    false_reasons: Counter[str] = Counter()
    miss_reasons: Counter[str] = Counter()
    for document in corpus.documents:
        recorded = run["documents"].get(document.id, {})
        text = recorded.get("text") or document.text()
        expected = [
            {
                "norm": violation.norm,
                "span": (
                    locate_quote(text, violation.quote, where=f"document {document.id}")
                    if violation.quote is not None else None
                ),
                "matched": False,
            }
            for violation in document.violations
        ]
        applicable = {
            norm.id
            for act_id in document.acts
            for norm in corpus.act(act_id).norms
            if norm.checkable
        }
        true_findings, false_findings, duplicates = [], [], []
        false_spans: list[dict[str, Any]] = []
        failed = recorded.get("status") != "ok"
        for finding in [] if failed else recorded.get("findings", []):
            norms = rule_norms.get(finding.get("rule_id"), [])
            span = _finding_span(finding)
            label = {
                "rule_code": finding.get("rule_code"),
                "quote": finding.get("quote"),
                "norms": norms,
            }
            compatible = [
                item for item in expected
                if item["norm"] in norms
                and (item["span"] is None or span is None or _overlaps(item["span"], span))
            ]
            fresh = [item for item in compatible if not item["matched"]]
            repeated_false = any(
                earlier["rule_id"] == finding.get("rule_id")
                and (earlier["span"] is None or span is None or _overlaps(earlier["span"], span))
                for earlier in false_spans
            )
            if fresh:
                fresh[0]["matched"] = True
                true_findings.append({**label, "norm": fresh[0]["norm"]})
            elif compatible or repeated_false:
                duplicates.append(label)
            else:
                false_spans.append({"rule_id": finding.get("rule_id"), "span": span})
                if not norms:
                    reason = "rule_without_norm"
                elif any(item["norm"] in norms for item in expected):
                    reason = "wrong_place"
                else:
                    reason = "norm_is_met"
                false_findings.append({**label, "reason": reason})
                false_reasons[reason] += 1
        missed = []
        for item in expected:
            if item["matched"]:
                continue
            if failed:
                reason = "audit_failed"
            elif item["norm"] not in rules_cover:
                reason = "no_rule"
            else:
                reason = "not_detected"
            missed.append({"norm": item["norm"], "reason": reason})
            miss_reasons[reason] += 1
        for item in expected:
            kind = corpus.norm(item["norm"]).kind
            counter = kind_totals.setdefault(kind, Counter())
            counter["tp" if item["matched"] else "fn"] += 1
        totals.update(
            tp=len(true_findings), fp=len(false_findings), fn=len(missed),
            duplicates=len(duplicates),
        )
        audit_documents.append({
            "document": document.id,
            "status": recorded.get("status", "missing"),
            "error": recorded.get("error"),
            "expected": len(expected),
            "applicable_norms": len(applicable),
            "true": true_findings,
            "false": false_findings,
            "missed": missed,
            "duplicates": duplicates,
        })

    covered_total = sum(item["covered"] for item in extraction_acts)
    checkable_total = sum(item["checkable_norms"] for item in extraction_acts)
    tp, fp, fn = totals["tp"], totals["fp"], totals["fn"]
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return {
        "extraction": {
            "norm_recall": _ratio(covered_total, checkable_total),
            "covered": covered_total,
            "checkable_norms": checkable_total,
            "extra_rules": sum(len(item["extra_rules"]) for item in extraction_acts),
            "not_checkable_with_rules": sum(
                len(item["not_checkable_with_rules"]) for item in extraction_acts
            ),
            "acts": extraction_acts,
        },
        "audit": {
            "precision": precision,
            "recall": recall,
            "f1": (
                round(2 * precision * recall / (precision + recall), 3)
                if precision and recall else None
            ),
            "true": tp,
            "false": fp,
            "missed": fn,
            "duplicates": totals["duplicates"],
            "false_reasons": dict(false_reasons),
            "miss_reasons": dict(miss_reasons),
            "recall_by_kind": {
                kind: _ratio(counter["tp"], counter["tp"] + counter["fn"])
                for kind, counter in sorted(kind_totals.items())
            },
            "clean_documents_without_false": sum(
                1 for item in audit_documents
                if item["expected"] == 0 and item["status"] == "ok" and not item["false"]
            ),
            "clean_documents": sum(1 for item in audit_documents if item["expected"] == 0),
            "documents": audit_documents,
        },
    }


def render_markdown(metrics: dict[str, Any], run: dict[str, Any]) -> str:
    """A short report for the console and the results folder."""
    extraction, audit = metrics["extraction"], metrics["audit"]
    lines = [
        f"# Оценка: {run.get('label', '')}",
        "",
        f"- Запуск: {run.get('started_at', '')}, пресет `{run.get('preset', '')}`, "
        f"длительность {run.get('duration_seconds', 0):.0f} с",
        f"- Модели: {_format_counts(run.get('models', {}))}",
        f"- Запросы к модели: {run.get('requests', {}).get('total', 0)} "
        f"({_format_counts(run.get('requests', {}).get('by_kind', {}))}), "
        f"повторов аудита после перегрузки модели: "
        f"{run.get('requests', {}).get('audit_retries', 0)}",
        "",
        "## Извлечение правил",
        "",
        f"- Покрыто норм: {extraction['covered']} из {extraction['checkable_norms']} "
        f"(полнота {extraction['norm_recall']})",
        f"- Лишних правил: {extraction['extra_rules']}, правил для не проверяемых норм: "
        f"{extraction['not_checkable_with_rules']}",
        "",
        "| НПА | Статус | Правил | Покрыто | Пропущены | Дубли |",
        "|-----|--------|--------|---------|-----------|-------|",
    ]
    for item in extraction["acts"]:
        lines.append(
            f"| {item['act']} | {item['status']} | {item['rules']} | "
            f"{item['covered']}/{item['checkable_norms']} | "
            f"{', '.join(item['missed']) or '—'} | {', '.join(item['duplicated_norms']) or '—'} |"
        )
    lines += [
        "",
        "## Аудит",
        "",
        f"- Точность {audit['precision']}, полнота {audit['recall']}, F1 {audit['f1']}",
        f"- Верных {audit['true']}, ложных {audit['false']}, пропущено {audit['missed']}, "
        f"повторов {audit['duplicates']}",
        f"- Ложные: {_format_counts(audit['false_reasons'])}",
        f"- Пропуски: {_format_counts(audit['miss_reasons'])}",
        f"- Полнота по видам норм: {_format_counts(audit['recall_by_kind'])}",
        f"- Документы без нарушений и без ложных находок: "
        f"{audit['clean_documents_without_false']} из {audit['clean_documents']}",
        "",
        "| Документ | Статус | Верные | Ложные | Пропущены |",
        "|----------|--------|--------|--------|-----------|",
    ]
    for item in audit["documents"]:
        false = ", ".join(
            f"{_cell(finding['quote'] or finding['rule_code'] or '—')} ({finding['reason']})"
            for finding in item["false"]
        )
        missed = ", ".join(f"{miss['norm']} ({miss['reason']})" for miss in item["missed"])
        lines.append(
            f"| {item['document']} | {item['status']} | {len(item['true'])}/{item['expected']} | "
            f"{false or '—'} | {missed or '—'} |"
        )
    return "\n".join(lines) + "\n"


def _cell(value: str) -> str:
    """Keep a quote on one table line."""
    return " ".join(value.split()).replace("|", "\\|")


def _format_counts(counts: dict[str, Any]) -> str:
    return ", ".join(f"{key} {value}" for key, value in counts.items()) or "—"

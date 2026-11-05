import pytest

from edm_auditor.classification import (
    ClassificationStatus,
    DocumentClassifier,
    classification_sample,
)
from edm_auditor.model_providers import DocumentTypeOption

CATALOG = (
    DocumentTypeOption("business_trip_order", "Приказ о командировке", "Командировка."),
    DocumentTypeOption("payroll_order", "Приказ об оплате труда", "Заработная плата."),
)


class Provider:
    model_name = "fake"

    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    def classify(self, text, *, title, filename, document_types):
        self.calls.append({"text": text, "title": title, "filename": filename})
        return self.answer


def _classify(answer: object, **options):
    return DocumentClassifier(Provider(answer), **options).classify(
        "Текст документа.", document_types=CATALOG
    )


def _answer(*types: tuple[str, float], name: str = "", reason: str = "") -> dict:
    return {
        "document_types": [{"code": code, "confidence": value} for code, value in types],
        "suggested_type_name": name,
        "suggested_type_reason": reason,
    }


def test_confident_answer_confirms_the_type() -> None:
    outcome = _classify(_answer(("business_trip_order", 0.9)))

    assert outcome.result.status is ClassificationStatus.CLASSIFIED
    assert outcome.result.confirmed_document_types == ("business_trip_order",)
    assert outcome.result.confidence == 0.9


def test_document_can_get_several_types() -> None:
    outcome = _classify(_answer(("payroll_order", 0.8), ("business_trip_order", 0.9)))

    assert outcome.result.confirmed_document_types == ("business_trip_order", "payroll_order")


def test_doubtful_answer_needs_review_and_confirms_nothing() -> None:
    outcome = _classify(_answer(("business_trip_order", 0.5)))

    assert outcome.result.status is ClassificationStatus.NEEDS_REVIEW
    assert outcome.result.confirmed_document_types == ()
    assert outcome.result.candidate_types[0].code == "business_trip_order"


def test_threshold_is_configurable() -> None:
    outcome = _classify(_answer(("business_trip_order", 0.5)), min_confidence=0.4)

    assert outcome.result.status is ClassificationStatus.CLASSIFIED


def test_code_outside_the_catalog_is_ignored() -> None:
    outcome = _classify(_answer(("invented_type", 1.0)))

    assert outcome.result.status is ClassificationStatus.UNKNOWN
    assert outcome.result.candidate_types == ()


def test_no_matching_type_keeps_the_suggestion() -> None:
    outcome = _classify(_answer(name=" Докладная записка ", reason="Нет в каталоге."))

    assert outcome.result.status is ClassificationStatus.UNKNOWN
    assert outcome.suggestion.name == "Докладная записка"
    assert outcome.suggestion.reason == "Нет в каталоге."


def test_suggestion_is_ignored_when_a_type_is_confirmed() -> None:
    outcome = _classify(_answer(("payroll_order", 0.9), name="Другой тип"))

    assert outcome.suggestion is None


@pytest.mark.parametrize(
    "answer",
    [
        "не объект",
        {},
        {"document_types": "payroll_order"},
        {"document_types": ["payroll_order"]},
        {"document_types": [{"code": "payroll_order", "confidence": "высокая"}]},
        {"document_types": [{"code": "payroll_order", "confidence": True}]},
        {"document_types": [{"code": "payroll_order", "confidence": 1.5}]},
    ],
)
def test_malformed_answer_is_an_error(answer: object) -> None:
    with pytest.raises(ValueError):
        _classify(answer)


def test_empty_catalog_does_not_call_the_model() -> None:
    provider = Provider(_answer())

    outcome = DocumentClassifier(provider).classify("Текст.", document_types=())

    assert outcome.result.status is ClassificationStatus.UNKNOWN
    assert provider.calls == []


def test_model_receives_only_the_start_and_end_of_a_long_document() -> None:
    provider = Provider(_answer())
    text = "Н" * 100 + "С" * 10_000 + "К" * 50

    DocumentClassifier(provider, head_chars=100, tail_chars=50).classify(
        text, title="Заголовок", filename="doc.txt", document_types=CATALOG
    )

    sent = provider.calls[0]
    assert sent["text"] == "Н" * 100 + "\n[...]\n" + "К" * 50
    assert sent["title"] == "Заголовок"
    assert sent["filename"] == "doc.txt"


def test_short_document_is_sent_whole() -> None:
    assert classification_sample("Короткий", head_chars=5, tail_chars=5) == "Короткий"


def test_sample_without_a_tail_keeps_only_the_start() -> None:
    assert classification_sample("Длинный", head_chars=3, tail_chars=0) == "Дли\n[...]\n"

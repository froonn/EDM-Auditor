import re
from pathlib import Path

import pytest

from edm_auditor.legal_structure import chunk_legal_act, parse_legal_act

CORPUS = Path(__file__).resolve().parents[1] / "evaluation" / "corpus" / "acts"
ACT = """Положение об оплате труда

Глава 1. Общие положения

1. Настоящее Положение определяет порядок выплаты заработной платы
работникам организации.

Глава 2. Сроки выплаты

2. Расчет производится не позднее чем за
15 календарных дней.
3. В приказе указываются:
1) период, за который производится выплата;
2) способ выплаты.
3.1. Способ выплаты выбирает работник.
"""


def body(text: str, block) -> str:
    return " ".join(text[block.start:block.end].split())


def test_wrapped_lines_join_and_units_get_paths() -> None:
    structure = parse_legal_act(ACT)

    found = {body(ACT, block): ", ".join(block.path) for block in structure.blocks}

    assert found["1. Настоящее Положение определяет порядок выплаты заработной платы работникам организации."] == "гл. 1, п. 1"
    # «15 календарных дней» continues the sentence instead of starting point 15.
    assert found["2. Расчет производится не позднее чем за 15 календарных дней."] == "гл. 2, п. 2"
    assert found["2) способ выплаты."] == "гл. 2, п. 3, подп. 2)"
    assert found["3.1. Способ выплаты выбирает работник."] == "гл. 2, п. 3, п. 3.1"


def test_list_item_context_names_heading_and_lead_in() -> None:
    structure = parse_legal_act(ACT)
    index = next(
        position for position, block in enumerate(structure.blocks)
        if body(ACT, block) == "2) способ выплаты."
    )

    assert structure.context(index) == ("Глава 2. Сроки выплаты", "3. В приказе указываются:")


def test_location_is_the_common_unit_of_a_quote() -> None:
    structure = parse_legal_act(ACT)
    start = ACT.index("3. В приказе")
    end = ACT.index("2) способ") + 5

    assert structure.location(start, end) == "гл. 2, п. 3"
    assert structure.location(end - 3, end) == "гл. 2, п. 3, подп. 2)"


def test_act_without_numbering_counts_paragraphs() -> None:
    text = "Положение о выплате.\n\nЗарплата выплачивается\nдва раза в месяц.\nАванс не менее 40 процентов.\n"

    structure = parse_legal_act(text)

    assert [", ".join(block.path) for block in structure.blocks] == ["абз. 1", "абз. 2", "абз. 3"]
    assert body(text, structure.blocks[1]) == "Зарплата выплачивается два раза в месяц."


def test_metadata_before_normative_text_is_not_chunked() -> None:
    text = (
        "Название акта\n\n"
        "Изменения и дополнения:\n\n"
        "Закон Республики Беларусь от 1 января 2020 г. № 1-З;\n\n"
        "СОДЕРЖАНИЕ\n\n"
        "Статья 1. Заголовок\n\n"
        "Статья 2. Другой заголовок\n\n"
        "Статья 1. Заголовок\n\n"
        "1. Нормативный текст."
    )

    structure = parse_legal_act(text)
    chunks = chunk_legal_act(structure, legal_act_id=1, max_chars=4000)

    assert text[structure.normative_start:].startswith("Статья 1. Заголовок")
    assert all(
        block.category == "metadata"
        for block in structure.blocks
        if block.start < structure.normative_start
    )
    assert "".join(chunk.text for chunk in chunks).strip() == text[structure.normative_start:].strip()


def test_small_chunks_keep_headings_with_their_text() -> None:
    chunks = chunk_legal_act(parse_legal_act(ACT), legal_act_id=1, max_chars=100)

    assert [chunk.text.partition("\n")[0] for chunk in chunks] == [
        "Положение об оплате труда",
        "1. Настоящее Положение определяет порядок выплаты заработной платы",
        "Глава 2. Сроки выплаты",
        "3. В приказе указываются:",
        "3.1. Способ выплаты выбирает работник.",
    ]
    assert chunks[1].context == ("Глава 1. Общие положения",)
    assert chunks[4].context == ("Глава 2. Сроки выплаты", "3. В приказе указываются:")


def test_list_split_across_chunks_repeats_the_lead_in() -> None:
    chunks = chunk_legal_act(parse_legal_act(ACT), legal_act_id=1, max_chars=80)

    list_chunk = next(chunk for chunk in chunks if chunk.text.startswith("2) способ"))
    assert list_chunk.context == ("Глава 2. Сроки выплаты", "3. В приказе указываются:")


def test_whole_act_fits_one_chunk() -> None:
    chunks = chunk_legal_act(parse_legal_act(ACT), legal_act_id=7, max_chars=4000)

    assert len(chunks) == 1
    assert chunks[0].text == ACT.strip()
    assert chunks[0].context == ()
    assert chunks[0].chunk_id.startswith("legal-act-7:base:")


def test_long_paragraph_splits_between_sentences() -> None:
    text = " ".join(f"Предложение номер {index} описывает требование." for index in range(20))

    chunks = chunk_legal_act(parse_legal_act(text), legal_act_id=1, max_chars=120)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 120
        assert chunk.text.endswith(".")
        assert text[chunk.start_char:chunk.end_char] == chunk.text


@pytest.mark.parametrize("path", sorted(CORPUS.glob("*.txt")), ids=lambda path: path.stem)
@pytest.mark.parametrize("max_chars", [200, 400, 4000])
def test_corpus_chunks_never_cut_a_sentence(path: Path, max_chars: int) -> None:
    text = path.read_text(encoding="utf-8")

    chunks = chunk_legal_act(parse_legal_act(text), legal_act_id=1, max_chars=max_chars)

    structure = parse_legal_act(text)
    covered = "".join(chunk.text for chunk in chunks)
    assert re.sub(r"\s+", "", covered) == re.sub(
        r"\s+", "", text[structure.normative_start:]
    )
    for chunk in chunks:
        assert len(chunk.text) <= max_chars
        assert re.search(r"[.;:]$|[^\s.;:]$", chunk.text)
        assert chunk.text.rstrip()[-1] in ".;:" or "\n\n" in text[chunk.end_char:chunk.end_char + 2] \
            or chunk.end_char == len(text.rstrip())

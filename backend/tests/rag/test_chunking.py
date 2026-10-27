from edm_auditor.rag import chunk_text
from edm_auditor.rag.exceptions import InvalidChunkingConfiguration


def test_chunking_preserves_source_ranges() -> None:
    source = "First paragraph.\n\nSecond paragraph is longer.\nThird paragraph."

    chunks = chunk_text(source, legal_act_id=7, max_chars=30, overlap_chars=5)

    assert chunks
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(source[chunk.start_char : chunk.end_char] == chunk.text for chunk in chunks)
    assert [chunk.chunk_id for chunk in chunks] == [
        "legal-act-7:base:0991473799fddb66:paragraph-v1:0",
        "legal-act-7:base:0991473799fddb66:paragraph-v1:1",
        "legal-act-7:base:0991473799fddb66:paragraph-v1:2",
    ]


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text(" \n ", legal_act_id=1) == []


def test_invalid_chunking_configuration_is_explicit() -> None:
    try:
        chunk_text("text", legal_act_id=1, max_chars=10, overlap_chars=10)
    except InvalidChunkingConfiguration:
        pass
    else:
        raise AssertionError("invalid configuration must raise")

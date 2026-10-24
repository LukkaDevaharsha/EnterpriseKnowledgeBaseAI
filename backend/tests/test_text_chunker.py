import pytest

from app.services.text_chunker import split_text


def test_empty_and_whitespace_text_return_no_chunks():
    assert split_text("") == []
    assert split_text(" \n\t ") == []


def test_short_text_has_exact_source_offsets():
    assert split_text("  short text  ") == [{
        "chunk_index": 0,
        "content": "short text",
        "start_char": 2,
        "end_char": 12,
    }]


def test_long_text_overlaps_and_has_sequential_indices_and_offsets():
    text = " ".join(f"word{i}" for i in range(30))
    chunks = split_text(text, chunk_size=35, overlap=8)
    assert len(chunks) > 1
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk["content"] == text[chunk["start_char"]:chunk["end_char"]]
        assert len(chunk["content"]) <= 35
    assert any(
        current["start_char"] < previous["end_char"]
        for previous, current in zip(chunks, chunks[1:])
    )


def test_chunking_prefers_word_boundaries():
    chunks = split_text("alpha beta gamma delta epsilon", chunk_size=17, overlap=3)
    assert all(not chunk["content"].startswith(" ") for chunk in chunks)
    assert all(chunk["content"] == chunk["content"].strip() for chunk in chunks)


@pytest.mark.parametrize("chunk_size", [0, -1, 1.5, True])
def test_invalid_chunk_size(chunk_size):
    with pytest.raises(ValueError):
        split_text("abc", chunk_size=chunk_size)


@pytest.mark.parametrize("overlap", [-1, 2.5, True, 10])
def test_invalid_overlap(overlap):
    with pytest.raises(ValueError):
        split_text("abc", chunk_size=10, overlap=overlap)


def test_non_string_input_is_rejected():
    with pytest.raises(TypeError):
        split_text(None)

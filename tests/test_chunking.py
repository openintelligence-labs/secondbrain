from __future__ import annotations

import pytest

from secondbrain.chunking import chunk_text


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []


def test_short_text_is_single_chunk():
    chunks = chunk_text("hello world", max_words=10, overlap_words=2)
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"


def test_long_text_produces_overlapping_chunks():
    words = [str(i) for i in range(100)]
    text = " ".join(words)
    chunks = chunk_text(text, max_words=20, overlap_words=5)
    assert len(chunks) > 1
    # Stride is 15, so chunk 1 starts at word 15
    assert chunks[1].start_word == 15
    # Last chunk reaches the end
    assert chunks[-1].end_word == 100
    # Overlap: last 5 words of chunk 0 == first 5 of chunk 1
    c0 = chunks[0].text.split()
    c1 = chunks[1].text.split()
    assert c0[-5:] == c1[:5]


def test_overlap_must_be_smaller_than_max():
    with pytest.raises(ValueError):
        chunk_text("one two three", max_words=5, overlap_words=5)

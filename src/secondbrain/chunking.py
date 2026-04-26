from __future__ import annotations

from pydantic import BaseModel


class Chunk(BaseModel):
    index: int
    text: str
    start_word: int
    end_word: int


def chunk_text(text: str, *, max_words: int = 400, overlap_words: int = 50) -> list[Chunk]:
    """Word-based chunker with overlap.

    A proper version would tokenize; word splitting is a good-enough default
    for readability.
    """
    if overlap_words >= max_words:
        raise ValueError("overlap_words must be less than max_words")
    words = text.split()
    if not words:
        return []

    chunks: list[Chunk] = []
    stride = max_words - overlap_words
    idx = 0
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(
            Chunk(
                index=idx,
                text=" ".join(words[start:end]),
                start_word=start,
                end_word=end,
            )
        )
        if end == len(words):
            break
        start += stride
        idx += 1
    return chunks

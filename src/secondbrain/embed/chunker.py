"""Chunker for embedding inputs.

Re-exports the existing word-based chunker from `secondbrain.chunking` (OK
for today's inputs, which are typically short AX-text snippets) and adds a
`Chunk` typed record carrying the parent capture id.

Late-chunking hook: for inputs above `LATE_CHUNK_TOK_THRESHOLD` we will switch
to Jina-v3-style late chunking once long browser snapshots flow in. For now
the pipeline simply records `late_chunked: false` so we can swap behind the
same surface later without touching call sites.
"""

from __future__ import annotations

from dataclasses import dataclass

from secondbrain.chunking import chunk_text

LATE_CHUNK_TOK_THRESHOLD = 2000  # tokens; ~8000 words rough proxy


@dataclass(slots=True)
class Chunk:
    capture_id: str
    chunk_index: int
    text: str
    start_word: int
    end_word: int
    late_chunked: bool = False


def chunks_for(
    capture_id: str,
    text: str,
    *,
    max_words: int = 400,
    overlap_words: int = 50,
) -> list[Chunk]:
    """Slice `text` into Chunks attached to `capture_id`."""
    if not text:
        return []
    word_chunks = chunk_text(text, max_words=max_words, overlap_words=overlap_words)
    out = []
    for c in word_chunks:
        out.append(
            Chunk(
                capture_id=capture_id,
                chunk_index=c.index,
                text=c.text,
                start_word=c.start_word,
                end_word=c.end_word,
            )
        )
    return out

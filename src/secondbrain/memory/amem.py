"""A-MEM Zettelkasten linker.

Implements the "find top-K similar prior memories, write bidirectional KG
links" half of A-MEM (NeurIPS 2025). The retroactive note-rewrite half is
deferred until the Qwen3-8B synthesizer is wired.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import numpy as np


class _Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...


@dataclass
class AMemLinker:
    embedder: _Embedder
    top_k: int = 5
    min_similarity: float = 0.4

    def neighbors(
        self,
        new_text: str,
        existing: list[tuple[str, str]],
    ) -> list[tuple[str, float]]:
        """Return [(memory_id, similarity)] for the top-K most-similar peers.

        `existing` is the candidate set as `(memory_id, content)` tuples — the
        caller decides how to source it (same-day, same-app, full sweep, etc).
        """
        if not existing:
            return []
        texts = [content for _id, content in existing]
        ids = [mid for mid, _ in existing]
        all_vecs = self.embedder.embed_passages([new_text] + texts)
        q = all_vecs[0]
        cands = all_vecs[1:]
        sims = cands @ q
        ranked = sorted(zip(ids, sims, strict=True), key=lambda x: float(x[1]), reverse=True)
        return [
            (mid, float(s))
            for mid, s in ranked[: self.top_k]
            if float(s) >= self.min_similarity
        ]


def now() -> datetime:
    return datetime.now(timezone.utc)

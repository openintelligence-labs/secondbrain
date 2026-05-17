"""Deterministic stub embedder for tests.

Embeds via SHA-256 of token vocabulary → cheap, ordered, identical inputs
yield identical vectors. Same dim as Nomic v2 (768) so storage paths match.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

from secondbrain.embed.text import EMBEDDING_DIM


def _vec(text: str, dim: int = EMBEDDING_DIM) -> np.ndarray:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    out = np.zeros(dim, dtype=np.float32)
    rng = np.random.default_rng(int.from_bytes(h[:8], "big"))
    out[:] = rng.standard_normal(dim).astype(np.float32)
    out /= max(np.linalg.norm(out), 1e-9)
    # Add a token-presence signal so semantically similar strings cluster.
    for tok in set(text.lower().split()):
        idx = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:4], "big") % dim
        out[idx] += 1.0
    out /= max(np.linalg.norm(out), 1e-9)
    return out


class StubEmbedder:
    dim = EMBEDDING_DIM

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([_vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return _vec(text)

    async def aembed_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self.embed_passages(texts)

    async def aembed_query(self, text: str) -> np.ndarray:
        return self.embed_query(text)

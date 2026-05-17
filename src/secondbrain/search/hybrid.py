"""Hybrid retrieval.

Recipe:
    tantivy BM25 ⊕ LanceDB cosine → RRF k=60 → top-50 → (optional) reranker
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from secondbrain.embed.text import TextEmbedder
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore

DEFAULT_RRF_K = 60


@dataclass
class HybridHit:
    chunk_uid: str
    capture_id: str
    chunk_index: int
    body: str
    rrf_score: float
    bm25_rank: int | None
    dense_rank: int | None


def rrf_fuse(
    bm25_hits: list[dict[str, Any]],
    dense_hits: list[dict[str, Any]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[HybridHit]:
    """RRF k=60 fusion. Order is the order in which lists were ranked."""
    scored: dict[str, dict[str, Any]] = {}
    for rank, h in enumerate(bm25_hits, start=1):
        cuid = h["chunk_uid"]
        scored.setdefault(
            cuid,
            {
                "chunk_uid": cuid,
                "capture_id": h["capture_id"],
                "chunk_index": h["chunk_index"],
                "body": h.get("body", ""),
                "score": 0.0,
                "bm25_rank": None,
                "dense_rank": None,
            },
        )
        scored[cuid]["score"] += 1.0 / (k + rank)
        scored[cuid]["bm25_rank"] = rank

    for rank, h in enumerate(dense_hits, start=1):
        cuid = h["chunk_uid"]
        scored.setdefault(
            cuid,
            {
                "chunk_uid": cuid,
                "capture_id": h["capture_id"],
                "chunk_index": h["chunk_index"],
                "body": h.get("text", ""),
                "score": 0.0,
                "bm25_rank": None,
                "dense_rank": None,
            },
        )
        scored[cuid]["score"] += 1.0 / (k + rank)
        scored[cuid]["dense_rank"] = rank
        if not scored[cuid]["body"]:
            scored[cuid]["body"] = h.get("text", "")

    fused = sorted(scored.values(), key=lambda x: x["score"], reverse=True)
    return [
        HybridHit(
            chunk_uid=r["chunk_uid"],
            capture_id=r["capture_id"],
            chunk_index=r["chunk_index"],
            body=r["body"],
            rrf_score=r["score"],
            bm25_rank=r["bm25_rank"],
            dense_rank=r["dense_rank"],
        )
        for r in fused
    ]


@dataclass
class HybridSearcher:
    text_index: TextIndex
    vector_store: VectorStore
    embedder: TextEmbedder
    bm25_top: int = 50
    dense_top: int = 50
    rrf_k: int = DEFAULT_RRF_K

    def search(self, query: str, *, limit: int = 10) -> list[HybridHit]:
        bm25_hits = self.text_index.search(query, limit=self.bm25_top)
        qvec = self.embedder.embed_query(query)
        dense_hits = self.vector_store.search(qvec, limit=self.dense_top)
        fused = rrf_fuse(bm25_hits, dense_hits, k=self.rrf_k)
        return fused[:limit]

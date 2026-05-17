from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from secondbrain.embed.stub import StubEmbedder
from secondbrain.indexing import Indexer
from secondbrain.models import Capture
from secondbrain.search.hybrid import HybridSearcher, rrf_fuse
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


def _cap(text: str, app: str = "Test") -> Capture:
    return Capture(
        id=text[:8].replace(" ", "_"),
        captured_at=datetime.now(UTC),
        app_name=app,
        ax_text=text,
    )


def _build_searcher(tmp_path: Path) -> HybridSearcher:
    vector = VectorStore(db_path=tmp_path / "lance")
    text = TextIndex(index_path=tmp_path / "tantivy")
    embedder = StubEmbedder()
    indexer = Indexer(embedder=embedder, vector=vector, text=text)

    docs = [
        "Sam discussed Snowflake quarterly review and budget targets",
        "Kafka consumer lag spiked on the ingest pipeline",
        "Stripe billing integration hit a token expiry bug",
        "weekend hike notes — golden gate trail conditions",
        "snowflake bigquery cost comparison meeting outcomes",
    ]
    for d in docs:
        indexer.index_capture(_cap(d))

    return HybridSearcher(
        text_index=text,
        vector_store=vector,
        embedder=embedder,
    )


def test_rrf_fuse_orders_by_combined_score():
    bm25 = [
        {"chunk_uid": "a:0", "capture_id": "a", "chunk_index": 0, "body": "a"},
        {"chunk_uid": "b:0", "capture_id": "b", "chunk_index": 0, "body": "b"},
    ]
    dense = [
        {"chunk_uid": "b:0", "capture_id": "b", "chunk_index": 0, "text": "b"},
        {"chunk_uid": "c:0", "capture_id": "c", "chunk_index": 0, "text": "c"},
    ]
    fused = rrf_fuse(bm25, dense)
    assert fused[0].chunk_uid == "b:0"  # appears in both
    assert {h.chunk_uid for h in fused} == {"a:0", "b:0", "c:0"}


def test_hybrid_search_finds_snowflake(tmp_path: Path):
    searcher = _build_searcher(tmp_path)
    hits = searcher.search("snowflake meeting", limit=3)
    assert len(hits) >= 1
    bodies = " ".join(h.body.lower() for h in hits[:2])
    assert "snowflake" in bodies


def test_hybrid_search_p95_latency_is_fast(tmp_path: Path):
    searcher = _build_searcher(tmp_path)
    timings = []
    for _ in range(20):
        t0 = time.perf_counter()
        searcher.search("snowflake quarterly", limit=10)
        timings.append((time.perf_counter() - t0) * 1000)
    p95 = sorted(timings)[int(0.95 * len(timings))]
    # Generous upper bound; the full latency check at scale lives in eval/replay.
    assert p95 < 200, f"p95={p95:.1f}ms exceeded 200ms"

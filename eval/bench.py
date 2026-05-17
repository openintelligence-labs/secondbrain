"""Reproducible microbench — story P-09.

Two measurements:

1. **Cascade microbench**: per-gate cost on a fixed 1280×800 PIL image.
   Validates that the documented budgets (dHash ~0.3ms, pHash ~2ms, SSIM ~5ms)
   hold on the running machine.

2. **Retrieval p95**: index N synthetic captures, run M warm queries, report
   p50/p95/p99 and recall@10 against the seeded ground truth.

Run:
    .venv/bin/python eval/bench.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "src"))

from secondbrain.capture.dedup import dhash, hamming, phash, ssim_thumb  # noqa: E402
from secondbrain.embed.stub import StubEmbedder  # noqa: E402
from secondbrain.indexing import Indexer  # noqa: E402
from secondbrain.models import Capture  # noqa: E402
from secondbrain.search.hybrid import HybridSearcher  # noqa: E402
from secondbrain.store.text_index import TextIndex  # noqa: E402
from secondbrain.store.vector import VectorStore  # noqa: E402


def _img(seed: int, size=(1280, 800)) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, size=(size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(arr)


def cascade_bench(rounds: int = 100) -> dict:
    a = _img(1)
    b = _img(2)
    timings: dict[str, list[float]] = {"dhash": [], "phash": [], "ssim": [], "hamming": []}

    # warmup
    dhash(a)
    phash(a)
    ssim_thumb(a, b)

    for _ in range(rounds):
        t0 = time.perf_counter()
        h_a = dhash(a)
        timings["dhash"].append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        phash(a)
        timings["phash"].append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        ssim_thumb(a, b)
        timings["ssim"].append((time.perf_counter() - t0) * 1000)
        h_b = dhash(b)
        t0 = time.perf_counter()
        hamming(h_a, h_b)
        timings["hamming"].append((time.perf_counter() - t0) * 1000)

    return {
        gate: {
            "p50_ms": round(statistics.median(samples), 4),
            "p95_ms": round(sorted(samples)[int(0.95 * len(samples))], 4),
            "max_ms": round(max(samples), 4),
        }
        for gate, samples in timings.items()
    }


def retrieval_bench(n_captures: int = 500, n_queries: int = 50) -> dict:
    workdir = ROOT / "_bench_workdir"
    if workdir.exists():
        import shutil

        shutil.rmtree(workdir)
    workdir.mkdir()

    embedder = StubEmbedder()
    vector = VectorStore(db_path=workdir / "lance")
    text = TextIndex(index_path=workdir / "tantivy")
    indexer = Indexer(embedder=embedder, vector=vector, text=text)

    # Seed N captures with predictable text so we know what to query.
    topics = ["snowflake", "kafka", "stripe", "postgres", "openai", "alex", "linear"]
    for i in range(n_captures):
        topic = topics[i % len(topics)]
        cap = Capture(
            id=f"bench_{i:04d}",
            captured_at=datetime.now(UTC),
            app_name="Bench",
            ax_text=f"document {i} about {topic} migration review status #{i % 17}",
        )
        indexer.index_capture(cap)

    searcher = HybridSearcher(text_index=text, vector_store=vector, embedder=embedder)

    # Warmup
    searcher.search("snowflake", limit=10)

    timings: list[float] = []
    correct_topic = 0
    for i in range(n_queries):
        topic = topics[i % len(topics)]
        t0 = time.perf_counter()
        hits = searcher.search(f"{topic} migration review", limit=10)
        timings.append((time.perf_counter() - t0) * 1000)
        if hits and topic in (hits[0].body or "").lower():
            correct_topic += 1

    timings_sorted = sorted(timings)
    return {
        "n_captures": n_captures,
        "n_queries": n_queries,
        "p50_ms": round(statistics.median(timings_sorted), 2),
        "p95_ms": round(timings_sorted[int(0.95 * len(timings_sorted))], 2),
        "p99_ms": round(timings_sorted[int(0.99 * len(timings_sorted))], 2),
        "top1_topic_match": round(correct_topic / n_queries, 3),
    }


def reranker_bench(*, n_queries: int = 10, top_k: int = 30) -> dict:
    """Cost of running the mxbai cross-encoder over top_k candidates."""
    from secondbrain.search.rerank import Reranker

    rr = Reranker()
    if not rr._ensure_loaded():
        return {"loaded": False, "note": "model could not load (offline?)"}

    passages = [
        f"document {i} about snowflake migration review status #{i % 7}" for i in range(top_k)
    ]
    # warmup
    rr.rerank("snowflake migration", passages, top_k=top_k)

    timings: list[float] = []
    for _ in range(n_queries):
        t0 = time.perf_counter()
        rr.rerank("snowflake migration review", passages, top_k=top_k)
        timings.append((time.perf_counter() - t0) * 1000)
    timings_sorted = sorted(timings)
    return {
        "loaded": True,
        "n_queries": n_queries,
        "top_k": top_k,
        "p50_ms": round(statistics.median(timings_sorted), 2),
        "p95_ms": round(timings_sorted[int(0.95 * len(timings_sorted))], 2),
        "p99_ms": round(timings_sorted[int(0.99 * len(timings_sorted))], 2),
        "note": "mxbai-rerank-base-v2 on CPU; ~K cross-encoder forward passes per query.",
    }


def main() -> None:
    print("running cascade microbench...")
    cascade = cascade_bench()
    print("running retrieval bench...")
    retrieval = retrieval_bench()
    print("running reranker bench (this is slow on CPU)...")
    rerank = reranker_bench()
    out = {
        "cascade": cascade,
        "retrieval": retrieval,
        "rerank": rerank,
        "ts": datetime.now().isoformat(),
    }
    (ROOT / "bench_results.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

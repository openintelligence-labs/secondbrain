"""Verify tantivy-py BM25 + RRF fusion against a stub dense ranker.

Pass criteria:
- Index 1k synthetic docs in tantivy
- BM25 query returns sane top-K
- RRF k=60 fusion with a stub dense ranker produces a fused list
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tantivy  # noqa: E402
from _runner import record  # noqa: E402

WORDS = [
    "snowflake",
    "sam",
    "meeting",
    "snowflake-data",
    "quarterly",
    "review",
    "stripe",
    "billing",
    "auth",
    "token",
    "kafka",
    "consumer",
    "lag",
    "index",
    "embedding",
    "retrieval",
    "graph",
    "bi-temporal",
    "memory",
    "agent",
]


def synth_docs(n: int) -> list[tuple[int, str]]:
    import random

    rng = random.Random(42)
    docs = []
    for i in range(n):
        k = rng.randint(8, 30)
        body = " ".join(rng.choice(WORDS) for _ in range(k))
        docs.append((i, body))
    return docs


def rrf(ranklists: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for lst in ranklists:
        for rank, doc_id in enumerate(lst, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sb_tantivy_"))
    try:
        schema_builder = tantivy.SchemaBuilder()
        schema_builder.add_integer_field("id", stored=True, indexed=True)
        schema_builder.add_text_field("body", stored=True)
        schema = schema_builder.build()

        index = tantivy.Index(schema, path=str(tmp))
        writer = index.writer()
        docs = synth_docs(1000)
        t0 = time.perf_counter()
        for did, body in docs:
            writer.add_document(tantivy.Document(id=did, body=body))
        writer.commit()
        index.reload()
        index_ms = (time.perf_counter() - t0) * 1000

        searcher = index.searcher()
        query = index.parse_query("snowflake meeting", ["body"])
        t0 = time.perf_counter()
        top = searcher.search(query, 50).hits
        bm25_ms = (time.perf_counter() - t0) * 1000
        bm25_ranklist = [searcher.doc(doc_addr)["id"][0] for _score, doc_addr in top]

        # Stub dense rank: random permutation seeded on the query
        import random

        rng = random.Random(7)
        dense_ranklist = list(range(50))
        rng.shuffle(dense_ranklist)

        fused = rrf([bm25_ranklist[:50], dense_ranklist[:50]], k=60)

        passed = len(bm25_ranklist) > 0 and len(fused) > 0 and fused[0][1] > fused[-1][1]
        record(
            "S0-06",
            passed,
            {
                "tantivy_version": getattr(tantivy, "__version__", "unknown"),
                "docs_indexed": 1000,
                "index_total_ms": round(index_ms, 1),
                "bm25_query_ms": round(bm25_ms, 2),
                "bm25_top": bm25_ranklist[:5],
                "rrf_top5": [d for d, _s in fused[:5]],
                "rrf_top1_score": round(fused[0][1], 4),
            },
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

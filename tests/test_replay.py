from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from secondbrain.embed.stub import StubEmbedder
from secondbrain.eval.replay import load_cases, run as run_replay
from secondbrain.indexing import Indexer
from secondbrain.models import Capture
from secondbrain.search.hybrid import HybridSearcher
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


def _cap(cid: str, text: str) -> Capture:
    return Capture(
        id=cid,
        captured_at=datetime.now(timezone.utc),
        app_name="Test",
        ax_text=text,
    )


def test_replay_recall_and_latency(tmp_path: Path):
    vector = VectorStore(db_path=tmp_path / "lance")
    text = TextIndex(index_path=tmp_path / "tantivy")
    embedder = StubEmbedder()
    indexer = Indexer(embedder=embedder, vector=vector, text=text)

    docs = {
        "snow1": "Sam discussed Snowflake quarterly review and budget targets",
        "kafka1": "Kafka consumer lag spiked on the ingest pipeline",
        "stripe1": "Stripe billing integration hit a token expiry bug",
        "trail1": "weekend hike notes — golden gate trail conditions",
        "snow2": "snowflake bigquery cost comparison meeting outcomes",
    }
    for cid, body in docs.items():
        indexer.index_capture(_cap(cid, body))

    searcher = HybridSearcher(
        text_index=text,
        vector_store=vector,
        embedder=embedder,
    )

    cases_file = tmp_path / "cases.jsonl"
    cases_file.write_text(
        "\n".join(
            json.dumps(c)
            for c in [
                {"query": "snowflake quarterly review", "expected": ["snow1"]},
                {"query": "kafka consumer lag", "expected": ["kafka1"]},
                {"query": "stripe token expiry bug", "expected": ["stripe1"]},
            ]
        )
    )
    cases = load_cases(cases_file)
    result = run_replay(searcher, cases, k=5)
    assert result.n == 3
    assert result.recall_at_k == 1.0
    assert result.p95_ms < 200

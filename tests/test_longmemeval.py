"""LongMemEval harness drives end-to-end.

Synthetic 10-case mini-set (axis-tagged) so we can prove the harness works
without depending on the public LongMemEval dataset (which isn't redistributable).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from secondbrain.embed.stub import StubEmbedder
from secondbrain.eval.longmemeval import run as run_lme
from secondbrain.indexing import Indexer
from secondbrain.models import Capture
from secondbrain.search.hybrid import HybridSearcher
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


def _cap(cid: str, text: str) -> Capture:
    return Capture(
        id=cid,
        captured_at=datetime.now(UTC),
        app_name="Test",
        ax_text=text,
    )


def test_longmemeval_harness_runs(tmp_path: Path):
    vector = VectorStore(db_path=tmp_path / "lance")
    text = TextIndex(index_path=tmp_path / "tantivy")
    embedder = StubEmbedder()
    indexer = Indexer(embedder=embedder, vector=vector, text=text)

    captures = {
        "snow1": "Sam Reed agreed to ship the Snowflake migration by Friday.",
        "kafka1": "Kafka consumer lag spiked at 14:02 on the ingest pipeline.",
        "stripe1": "Stripe billing token expiry hit on Thursday.",
        "trail1": "Weekend hike — golden gate trail conditions are dry.",
    }
    for cid, body in captures.items():
        indexer.index_capture(_cap(cid, body))

    cases = tmp_path / "lme.jsonl"
    cases.write_text(
        "\n".join(
            json.dumps(c)
            for c in [
                {
                    "axis": "extraction",
                    "query": "snowflake migration friday",
                    "expected_capture_ids": ["snow1"],
                },
                {
                    "axis": "extraction",
                    "query": "kafka consumer lag",
                    "expected_capture_ids": ["kafka1"],
                },
                {
                    "axis": "temporal",
                    "query": "stripe billing token expiry",
                    "expected_capture_ids": ["stripe1"],
                },
                {
                    "axis": "abstention",
                    "query": "marsupial breeding seasons",
                    "expected_capture_ids": [],
                },
            ]
        )
    )

    searcher = HybridSearcher(text_index=text, vector_store=vector, embedder=embedder)
    out = run_lme(searcher, cases, k=5)
    assert out.n == 4
    # 3 of 4 extraction/temporal cases land their expected capture; the
    # abstention case may also pass depending on rrf_score thresholds.
    assert out.overall_accuracy >= 0.6
    assert "extraction" in out.by_axis

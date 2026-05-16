from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from secondbrain.embed.stub import StubEmbedder
from secondbrain.indexing import Indexer
from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.models import Capture
from secondbrain.search.hybrid import HybridSearcher
from secondbrain.search.kg_filter import KGAwareSearcher
from secondbrain.store.kg import KnowledgeGraph
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


def _cap(cid: str, text: str) -> Capture:
    return Capture(
        id=cid,
        captured_at=datetime.now(timezone.utc),
        app_name="Slack",
        app_bundle_id="com.slack",
        ax_text=text,
    )


def test_kg_prefilter_constrains_results(tmp_path: Path):
    vector = VectorStore(db_path=tmp_path / "lance")
    text = TextIndex(index_path=tmp_path / "tantivy")
    embedder = StubEmbedder()
    indexer = Indexer(embedder=embedder, vector=vector, text=text)

    kg = KnowledgeGraph(db_path=tmp_path / "kg")
    pipe = MemoryPipeline(
        kg=kg,
        linker=AMemLinker(embedder=embedder),
        resolver=EntityResolver(kg=kg),
    )

    docs = [
        ("a", "Sam Reed discussed Snowflake quarterly review."),
        ("b", "Pat Lane discussed Snowflake quarterly review separately."),
        ("c", "Snowflake is a data warehouse."),
    ]
    for cid, body in docs:
        cap = _cap(cid, body)
        indexer.index_capture(cap)
        pipe.ingest(cap)

    inner = HybridSearcher(text_index=text, vector_store=vector, embedder=embedder)
    kgs = KGAwareSearcher(kg=kg, inner=inner)

    hits = kgs.search("Snowflake review with Sam Reed", limit=5)
    cids = [h.capture_id for h in hits]
    # Sam Reed prefilter must exclude Pat's capture.
    assert "a" in cids
    assert "b" not in cids

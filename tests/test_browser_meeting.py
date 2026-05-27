from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from secondbrain.capture.browser import chromium_history
from secondbrain.capture.meetmind_adapter import ingest_meeting
from secondbrain.embed.stub import StubEmbedder
from secondbrain.indexing import Indexer
from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.search.hybrid import HybridSearcher
from secondbrain.store.kg import KnowledgeGraph
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


def _make_chrome_db(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT, last_visit_time INTEGER)"
    )
    base = (
        datetime(2026, 5, 5, tzinfo=UTC) - datetime(1601, 1, 1, tzinfo=UTC)
    ).total_seconds() * 1_000_000
    conn.execute(
        "INSERT INTO urls(url, title, last_visit_time) VALUES (?, ?, ?)",
        ("https://example.com/snowflake", "Snowflake article", int(base)),
    )
    conn.execute(
        "INSERT INTO urls(url, title, last_visit_time) VALUES (?, ?, ?)",
        ("https://example.com/cats", "Cat blog", int(base) - 3600 * 1_000_000),
    )
    conn.commit()
    conn.close()
    return path


def test_chromium_history_yields_captures(tmp_path: Path):
    db = _make_chrome_db(tmp_path / "History")
    caps = list(chromium_history(db, limit=10))
    assert len(caps) == 2
    assert any(c.url == "https://example.com/snowflake" for c in caps)


def test_meeting_then_browser_unified_query(tmp_path: Path):
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

    # Meeting at 11am: Sam talks about Snowflake.
    meeting = {
        "id": "m1",
        "started_at": "2026-05-05T11:00:00Z",
        "title": "Snowflake migration sync",
        "segments": [
            {
                "id": "s1",
                "speaker_id": "u-sam",
                "speaker_name": "Sam Reed",
                "text": "We need the Snowflake migration done by Friday.",
                "start_ms": 0,
                "end_ms": 8000,
            },
            {
                "id": "s2",
                "speaker_id": "u-pat",
                "speaker_name": "Pat Lane",
                "text": "I will draft the rollback plan tonight.",
                "start_ms": 9000,
                "end_ms": 14000,
            },
        ],
    }
    ingest_meeting(meeting, indexer=indexer, pipe=pipe, resolver=EntityResolver(kg=kg))

    # Browser visit at 10am: an article on Snowflake.
    db = _make_chrome_db(tmp_path / "History")
    for cap in chromium_history(db, limit=10):
        indexer.index_capture(cap)
        pipe.ingest(cap)

    searcher = HybridSearcher(text_index=text, vector_store=vector, embedder=embedder)
    hits = searcher.search("Snowflake migration", limit=5)
    sources = {h.capture_id.split(":")[0] for h in hits}
    # Both modalities should surface in a single query.
    assert "audio" in sources
    assert "browser" in sources

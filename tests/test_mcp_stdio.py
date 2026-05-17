"""Verify the FastMCP app builds and registers all 7 tools."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from secondbrain.api.mcp_server import list_tools
from secondbrain.api.mcp_stdio import build_app
from secondbrain.embed.stub import StubEmbedder
from secondbrain.indexing import Indexer
from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.models import Capture
from secondbrain.store.captures import insert as insert_capture
from secondbrain.store.kg import KnowledgeGraph
from secondbrain.store.oltp import open_unencrypted
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


def _seed(tmp_path: Path) -> Path:
    db = tmp_path / "secondbrain.db"
    base = db.parent
    vector = VectorStore(db_path=base / "lance")
    text = TextIndex(index_path=base / "tantivy")
    kg = KnowledgeGraph(db_path=base / "kg")
    embedder = StubEmbedder()
    indexer = Indexer(embedder=embedder, vector=vector, text=text)
    pipe = MemoryPipeline(
        kg=kg,
        linker=AMemLinker(embedder=embedder),
        resolver=EntityResolver(kg=kg),
    )
    oltp = open_unencrypted(db)
    cap = Capture(
        id="c1",
        captured_at=datetime(2026, 5, 5, tzinfo=UTC),
        app_name="Slack",
        ax_text="Sam Reed will ship Snowflake migration by Friday.",
    )
    insert_capture(oltp, cap)
    indexer.index_capture(cap)
    pipe.ingest(cap)
    oltp.close()
    return db


def test_mcp_stdio_app_registers_seven_tools(tmp_path: Path):
    db = _seed(tmp_path)
    # `_seed` returned without us holding any references to the TextIndex /
    # IndexWriter; force collection so tantivy releases the writer-lock on
    # the index dir before `build_app` opens it again.
    import gc

    gc.collect()

    app = build_app(db=db, use_stub_embedder=True)
    # FastMCP exposes a list_tools coroutine; tools live on its tool manager.
    registered = {t.name for t in app._tool_manager._tools.values()}
    expected = {t.name for t in list_tools()}
    assert expected.issubset(registered), f"missing: {expected - registered}"
    assert len(expected) == 7

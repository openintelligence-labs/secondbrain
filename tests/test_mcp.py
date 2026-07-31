"""MCP smoke test: every one of the 7 tools through the in-process router."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from secondbrain.api.mcp_server import (
    call,
    list_tools,
    make_default_context,
)
from secondbrain.embed.stub import StubEmbedder
from secondbrain.indexing import Indexer
from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.models import Capture
from secondbrain.store.captures import insert as insert_capture


def _seed(tmp_path: Path):
    db = tmp_path / "secondbrain.db"
    ctx = make_default_context(db=db, use_stub_embedder=True)
    indexer = Indexer(embedder=StubEmbedder(), vector=ctx.vector, text=ctx.text)
    pipe = MemoryPipeline(
        kg=ctx.kg,
        linker=AMemLinker(embedder=StubEmbedder()),
        resolver=EntityResolver(kg=ctx.kg),
    )
    when = datetime(2026, 5, 5, 14, 0, tzinfo=UTC)
    captures = [
        Capture(
            id="c1",
            captured_at=when,
            app_name="Slack",
            ax_text="Sam Reed will ship Snowflake migration by Friday.",
        ),
        Capture(
            id="c2",
            captured_at=when,
            app_name="Linear",
            ax_text="Stripe billing token expiry needs a hotfix.",
        ),
    ]
    oltp = ctx.oltp
    for cap in captures:
        insert_capture(oltp, cap)
        indexer.index_capture(cap)
        pipe.ingest(cap)
    return ctx


def test_tool_list_has_seven_tools():
    names = {t.name for t in list_tools()}
    assert "memory.search" in names
    assert "memory.forget" in names
    assert len(names) == 7


def test_search_via_mcp(tmp_path: Path):
    ctx = _seed(tmp_path)
    out = call(ctx, "memory.search", {"query": "snowflake migration", "limit": 5})
    assert "hits" in out
    assert any(h["capture_id"] == "c1" for h in out["hits"])


def test_get_person_via_mcp(tmp_path: Path):
    ctx = _seed(tmp_path)
    out = call(ctx, "memory.get_person", {"name": "Sam Reed"})
    assert "facts" in out
    assert any("Snowflake" in f["content"] for f in out["facts"])


def test_recall_timeline_via_mcp(tmp_path: Path):
    ctx = _seed(tmp_path)
    out = call(
        ctx,
        "memory.recall_timeline",
        {"start": "2026-05-04", "end": "2026-05-06"},
    )
    assert "events" in out
    assert len(out["events"]) >= 1


def test_add_note_via_mcp(tmp_path: Path):
    ctx = _seed(tmp_path)
    out = call(ctx, "memory.add_note", {"text": "Reminder: cancel SaaS X."})
    assert "memory_id" in out
    assert out["chunks_indexed"] >= 1


def test_add_note_is_searchable(tmp_path: Path):
    """A note must be retrievable through memory.search hybrid RRF."""
    ctx = _seed(tmp_path)
    added = call(ctx, "memory.add_note", {"text": "Quarterly OKR retro moved to Thursday 3pm."})
    out = call(ctx, "memory.search", {"query": "quarterly OKR retro Thursday", "limit": 5})
    assert any(h["capture_id"] == added["capture_id"] for h in out["hits"])


def test_add_note_forget_cascades(tmp_path: Path):
    """forget --capture-id must delete the note's MemoryNode."""
    ctx = _seed(tmp_path)
    added = call(ctx, "memory.add_note", {"text": "Throwaway note to be forgotten."})
    out = call(ctx, "memory.forget", {"capture_id": added["capture_id"], "reason": "test"})
    assert out["deleted"] >= 1


def test_add_note_survives_embedder_outage(tmp_path: Path):
    """With the embedder down, notes still land in tantivy and OLTP."""

    class _BrokenEmbedder:
        def embed_passages(self, texts):
            raise RuntimeError("model not cached")

        def embed_query(self, text):
            raise RuntimeError("model not cached")

    ctx = _seed(tmp_path)
    ctx.embedder = _BrokenEmbedder()
    added = call(ctx, "memory.add_note", {"text": "Rotate the Vault signing key next sprint."})
    assert added["vector_indexed"] is False
    assert added["chunks_indexed"] >= 1
    bm25 = ctx.text.search("rotate vault signing key", limit=5)
    assert any(h["capture_id"] == added["capture_id"] for h in bm25)
    # The OLTP row lets `secondbrain index` backfill vectors later.
    row = ctx.oltp.execute(
        "SELECT source, ax_text FROM captures WHERE id=?", (added["capture_id"],)
    ).fetchone()
    assert row == ("note", "Rotate the Vault signing key next sprint.")


def test_forget_via_mcp(tmp_path: Path):
    ctx = _seed(tmp_path)
    out = call(ctx, "memory.forget", {"capture_id": "c1", "reason": "user request"})
    assert out["deleted"] >= 1
    rows = ctx.oltp.execute("SELECT action FROM audit_log WHERE action='forget'").fetchall()
    assert len(rows) >= 1


def test_unknown_tool_returns_error(tmp_path: Path):
    ctx = _seed(tmp_path)
    out = call(ctx, "memory.nope", {})
    assert "error" in out


def test_daily_digest_via_mcp(tmp_path: Path):
    ctx = _seed(tmp_path)
    out = call(ctx, "memory.daily_digest", {"date": "2026-05-05", "period": "day"})
    assert out["period"] == "day"
    assert "themes" in out

"""Full end-to-end smoke without a display.

Drives the entire shipping stack against synthetic frames containing real
text, then exercises:
   capture → cascade → embed → KG → search → who → MCP forget → cascade
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from secondbrain.api.mcp_server import call
from secondbrain.capture.frame import Frame, SyntheticFrameSource
from secondbrain.daemon import Daemon, DaemonConfig
from secondbrain.search.hybrid import HybridSearcher
from secondbrain.store.captures import recent
from secondbrain.store.oltp import open_unencrypted


def _frames() -> list[Frame]:
    rng = np.random.default_rng(0)

    def img(seed: int) -> Image.Image:
        a = rng.integers(0, 255, size=(120, 160, 3), dtype=np.uint8)
        return Image.fromarray(a)

    payloads = [
        ("Slack", "Sam Reed will ship the Snowflake migration by Friday."),
        ("Linear", "Stripe billing token expiry hotfix needed Wednesday."),
        ("Notion", "Snowflake bigquery cost comparison meeting outcomes."),
        ("Notes", "Weekend hike — golden gate trail conditions are dry."),
    ]
    out: list[Frame] = []
    for i, (app, text) in enumerate(payloads):
        out.append(
            Frame(
                captured_at=datetime(2026, 5, 5, 12, i, tzinfo=UTC),
                image=img(i),
                app_name=app,
                app_bundle_id=f"com.example.{app.lower()}",
                window_title="(test)",
                ax_text=text,
                dirty_rect_fraction=0.5,
            )
        )
    return out


def test_full_e2e_capture_search_who_forget(tmp_path: Path):
    db = tmp_path / "secondbrain.db"
    cfg = DaemonConfig(db_path=db, use_encryption=False, use_stub_embedder=True)
    daemon = Daemon(cfg)
    asyncio.run(daemon.run(SyntheticFrameSource(_frames())))

    # 1. OLTP has all 4 captures.
    conn = open_unencrypted(db)
    rows = list(recent(conn, limit=10))
    assert len(rows) == 4

    # 2. Hybrid search via the daemon's own handles (avoids tantivy lock conflict).
    assert daemon._indexer is not None
    searcher = HybridSearcher(
        text_index=daemon._indexer.text,
        vector_store=daemon._indexer.vector,
        embedder=daemon._indexer.embedder,
    )
    hits = searcher.search("Snowflake migration Sam", limit=5)
    top_two = " ".join(h.body.lower() for h in hits[:2])
    assert "snowflake" in top_two
    assert "sam" in top_two

    # 3. KG knows about Sam Reed.
    assert daemon._memory is not None
    kg = daemon._memory.kg
    r = kg._conn.execute("MATCH (p:Person {name:'Sam Reed'}) RETURN p.id")
    assert r.has_next()
    sam_id = r.get_next()[0]

    # 4. MCP tool call against the daemon's running context (in-process).
    from secondbrain.api.mcp_server import MCPContext

    ctx = MCPContext(
        kg=daemon._memory.kg,
        vector=daemon._indexer.vector,
        text=daemon._indexer.text,
        embedder=daemon._indexer.embedder,
        oltp=conn,
    )
    mcp_search = call(ctx, "memory.search", {"query": "Snowflake migration", "limit": 3})
    assert any("snowflake" in (h.get("snippet") or "").lower() for h in mcp_search["hits"])

    # 5. memory.get_person returns the Person card.
    person_card = call(ctx, "memory.get_person", {"name": "Sam Reed"})
    assert person_card["person_id"] == sam_id
    assert any("snowflake" in f["content"].lower() for f in person_card["facts"])

    # 6. memory.forget cascades.
    target = rows[0]["id"]
    out = call(ctx, "memory.forget", {"capture_id": target, "reason": "e2e smoke"})
    assert "deleted" in out

    # The audit log records this attempt.
    audit_rows = conn.execute("SELECT action FROM audit_log WHERE action='forget'").fetchall()
    assert len(audit_rows) >= 1

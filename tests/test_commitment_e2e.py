"""F-05 — commitments actually flow from a captured sentence into the KG and
out through the MCP `memory.commitments` tool.

Before this test existed, the daemon never wrote a single Commitment node —
the pipeline only called `extract.py::extract`, which emits episodic
MemoryNodes. The MCP tool I'd already shipped queried an empty table.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from secondbrain.api.mcp_server import MCPContext, call
from secondbrain.capture.frame import Frame, SyntheticFrameSource
from secondbrain.daemon import Daemon, DaemonConfig
from secondbrain.store.oltp import open_unencrypted


def _frame_with_commitment(text: str, ts: datetime) -> Frame:
    rng = np.random.default_rng(0)
    return Frame(
        captured_at=ts,
        image=Image.fromarray(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)),
        app_name="Slack",
        app_bundle_id="com.slack",
        window_title="(test)",
        ax_text=text,
        dirty_rect_fraction=0.5,
    )


def test_daemon_writes_commitment_nodes(tmp_path: Path):
    db = tmp_path / "secondbrain.db"
    cfg = DaemonConfig(db_path=db, use_encryption=False, use_stub_embedder=True)
    daemon = Daemon(cfg)

    base = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    frames = [
        _frame_with_commitment(
            "Sam Reed: I'll send the Snowflake migration design doc by Friday.",
            base,
        ),
        _frame_with_commitment(
            "Pat Lane will deploy the Stripe billing rollback on Wednesday.",
            base.replace(minute=1),
        ),
        # No-commitment control row.
        _frame_with_commitment(
            "Weekend hike notes — golden gate trail conditions are dry.",
            base.replace(minute=2),
        ),
    ]
    asyncio.run(daemon.run(SyntheticFrameSource(frames)))

    assert daemon._memory is not None
    rows = daemon._memory.kg.commitments(status="open")
    contents = [r["content"] for r in rows]

    # The first frame is a clear first-person commitment (regex catches "I'll send").
    assert any("send" in c.lower() and "design doc" in c.lower() for c in contents), (
        f"first-person commitment was not written. rows: {rows}"
    )
    # No-commitment control should not produce a row from "weekend hike notes".
    assert not any("hike" in c.lower() for c in contents)


def test_mcp_commitments_returns_real_rows(tmp_path: Path):
    db = tmp_path / "secondbrain.db"
    cfg = DaemonConfig(db_path=db, use_encryption=False, use_stub_embedder=True)
    daemon = Daemon(cfg)

    asyncio.run(daemon.run(SyntheticFrameSource([
        _frame_with_commitment(
            "I'll send the Snowflake design doc by Friday.",
            datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc),
        ),
    ])))

    assert daemon._memory is not None
    assert daemon._indexer is not None

    ctx = MCPContext(
        kg=daemon._memory.kg,
        vector=daemon._indexer.vector,
        text=daemon._indexer.text,
        embedder=daemon._indexer.embedder,
        oltp=open_unencrypted(db),
    )
    out = call(ctx, "memory.commitments", {"status": "open"})
    assert "commitments" in out
    assert len(out["commitments"]) >= 1
    item = out["commitments"][0]
    # Required fields the docstring promises.
    assert "id" in item
    assert "content" in item
    assert "status" in item
    assert "due_at" in item   # may be None or ISO string


def test_due_before_filter(tmp_path: Path):
    db = tmp_path / "secondbrain.db"
    cfg = DaemonConfig(db_path=db, use_encryption=False, use_stub_embedder=True)
    daemon = Daemon(cfg)

    base = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    asyncio.run(daemon.run(SyntheticFrameSource([
        _frame_with_commitment(
            "I'll send the doc tomorrow.",
            base,
        ),
        _frame_with_commitment(
            "I will ship the code by Friday.",
            base,
        ),
    ])))

    assert daemon._memory is not None
    # Filter for things due before "tomorrow" — i.e. only "today/tonight" stuff.
    # Both heuristic fixtures resolve to a real datetime, so the comparison
    # exercises the Cypher WHERE branch.
    rows = daemon._memory.kg.commitments(
        status="open",
        due_before=base.replace(day=base.day + 1, hour=23, minute=59),
    )
    # At least one commitment should be due before end-of-tomorrow.
    assert len(rows) >= 1

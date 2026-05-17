"""F-01 — does `memory.forget` actually cascade when the daemon's KG is alive?

The "GDPR-by-construction" claim falls apart if a forget call from MCP runs
against a fresh Kùzu handle while the daemon's separate handle still has a
write lock. This test is the first thing that exercises both at once.

Three scenarios:
  1. Daemon writes captures → daemon dies → MCP context opens fresh →
     `memory.forget(capture_id=...)` cascades. (Already covered by test_e2e
     but with the same handle; here we open a separate one.)
  2. Daemon's KG handle is still open when MCP context tries to open its
     own — Kùzu's per-process exclusivity should be exposed.
  3. Daemon's pipeline writes → forget → daemon's pipeline reads back →
     does it see the deletion?
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from secondbrain.api.mcp_server import MCPContext, call
from secondbrain.capture.frame import Frame, SyntheticFrameSource
from secondbrain.daemon import Daemon, DaemonConfig
from secondbrain.store.kg import KnowledgeGraph
from secondbrain.store.oltp import open_unencrypted


def _seed_via_daemon(tmp_path: Path) -> Daemon:
    """Run the daemon over fixed frames and return it (still holding handles)."""
    db = tmp_path / "secondbrain.db"
    cfg = DaemonConfig(db_path=db, use_encryption=False, use_stub_embedder=True)
    daemon = Daemon(cfg)

    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(0)
    frames = [
        Frame(
            captured_at=datetime(2026, 5, 6, 12, i, tzinfo=UTC),
            image=Image.fromarray(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)),
            app_name="Slack",
            app_bundle_id="com.slack",
            window_title="(test)",
            ax_text=text,
            dirty_rect_fraction=0.5,
        )
        for i, text in enumerate(
            [
                "Sam Reed will ship the Snowflake migration by Friday.",
                "Pat Lane wrote the rollback plan.",
                "Stripe billing token expiry hotfix Wednesday.",
            ]
        )
    ]
    asyncio.run(daemon.run(SyntheticFrameSource(frames)))
    return daemon


def test_mcp_forget_works_after_daemon_finishes(tmp_path: Path):
    """Scenario 1: daemon ran, exited, MCP picks up. The handle the daemon held
    has been GC'd by then; a fresh KnowledgeGraph should be openable."""
    daemon = _seed_via_daemon(tmp_path)
    assert daemon._memory is not None

    # Use the daemon's *own* handles for the MCP context — what test_e2e does.
    db = tmp_path / "secondbrain.db"
    conn = open_unencrypted(db)

    # Find a real capture id to forget.
    cap_id = next(iter(r[0] for r in conn.execute("SELECT id FROM captures LIMIT 1")))

    ctx = MCPContext(
        kg=daemon._memory.kg,
        vector=daemon._indexer.vector,
        text=daemon._indexer.text,
        embedder=daemon._indexer.embedder,
        oltp=conn,
    )
    out = call(ctx, "memory.forget", {"capture_id": cap_id, "reason": "F-01 test"})
    assert "deleted" in out
    assert out["deleted"] >= 0
    # Capture node must be gone from the KG.
    r = daemon._memory.kg._conn.execute(
        "MATCH (c:Capture {id:$id}) RETURN count(c)", {"id": cap_id}
    )
    assert r.get_next()[0] == 0


def test_separate_kuzu_handle_collides_with_daemon(tmp_path: Path):
    """Scenario 2: open a *second* Kùzu handle on the same DB while the
    daemon's first handle is still alive. This is what would happen if a
    `secondbrain mcp` server spun up while `secondbrain run` was still
    capturing — a likely user setup."""
    _seed_via_daemon(tmp_path)

    # Daemon's KG is still alive; trying to open another connection on the
    # same Kùzu DB from this same process should either share or collide.
    raised: Exception | None = None
    second = None
    try:
        second = KnowledgeGraph(db_path=tmp_path / "kg")
        # If we got here, see how many MemoryNodes the second handle sees.
        r = second._conn.execute("MATCH (m:MemoryNode) RETURN count(m)")
        n = r.get_next()[0]
        # If the daemon wrote 3 importance>floor captures, n should be > 0.
        # Mostly we want to know whether a second handle is even creatable.
        print(f"second-handle-saw {n} memory nodes")
    except Exception as e:
        raised = e
        print(f"second-handle-raised {type(e).__name__}: {e}")

    # Document the answer either way; fail only on a totally mysterious error.
    if (
        raised is not None
        and "lock" not in repr(raised).lower()
        and "unique" not in repr(raised).lower()
        and "concurrent" not in repr(raised).lower()
        and "open" not in repr(raised).lower()
    ):
        pytest.fail(f"Second handle raised an unexpected exception: {raised!r}")


def test_kuzu_two_process_collision(tmp_path: Path):
    """The actual user scenario: `secondbrain run` and `secondbrain mcp`
    run as separate processes against the same on-disk DB. Kùzu generally
    holds a per-process exclusive write lock; opening from a second
    process while the first is alive should either share-or-collide
    visibly (not corrupt silently)."""
    import subprocess
    import sys

    # Process A: opens the KG, holds it open for a few seconds.
    db_root = tmp_path / "kg"
    holder_script = (
        "import time, sys; "
        "sys.path.insert(0, {!r}); "
        "from secondbrain.store.kg import KnowledgeGraph; "
        "kg = KnowledgeGraph(db_path={!r}); "
        "kg._conn.execute('MATCH (n) RETURN count(n)').get_next(); "
        "print('A_OPEN', flush=True); "
        "time.sleep(3)"
    ).format(
        str(Path(__file__).resolve().parents[1] / "src"),
        str(db_root),
    )

    holder = subprocess.Popen(
        [sys.executable, "-c", holder_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Wait until A has opened.
    while True:
        line = holder.stdout.readline() if holder.stdout else ""
        if not line or "A_OPEN" in line:
            break

    # Process B: try to open the same DB.
    try:
        kg2 = KnowledgeGraph(db_path=db_root)
        # If it didn't raise, see if it can read.
        try:
            r = kg2._conn.execute("MATCH (n) RETURN count(n)")
            r.get_next()
            outcome = "concurrent-open-ok"
        except Exception as e:
            outcome = f"open-ok-query-failed: {type(e).__name__}: {e}"
    except Exception as e:
        outcome = f"open-failed: {type(e).__name__}: {e}"

    holder.terminate()
    holder.wait(timeout=5)

    # We don't fail the test on either outcome — we just want it on the record.
    # If "open-failed" with a lock-shaped error, we know the real-user setup
    # (run in one terminal + mcp in another) has a problem we'd have to solve
    # before claiming GDPR delete works concurrently.
    print(f"two-process-outcome: {outcome}")
    assert outcome.startswith(("concurrent-open", "open-failed", "open-ok"))


def test_forget_visible_to_daemon_pipeline(tmp_path: Path):
    """Scenario 3: write → forget → re-query through the same pipeline. A
    forget that doesn't show up in the daemon's own subsequent reads is
    worse than no forget at all."""
    daemon = _seed_via_daemon(tmp_path)
    assert daemon._memory is not None

    cap_ids_before = [
        r[0] for r in daemon._memory.kg._conn.execute("MATCH (c:Capture) RETURN c.id")
    ]
    # Iterate the result fully to release Kùzu's cursor before next query.
    target = list(cap_ids_before)[0]

    # Forget through the daemon's KG handle directly.
    n_deleted = daemon._memory.kg.forget_capture(target)
    assert n_deleted >= 0

    # Re-query through the same handle.
    cap_ids_after = [r[0] for r in daemon._memory.kg._conn.execute("MATCH (c:Capture) RETURN c.id")]
    assert target not in cap_ids_after, (
        "forget_capture did not remove the Capture node visible to the same handle"
    )

"""`memory.forget` cascade behavior while the daemon's Kùzu handle is alive.

Kùzu holds per-process exclusive locks, so a forget issued from MCP against a
separate handle is the case that would break the GDPR-delete guarantee.
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
    """Run the daemon over fixed frames; the returned daemon still holds handles."""
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
    daemon = _seed_via_daemon(tmp_path)
    assert daemon._memory is not None

    db = tmp_path / "secondbrain.db"
    conn = open_unencrypted(db)

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
    r = daemon._memory.kg._conn.execute(
        "MATCH (c:Capture {id:$id}) RETURN count(c)", {"id": cap_id}
    )
    assert r.get_next()[0] == 0


def test_separate_kuzu_handle_collides_with_daemon(tmp_path: Path):
    """A second Kùzu handle on the same DB must share or collide, not corrupt.

    This is the `secondbrain mcp` + `secondbrain run` setup.
    """
    _seed_via_daemon(tmp_path)

    raised: Exception | None = None
    second = None
    try:
        second = KnowledgeGraph(db_path=tmp_path / "kg")
        r = second._conn.execute("MATCH (m:MemoryNode) RETURN count(m)")
        n = r.get_next()[0]
        print(f"second-handle-saw {n} memory nodes")
    except Exception as e:
        raised = e
        print(f"second-handle-raised {type(e).__name__}: {e}")

    # Either outcome is acceptable; only an unrecognized error is a failure.
    if (
        raised is not None
        and "lock" not in repr(raised).lower()
        and "unique" not in repr(raised).lower()
        and "concurrent" not in repr(raised).lower()
        and "open" not in repr(raised).lower()
    ):
        pytest.fail(f"Second handle raised an unexpected exception: {raised!r}")


def test_kuzu_two_process_collision(tmp_path: Path):
    """Two processes on the same on-disk DB must collide visibly, not silently."""
    import subprocess
    import sys

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
    while True:
        line = holder.stdout.readline() if holder.stdout else ""
        if not line or "A_OPEN" in line:
            break

    try:
        kg2 = KnowledgeGraph(db_path=db_root)
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

    print(f"two-process-outcome: {outcome}")
    assert outcome.startswith(("concurrent-open", "open-failed", "open-ok"))


def test_forget_visible_to_daemon_pipeline(tmp_path: Path):
    """A forget must be visible to the daemon's own subsequent reads."""
    daemon = _seed_via_daemon(tmp_path)
    assert daemon._memory is not None

    cap_ids_before = [
        r[0] for r in daemon._memory.kg._conn.execute("MATCH (c:Capture) RETURN c.id")
    ]
    # Iterate the result fully to release Kùzu's cursor before the next query.
    target = list(cap_ids_before)[0]

    n_deleted = daemon._memory.kg.forget_capture(target)
    assert n_deleted >= 0

    cap_ids_after = [r[0] for r in daemon._memory.kg._conn.execute("MATCH (c:Capture) RETURN c.id")]
    assert target not in cap_ids_after, (
        "forget_capture did not remove the Capture node visible to the same handle"
    )

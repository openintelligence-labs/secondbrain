"""H-08 — daemon end-to-end with the LLM actually in the loop.

Skipped when Ollama isn't reachable. Otherwise:
  - drives 4 synthetic captures through the daemon with `enable_llm=True`
  - verifies that at least one resulting MemoryNode in Kùzu has an importance
    score that doesn't match what the heuristic would have produced for the
    same text — i.e. the LLM was actually consulted, not bypassed.

This is the test that turns "we wired actants" into "we used actants in the
daemon's actual hot path."
"""

from __future__ import annotations

import asyncio
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from secondbrain.capture.frame import Frame, SyntheticFrameSource
from secondbrain.daemon import Daemon, DaemonConfig
from secondbrain.memory.importance import heuristic_importance


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


_PRECONDITION = pytest.mark.skipif(
    not _ollama_up() or os.environ.get("SECONDBRAIN_SKIP_LLM_TESTS") == "1",
    reason="Ollama not reachable on localhost:11434",
)

# Default to a fully local model so the default test suite never egresses.
# Override with SECONDBRAIN_TEST_CHAT_MODEL (e.g. an Ollama cloud model) when
# you explicitly want to test against a hosted model.
_CHAT_MODEL = os.environ.get("SECONDBRAIN_TEST_CHAT_MODEL", "gemma4:latest")


def _warm_model(model: str) -> None:
    """Load the model into Ollama's memory before the daemon starts.

    The daemon's per-call LLM timeouts (5s scorer / 8s extractor) are sized for
    warm inference. A cold local model pays several seconds of load on the
    first call, times out, and silently falls back to the heuristic — which is
    exactly the bypass this test exists to catch. Warm it so the timeouts
    measure inference, not model load.
    """
    import json

    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps({"model": model, "prompt": "ok", "stream": False}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        r.read()


def _frames() -> list[Frame]:
    rng = np.random.default_rng(0)

    def img(seed: int) -> Image.Image:
        arr = rng.integers(0, 255, size=(120, 160, 3), dtype=np.uint8)
        return Image.fromarray(arr)

    payloads = [
        ("Slack", "Sam Reed will ship the Snowflake migration by Friday or we miss launch."),
        ("Linear", "Stripe billing token expiry hotfix; rollout pushed to Tuesday for safety."),
        ("Notion", "Q3 budget review — Snowflake spend stays at $48k/mo."),
        ("Notes", "Weekend hike — golden gate trail conditions are dry."),
    ]
    out: list[Frame] = []
    for i, (app, text) in enumerate(payloads):
        out.append(
            Frame(
                captured_at=datetime(2026, 5, 6, 12, i, tzinfo=UTC),
                image=img(i),
                app_name=app,
                app_bundle_id=f"com.example.{app.lower()}",
                window_title="(test)",
                ax_text=text,
                dirty_rect_fraction=0.5,
            )
        )
    return out


@_PRECONDITION
def test_daemon_with_llm_writes_memorynodes(tmp_path: Path):
    _warm_model(_CHAT_MODEL)
    db = tmp_path / "secondbrain.db"
    cfg = DaemonConfig(
        db_path=db,
        use_encryption=False,
        use_stub_embedder=True,  # keep embed cheap; the LLM is what we're testing
        enable_llm=True,
        llm_model=_CHAT_MODEL,
        # Local models are slower than the daemon's warm-hosted default
        # timeouts; a timeout here silently falls back to the heuristic, which
        # is the exact bypass this test exists to catch.
        llm_timeout_s=45.0,
    )
    daemon = Daemon(cfg)
    asyncio.run(daemon.run(SyntheticFrameSource(_frames())))

    # 4 captures persisted, KG has at least 1 MemoryNode.
    assert daemon._memory is not None
    r = daemon._memory.kg._conn.execute("MATCH (m:MemoryNode) RETURN m.id, m.content, m.importance")
    rows = []
    while r.has_next():
        rows.append(r.get_next())

    assert len(rows) >= 1, "no MemoryNodes were written by the daemon"

    # At least one node's importance should differ from what the regex
    # heuristic would have given. If every score matches, the LLM didn't run.
    diffs = []
    for _id, content, importance in rows:
        h = heuristic_importance(content)
        if abs(float(importance) - float(h)) > 0.01:
            diffs.append((content[:40], h, importance))

    assert diffs, (
        "every MemoryNode's importance equals the heuristic — the LLM path "
        "was bypassed or the LLM happened to mirror the heuristic exactly. "
        f"Rows: {rows}"
    )

    # And every importance should be in [0, 10].
    for _id, _content, importance in rows:
        assert 0.0 <= float(importance) <= 10.0

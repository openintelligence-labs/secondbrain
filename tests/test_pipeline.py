from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import numpy as np
from PIL import Image

from secondbrain.capture.capability import CapabilityCache
from secondbrain.capture.dedup import DedupCascade
from secondbrain.capture.deny_list import DenyList
from secondbrain.capture.frame import Frame, SyntheticFrameSource, now
from secondbrain.capture.pipeline import CapturePipeline
from secondbrain.store import captures as captures_repo
from secondbrain.store.oltp import open_unencrypted


def _frame(seed: int, **kwargs) -> Frame:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, size=(120, 160, 3), dtype=np.uint8)
    base = {
        "captured_at": now(),
        "image": Image.fromarray(arr),
        "app_name": "TestApp",
        "app_bundle_id": "com.example.test",
        "window_title": "Hacker News",
        "ax_text": "test text",
        "dirty_rect_fraction": 0.5,
    }
    base.update(kwargs)
    return Frame(**base)


def _pipeline(conn: sqlite3.Connection) -> CapturePipeline:
    return CapturePipeline(
        deny=DenyList.from_defaults(),
        cascade=DedupCascade(),
        capability=CapabilityCache(conn),
        conn=conn,
    )


def test_pipeline_persists_distinct_frames(tmp_path: Path):
    conn = open_unencrypted(tmp_path / "p.db")
    pipe = _pipeline(conn)
    a = pipe.process_one(_frame(1))
    b = pipe.process_one(_frame(99))
    assert a is not None
    assert b is not None
    assert captures_repo.count(conn) == 2


def test_pipeline_skips_dhash_duplicate(tmp_path: Path):
    conn = open_unencrypted(tmp_path / "p.db")
    pipe = _pipeline(conn)
    f = _frame(7)
    assert pipe.process_one(f) is not None
    # Same image -> dHash gate should skip.
    f2 = _frame(7)
    assert pipe.process_one(f2) is None
    assert pipe.metrics.by_gate.get("dhash", 0) >= 1


def test_pipeline_skips_password_manager(tmp_path: Path):
    conn = open_unencrypted(tmp_path / "p.db")
    pipe = _pipeline(conn)
    f = _frame(2, app_name="1Password 8", window_title="All Vaults")
    out = pipe.process_one(f)
    assert out is None
    assert pipe.metrics.by_gate.get("deny_list", 0) == 1
    assert captures_repo.count(conn) == 0


def test_pipeline_skips_ax_unchanged(tmp_path: Path):
    conn = open_unencrypted(tmp_path / "p.db")
    pipe = _pipeline(conn)
    digest = b"x" * 32
    f = _frame(11, ax_text_digest=digest)
    assert pipe.process_one(f) is not None
    # Different image but same AX digest in same app → AX gate fires.
    f2 = _frame(12, ax_text_digest=digest)
    out = pipe.process_one(f2)
    assert out is None
    assert pipe.metrics.by_gate.get("ax_unchanged", 0) >= 1


def test_pipeline_async_drives_source(tmp_path: Path):
    conn = open_unencrypted(tmp_path / "p.db")
    pipe = _pipeline(conn)
    src = SyntheticFrameSource([_frame(i) for i in range(5)])

    async def collect() -> list:
        out = []
        async for cap in pipe.run(src):
            out.append(cap)
        return out

    captured = asyncio.run(collect())
    persisted = [c for c in captured if c is not None]
    assert len(persisted) >= 1
    assert pipe.metrics.seen == 5


def test_metrics_ax_ratio(tmp_path: Path):
    conn = open_unencrypted(tmp_path / "p.db")
    pipe = _pipeline(conn)
    pipe.process_one(_frame(1, ax_text="something"))
    pipe.process_one(_frame(99, ax_text=None))
    snap = pipe.metrics.as_dict()
    assert snap["persisted"] == 2
    # 1 of 2 had AX text → ratio 0.5
    assert snap["ax_text_ratio"] == 0.5

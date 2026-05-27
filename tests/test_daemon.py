"""Capture-cascade integration test.

Drives a SyntheticFrameSource through the daemon end-to-end (without
encryption, to keep CI portable). Asserts capture count + gate metrics
match expectations.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
from PIL import Image

from secondbrain.capture.frame import Frame, SyntheticFrameSource, now
from secondbrain.daemon import Daemon, DaemonConfig
from secondbrain.store import captures as captures_repo
from secondbrain.store.oltp import open_unencrypted


def _build_frames() -> list[Frame]:
    """A fixed sequence the cascade must classify in a known way:

    1. distinct noise A           → persist
    2. password-manager app        → deny_list skip
    3. distinct noise B            → persist
    4. exact duplicate of #3       → dhash skip
    5. tiny dirty-rect fraction    → dirty_rect skip
    6. distinct noise C            → persist
    """
    rng = np.random.default_rng(123)

    def noise(seed: int) -> Image.Image:
        arr = rng.integers(0, 255, size=(120, 160, 3), dtype=np.uint8)
        return Image.fromarray(arr)

    a, b, c = noise(1), noise(2), noise(3)
    # Real-prose ax_text so the memory pipeline's substantive-text gate
    # (`looks_substantive`) doesn't reject these as OCR confetti.
    return [
        Frame(
            captured_at=now(),
            image=a,
            app_name="Code",
            app_bundle_id="com.microsoft.VSCode",
            window_title="repo",
            ax_text="Refactored the auth module to use Argon2.",
            dirty_rect_fraction=0.5,
        ),
        Frame(
            captured_at=now(),
            image=noise(4),
            app_name="1Password 8",
            app_bundle_id="com.1password",
            window_title="All Vaults",
            dirty_rect_fraction=0.5,
        ),
        Frame(
            captured_at=now(),
            image=b,
            app_name="Code",
            app_bundle_id="com.microsoft.VSCode",
            window_title="repo",
            ax_text="Opened a PR with the Snowflake migration plan.",
            dirty_rect_fraction=0.5,
        ),
        Frame(
            captured_at=now(),
            image=b,
            app_name="Code",
            app_bundle_id="com.microsoft.VSCode",
            window_title="repo",
            ax_text="Opened a PR with the Snowflake migration plan.",
            dirty_rect_fraction=0.5,
        ),
        Frame(
            captured_at=now(),
            image=noise(5),
            app_name="Code",
            app_bundle_id="com.microsoft.VSCode",
            window_title="repo",
            ax_text="Reviewed Linda's pull request comments line by line.",
            dirty_rect_fraction=0.001,
        ),
        Frame(
            captured_at=now(),
            image=c,
            app_name="Code",
            app_bundle_id="com.microsoft.VSCode",
            window_title="repo",
            ax_text="Merged the dashboard branch after the e2e suite passed.",
            dirty_rect_fraction=0.5,
        ),
    ]


def test_cascade_60s_synthetic(tmp_path: Path):
    db = tmp_path / "daemon.db"
    cfg = DaemonConfig(
        db_path=db,
        use_encryption=False,
        use_stub_embedder=True,  # avoid the multi-GB Nomic v2 model download
    )
    daemon = Daemon(cfg)
    src = SyntheticFrameSource(_build_frames())
    asyncio.run(daemon.run(src))

    snap = daemon.metrics.as_dict()
    # 6 frames seen, 3 persisted (1, 3, 6), 1 deny, 1 dhash, 1 dirty_rect.
    assert snap["seen"] == 6
    assert snap["persisted"] == 3
    assert snap["by_gate"].get("deny_list") == 1
    assert snap["by_gate"].get("dirty_rect") == 1
    assert snap["by_gate"].get("dhash") == 1

    # And the DB matches.
    conn = open_unencrypted(db)
    assert captures_repo.count(conn) == 3


def test_daemon_populates_kg_and_search(tmp_path: Path):
    """Daemon runs the memory pipeline so KG + search are queryable end-to-end."""
    db = tmp_path / "daemon.db"
    cfg = DaemonConfig(db_path=db, use_encryption=False, use_stub_embedder=True)
    daemon = Daemon(cfg)
    src = SyntheticFrameSource(_build_frames())
    asyncio.run(daemon.run(src))

    # The daemon's own handles know the KG was populated.
    assert daemon._memory is not None
    r = daemon._memory.kg._conn.execute("MATCH (m:MemoryNode) RETURN count(m)")
    assert r.get_next()[0] >= 1

    # And captures land in LanceDB (count_rows is the simplest cross-version probe).
    assert daemon._indexer is not None
    assert daemon._indexer.vector.count() >= 1

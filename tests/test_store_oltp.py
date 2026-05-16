from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from secondbrain.models import Capture
from secondbrain.store import captures
from secondbrain.store.oltp import open_unencrypted


def test_round_trip_capture(tmp_path: Path):
    conn = open_unencrypted(tmp_path / "test.db")
    cap = Capture(
        id="01HZZZZZZZZZZZZZZZZZZZZZZZZZ",
        captured_at=datetime.now(timezone.utc),
        app_name="Code",
        app_bundle_id="com.microsoft.VSCode",
        window_title="README.md — secondbrain",
        ax_text="hello secondbrain",
        gate="persist",
        meta={"dirty_rect": 0.42},
    )
    captures.insert(conn, cap)
    assert captures.count(conn) == 1
    rows = list(captures.recent(conn))
    assert rows[0]["id"] == cap.id
    assert rows[0]["app_name"] == "Code"
    assert rows[0]["ax_text"] == "hello secondbrain"
    assert rows[0]["gate"] == "persist"

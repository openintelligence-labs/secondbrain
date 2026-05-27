from __future__ import annotations

import json
import time
from pathlib import Path

from secondbrain.capture.wearable.bee_import import import_jsonl as bee_import
from secondbrain.capture.wearable.limitless_import import (
    import_jsonl as limitless_import,
)
from secondbrain.capture.wearable.memorystream import (
    import_jsonl as ms_import,
)
from secondbrain.capture.wearable.memorystream import (
    record_to_capture,
)
from secondbrain.capture.wearable.omi_adapter import import_export as omi_import
from secondbrain.capture.wearable.plaud_adapter import import_export as plaud_import
from secondbrain.capture.wearable.rewind_import import import_export as rewind_import


def test_record_to_capture_minimal_transcript():
    cap = record_to_capture(
        {
            "type": "transcript",
            "ts": time.time(),
            "device": "test-dev",
            "sequence": 1,
            "speaker": "Sam",
            "text": "snowflake budget Q3",
        }
    )
    assert cap is not None
    assert cap.source == "wearable"
    assert "snowflake" in (cap.ax_text or "").lower()


def test_record_to_capture_rejects_far_future():
    cap = record_to_capture(
        {
            "type": "transcript",
            "ts": time.time() + 365 * 24 * 3600,  # 1 year in the future
            "device": "test",
            "text": "x",
        }
    )
    assert cap is None


def test_memorystream_jsonl_round_trip(tmp_path: Path):
    path = tmp_path / "in.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "transcript",
                "ts": time.time() - 10,
                "device": "test",
                "speaker": "self",
                "text": "hello",
            }
        )
        + "\n"
        + json.dumps(
            {"type": "event", "ts": time.time(), "device": "test", "kind": "battery", "value": 80}
        )
        + "\n"
    )
    caps = list(ms_import(path))
    assert len(caps) == 1


def test_plaud_adapter(tmp_path: Path):
    path = tmp_path / "p.json"
    path.write_text(
        json.dumps(
            {
                "created_at_unix": time.time() - 600,
                "transcripts": [
                    {"speaker": "Sam", "text": "Snowflake review.", "start": 0.0, "end": 2.0},
                    {"speaker": "Pat", "text": "Stripe billing.", "start": 2.5, "end": 5.0},
                ],
            }
        )
    )
    caps = list(plaud_import(path))
    assert len(caps) == 2
    assert all(c.app_name == "plaud-notepin-s" for c in caps)


def test_omi_adapter(tmp_path: Path):
    path = tmp_path / "o.json"
    path.write_text(
        json.dumps(
            {
                "created_at": time.time() - 100,
                "segments": [
                    {"speaker_id": "u-sam", "text": "ship by friday", "start": 0},
                    {"speaker_id": "u-pat", "text": "rollback plan", "start": 5},
                ],
            }
        )
    )
    caps = list(omi_import(path))
    assert len(caps) == 2


def test_limitless_orphan_import(tmp_path: Path):
    path = tmp_path / "lim.jsonl"
    path.write_text(
        "\n".join(json.dumps({"timestamp": time.time() - i, "text": f"line {i}"}) for i in range(3))
    )
    caps = list(limitless_import(path))
    assert len(caps) == 3


def test_bee_orphan_import(tmp_path: Path):
    path = tmp_path / "bee.jsonl"
    path.write_text(json.dumps({"created_at": time.time() - 60, "transcript": "Sam: hi"}) + "\n")
    caps = list(bee_import(path))
    assert len(caps) == 1
    assert caps[0].app_name == "bee-pendant"


def test_rewind_backup_import(tmp_path: Path):
    path = tmp_path / "rw.json"
    path.write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "started_at": time.time() - 1000,
                        "lines": [{"ts": time.time() - 1000, "text": "morning standup"}],
                    }
                ]
            }
        )
    )
    caps = list(rewind_import(path))
    assert len(caps) == 1
    assert caps[0].app_name == "rewind-mac"

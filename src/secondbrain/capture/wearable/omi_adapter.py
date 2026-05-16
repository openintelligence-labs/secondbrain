"""OMI / BasedHardware adapter."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from secondbrain.capture.wearable.memorystream import record_to_capture
from secondbrain.models import Capture

DEVICE_ID = "omi-v1"


def _to_records(omi_json: dict[str, Any]) -> Iterator[dict[str, Any]]:
    base_ts = float(omi_json.get("created_at", 0)) or 0.0
    for i, seg in enumerate(omi_json.get("segments", [])):
        yield {
            "type": "transcript",
            "ts": base_ts + float(seg.get("start", i)),
            "device": DEVICE_ID,
            "sequence": i,
            "speaker": seg.get("speaker_id") or "speaker",
            "text": seg.get("text", ""),
        }


def import_export(path: Path) -> Iterator[Capture]:
    data = json.loads(path.read_text())
    for rec in _to_records(data):
        cap = record_to_capture(rec)
        if cap is not None:
            yield cap

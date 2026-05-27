"""Plaud Note Pro / NotePin S adapter.

Plaud's export ships a JSON manifest per recording with `transcripts`,
`speakers`, `created_at`. We map straight to MemoryStream `transcript`
records, then through `record_to_capture`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from secondbrain.capture.wearable.memorystream import record_to_capture
from secondbrain.models import Capture

DEVICE_ID = "plaud-notepin-s"


def _to_records(plaud_json: dict[str, Any]) -> Iterator[dict[str, Any]]:
    base_ts = float(plaud_json.get("created_at_unix", 0)) or 0.0
    for i, seg in enumerate(plaud_json.get("transcripts", [])):
        yield {
            "type": "transcript",
            "ts": base_ts + float(seg.get("start", i)),
            "device": DEVICE_ID,
            "sequence": i,
            "speaker": seg.get("speaker") or "speaker",
            "text": seg.get("text", ""),
            "start_ms": int(float(seg.get("start", 0)) * 1000),
            "end_ms": int(float(seg.get("end", 0)) * 1000),
        }


def import_export(path: Path) -> Iterator[Capture]:
    data = json.loads(path.read_text())
    for rec in _to_records(data):
        cap = record_to_capture(rec)
        if cap is not None:
            yield cap

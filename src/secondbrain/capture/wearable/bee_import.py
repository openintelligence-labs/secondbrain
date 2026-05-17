"""Bee orphaned-data importer."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from secondbrain.capture.wearable.memorystream import record_to_capture
from secondbrain.models import Capture

DEVICE_ID = "bee-pendant"


def import_jsonl(path: Path) -> Iterator[Capture]:
    with path.open() as f:
        for i, raw in enumerate(f):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            text = row.get("transcript") or row.get("text")
            ts = row.get("created_at") or row.get("ts")
            if not (text and ts):
                continue
            cap = record_to_capture(
                {
                    "type": "transcript",
                    "ts": float(ts),
                    "device": DEVICE_ID,
                    "sequence": i,
                    "speaker": row.get("speaker") or "self",
                    "text": text,
                }
            )
            if cap is not None:
                yield cap

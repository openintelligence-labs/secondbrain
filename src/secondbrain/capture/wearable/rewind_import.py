"""Rewind.ai backup importer.

Rewind shipped as a SQLite-backed app; their published export format is JSON
per session. Same shape as the others — we accept either JSONL or a single
JSON document with a `sessions` field.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from secondbrain.capture.wearable.memorystream import record_to_capture
from secondbrain.models import Capture

DEVICE_ID = "rewind-mac"


def import_export(path: Path) -> Iterator[Capture]:
    text = path.read_text()
    try:
        data = json.loads(text)
        sessions = data.get("sessions", [])
        for i, sess in enumerate(sessions):
            for j, line in enumerate(sess.get("lines", [])):
                cap = record_to_capture(
                    {
                        "type": "transcript",
                        "ts": float(line.get("ts", sess.get("started_at", 0))),
                        "device": DEVICE_ID,
                        "sequence": i * 10000 + j,
                        "speaker": line.get("speaker") or "self",
                        "text": line.get("text", ""),
                    }
                )
                if cap is not None:
                    yield cap
    except json.JSONDecodeError:
        # Fallback: treat as JSONL.
        with path.open() as f:
            for i, raw in enumerate(f):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                cap = record_to_capture(
                    {
                        "type": "transcript",
                        "ts": float(row.get("ts", 0)),
                        "device": DEVICE_ID,
                        "sequence": i,
                        "speaker": row.get("speaker") or "self",
                        "text": row.get("text", ""),
                    }
                )
                if cap is not None:
                    yield cap

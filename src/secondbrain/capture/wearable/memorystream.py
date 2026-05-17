"""MemoryStream v1 record → Capture mapping.

Open wearable-import format. The receiver accepts JSONL records over BLE,
HTTP, or file and yields `Capture` objects. Schema is documented inline at
`MemoryStreamRecord` below.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from secondbrain.models import Capture

CLOCK_SKEW_SECONDS = 30 * 24 * 3600


def _now() -> datetime:
    return datetime.now(UTC)


def record_to_capture(record: dict[str, Any]) -> Capture | None:
    rtype = record.get("type")
    ts = record.get("ts")
    device = record.get("device")
    if rtype is None or ts is None or device is None:
        return None
    captured_at = datetime.fromtimestamp(float(ts), tz=UTC)
    if captured_at - _now() > timedelta(seconds=CLOCK_SKEW_SECONDS):
        return None  # spec conformance: refuse impossible-future records

    if rtype == "transcript":
        text = record.get("text", "").strip()
        if not text:
            return None
        return Capture(
            id=f"wearable:{device}:{record.get('sequence', int(float(ts) * 1000))}",
            source="wearable",
            captured_at=captured_at,
            app_name=device,
            app_bundle_id=f"vendor.{device}",
            window_title=record.get("title"),
            ax_text=f"{record.get('speaker', '')}: {text}".strip(": "),
        )
    if rtype == "frame_audio":
        # Audio frames are persisted as Capture rows with no AX/OCR text;
        # an STT pipeline plugs in later to fill ax_text.
        return Capture(
            id=f"wearable:{device}:audio:{record.get('sequence', int(float(ts) * 1000))}",
            source="wearable",
            captured_at=captured_at,
            app_name=device,
            ax_text=None,
        )
    if rtype == "event":
        # Skip device-health events; not memory-relevant.
        return None
    return None


def import_jsonl(path: Path) -> Iterator[Capture]:
    """Import a flat JSONL archive — used for orphaned-vendor data."""
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            cap = record_to_capture(rec)
            if cap is not None:
                yield cap

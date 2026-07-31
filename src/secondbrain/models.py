"""Pydantic models shared across module boundaries."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

CaptureSource = Literal["screen", "audio", "browser", "document", "clipboard", "wearable", "note"]


class Capture(BaseModel):
    """A single observation persisted to the timeline.

    All sources share this schema so retrieval and KG layers stay
    source-agnostic.
    """

    id: str
    source: CaptureSource = "screen"
    captured_at: datetime
    app_name: str | None = None
    app_bundle_id: str | None = None
    window_title: str | None = None
    url: str | None = None
    file_path: Path | None = None
    ax_text: str | None = None
    ocr_text: str | None = None
    text_hash: bytes | None = None
    pixel_hash: bytes | None = None
    pixel_path: Path | None = None
    sensitive: bool = False
    redacted: bool = False
    monitor_index: int | None = None
    capability_cache_hit: bool = False
    # Which cascade gate emitted this capture.
    gate: str = "persist"
    # Free-form per-source metadata (eg. dirty-rect fraction, dHash distance).
    meta: dict[str, str | int | float | bool] = Field(default_factory=dict)

"""The capture cascade — orchestrates gates and emits Capture rows.

Order (cheapest first):

    deny_list → ax_unchanged → dirty_rect → dHash → pHash → SSIM → persist

This module owns no I/O concerns: it consumes `Frame` objects, emits `Capture`
rows, and delegates persistence + capability tracking to its collaborators.
That makes it trivially unit-testable.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4

from secondbrain.capture.capability import CapabilityCache
from secondbrain.capture.dedup import Decision, DedupCascade
from secondbrain.capture.deny_list import DenyList
from secondbrain.capture.frame import Frame, FrameSource
from secondbrain.models import Capture
from secondbrain.store import captures as captures_repo

GateName = Literal[
    "deny_list",
    "ax_unchanged",
    "dirty_rect",
    "dhash",
    "phash",
    "ssim",
    "persist",
]


@dataclass
class CascadeMetrics:
    """Counters for `secondbrain status`."""

    seen: int = 0
    persisted: int = 0
    by_gate: dict[str, int] = field(default_factory=dict)
    ax_text_present: int = 0  # for AX-vs-OCR ratio
    paused: bool = False  # set via /daemon control endpoint

    def hit(self, gate: GateName) -> None:
        self.by_gate[gate] = self.by_gate.get(gate, 0) + 1

    def as_dict(self) -> dict:
        ax_ratio = self.ax_text_present / self.persisted if self.persisted else 0.0
        return {
            "seen": self.seen,
            "persisted": self.persisted,
            "by_gate": dict(self.by_gate),
            "ax_text_ratio": round(ax_ratio, 3),
            "paused": self.paused,
        }


@dataclass
class CapturePipeline:
    """Orchestrates the cascade. One pipeline per running daemon."""

    deny: DenyList
    cascade: DedupCascade
    capability: CapabilityCache
    conn: sqlite3.Connection
    metrics: CascadeMetrics = field(default_factory=CascadeMetrics)
    # Track previous AX digest per (bundle_id, app_name) to skip unchanged.
    _prev_ax_digest: dict[tuple[str, str], bytes] = field(default_factory=dict)

    async def run(self, source: FrameSource) -> AsyncIterator[Capture | None]:
        """Stream captures (None when a frame is gated). Caller decides what to
        log — useful for the integration test."""
        async for frame in source.stream():
            yield self._process(frame)

    def process_one(self, frame: Frame) -> Capture | None:
        """Synchronous entry point used by tests."""
        return self._process(frame)

    def _process(self, frame: Frame) -> Capture | None:
        self.metrics.seen += 1
        if self.metrics.paused:
            # When paused, count seen frames but skip every gate beyond this
            # — gives users an instant kill-switch from the UI/tray.
            self.metrics.hit("paused")
            return None

        # Gate 1 — window-title deny-list (0 ms)
        denied, _reason = self.deny.decide(
            frame.app_name,
            frame.window_title,
            frame.app_bundle_id,
        )
        if denied:
            self.metrics.hit("deny_list")
            return None

        # Gate 2 — AX-tree unchanged
        ax_key = (frame.app_bundle_id or "", frame.app_name or "")
        if frame.ax_text_digest is not None:
            prev = self._prev_ax_digest.get(ax_key)
            if prev is not None and prev == frame.ax_text_digest:
                self.metrics.hit("ax_unchanged")
                return None
            self._prev_ax_digest[ax_key] = frame.ax_text_digest

        # Gates 3-6 — dirty-rect / dHash / pHash / SSIM
        decision: Decision = self.cascade.evaluate(
            frame.image,
            dirty_rect_fraction=frame.dirty_rect_fraction,
        )
        if not decision.persist:
            self.metrics.hit(decision.gate)
            return None

        # Track per-app AX capability based on whether the source produced
        # ax_text for this frame.
        if frame.app_bundle_id and frame.app_name:
            self.capability.record(
                frame.app_bundle_id,
                frame.app_name,
                ax_text_present=bool(frame.ax_text),
            )

        capture = Capture(
            id=uuid4().hex,
            captured_at=frame.captured_at,
            app_name=frame.app_name,
            app_bundle_id=frame.app_bundle_id,
            window_title=frame.window_title,
            url=frame.url,
            ax_text=frame.ax_text,
            monitor_index=frame.monitor_index,
            gate="persist",
            meta={
                "dirty_rect_fraction": frame.dirty_rect_fraction
                if frame.dirty_rect_fraction is not None
                else -1.0,
            },
        )
        captures_repo.insert(self.conn, capture)
        self.metrics.persisted += 1
        self.metrics.hit("persist")
        if frame.ax_text:
            self.metrics.ax_text_present += 1
        # Stash the PIL image so downstream visual-embed can fetch it without
        # mutating the Pydantic model. Cleared by the consumer after use.
        _IMAGE_FOR_VISUAL[capture.id] = frame.image
        return capture


# Tiny sidecar map — capture_id → PIL.Image for the visual-embed path.
# Daemon pops entries after encoding; entries here are never persisted.
_IMAGE_FOR_VISUAL: dict[str, object] = {}


def take_image_for_visual(capture_id: str):
    return _IMAGE_FOR_VISUAL.pop(capture_id, None)


def started_at(_frame: Frame | None = None) -> datetime:
    """Tiny indirection so tests can monkey-patch time if they need to."""
    from secondbrain.capture.frame import now

    return now()

"""Frame source protocol — the interface every capture backend implements.

A `FrameSource` yields `Frame` objects asynchronously. Backends:

- `SyntheticFrameSource` — deterministic, used by the integration test.
- `MacOSScreenSource`    — Swift-sidecar-backed.
- (later) `WindowsScreenSource`, `LinuxScreenSource`.

Keeping the interface tiny means the cascade and persistence layers don't care
where the frame came from.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from PIL import Image


@dataclass(slots=True)
class Frame:
    """A single capture opportunity flowing through the cascade.

    `dirty_rect_fraction` comes from the source (SCK / WGC) when available; if
    None, the cascade will not invoke the dirty-rect gate.
    """

    captured_at: datetime
    image: Image.Image
    monitor_index: int = 0
    app_name: str | None = None
    app_bundle_id: str | None = None
    window_title: str | None = None
    url: str | None = None
    dirty_rect_fraction: float | None = None
    # Backends can attach raw text already extracted by the OS (eg. AX-tree)
    # so the cascade can short-circuit before pixel work.
    ax_text: str | None = None
    ax_text_digest: bytes | None = None
    extras: dict = field(default_factory=dict)


class FrameSource(Protocol):
    """Async iterator of frames. Backends MUST be cancel-safe."""

    def stream(self) -> AsyncIterator[Frame]: ...
    async def close(self) -> None: ...


class SyntheticFrameSource:
    """Test/dev frame source. Yields a fixed list of frames once."""

    def __init__(self, frames: list[Frame]) -> None:
        self._frames = frames

    async def stream(self) -> AsyncIterator[Frame]:
        for f in self._frames:
            yield f

    async def close(self) -> None:
        return None


class LoopingSyntheticSource:
    """Demo/dev frame source for the Tauri UI.

    Wraps a fixed list of frame *templates* and yields them on a steady
    cadence forever (or until `close()` is called). The captured_at
    timestamp is refreshed on every yield so cascade dedup decisions are
    realistic and the timeline shows movement.

    This is the default behind `secondbrain ui` so the UI has live data
    without ScreenCaptureKit / TCC permission.
    """

    def __init__(self, templates: list[Frame], interval_s: float = 1.0) -> None:
        if not templates:
            raise ValueError("templates must be non-empty")
        self._templates = templates
        self._interval_s = interval_s
        self._closed = False

    async def stream(self) -> AsyncIterator[Frame]:
        import asyncio as _aio

        i = 0
        while not self._closed:
            tmpl = self._templates[i % len(self._templates)]
            i += 1
            # Fresh timestamp each yield so dirty-rect / dedup gates see new
            # events and the timeline UI shows progression.
            yield Frame(
                captured_at=now(),
                image=tmpl.image,
                monitor_index=tmpl.monitor_index,
                app_name=tmpl.app_name,
                app_bundle_id=tmpl.app_bundle_id,
                window_title=f"{tmpl.window_title or 'demo'} #{i}",
                url=tmpl.url,
                dirty_rect_fraction=tmpl.dirty_rect_fraction,
                ax_text=tmpl.ax_text,
                ax_text_digest=None,
                extras=dict(tmpl.extras),
            )
            await _aio.sleep(self._interval_s)

    async def close(self) -> None:
        self._closed = True


def now() -> datetime:
    return datetime.now(timezone.utc)

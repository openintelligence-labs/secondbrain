"""Linux PipeWire FrameSource (skeleton).

Architecture: xdg-desktop-portal ScreenCast with `persist_mode=2` and stored
`RestoreToken`. Negotiate DMA-BUF with modifiers; fall back to MemFd+SHM for
older compositors.

The Python integration uses `dasbus` for the portal D-Bus calls and a small
GStreamer pipeline (`gst-python`) to consume the resulting PipeWire stream.

This module currently ships the interface; the GStreamer + RestoreToken loop
lands later.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator

from secondbrain.capture.frame import Frame, FrameSource

_NEEDS_GST = "Linux capture requires gst-python + dasbus + xdg-desktop-portal."


class LinuxScreenSource(FrameSource):
    def __init__(self, *, fps: int = 1, display_index: int = 0, max_frames: int = -1) -> None:
        if not sys.platform.startswith("linux"):
            raise RuntimeError("LinuxScreenSource: not on linux")
        raise NotImplementedError(_NEEDS_GST)

    async def stream(self) -> AsyncIterator[Frame]:  # pragma: no cover
        raise NotImplementedError(_NEEDS_GST)
        yield  # type: ignore[unreachable]

    async def close(self) -> None:  # pragma: no cover
        return None

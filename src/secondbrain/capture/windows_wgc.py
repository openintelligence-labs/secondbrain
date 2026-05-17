"""Windows.Graphics.Capture FrameSource (skeleton).

Goal: parity with macOS via the `windows-capture` Rust crate (NiiightmareXD)
exposed to Python through PyO3. The Rust binding is the cleanest path to
WGC + DXGI fallback per the architecture's research.

This module currently ships the *interface*; the PyO3 build pipeline lands
later against a real Windows runner. Until then, importing this module on
Windows raises `NotImplementedError` with a precise pointer.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator

from secondbrain.capture.frame import Frame, FrameSource

_NEEDS_PYO3 = "Windows capture requires the windows-capture Rust crate compiled with PyO3 bindings."


class WindowsScreenSource(FrameSource):
    def __init__(self, *, fps: int = 1, display_index: int = 0, max_frames: int = -1) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsScreenSource: not on win32")
        raise NotImplementedError(_NEEDS_PYO3)

    async def stream(self) -> AsyncIterator[Frame]:  # pragma: no cover
        raise NotImplementedError(_NEEDS_PYO3)
        yield  # type: ignore[unreachable]

    async def close(self) -> None:  # pragma: no cover
        return None

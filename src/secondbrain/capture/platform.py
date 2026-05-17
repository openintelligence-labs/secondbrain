"""Platform dispatch.

Returns a `FrameSource` for the running OS or raises a clear error.

This module lands the dispatch surface; the heavy native impls
(windows-capture + PipeWire) ship later once we run on real Windows / Linux
hardware. The NotImplementedError messages tell users exactly which path
needs to be exercised.
"""

from __future__ import annotations

import sys
from pathlib import Path

from secondbrain.capture.frame import FrameSource


def make_screen_source(
    *,
    pixel_mode: str = "png",
    frame_dir: Path | None = None,
    fps: int = 1,
    display_index: int = 0,
    max_frames: int = -1,
) -> FrameSource:
    if sys.platform == "darwin":
        from secondbrain.capture.macos_sck import MacOSScreenSource

        return MacOSScreenSource(
            pixel_mode=pixel_mode,
            frame_dir=frame_dir,
            fps=fps,
            display_index=display_index,
            max_frames=max_frames,
        )

    if sys.platform == "win32":
        try:
            from secondbrain.capture.windows_wgc import WindowsScreenSource
        except Exception as e:  # pragma: no cover
            raise NotImplementedError(
                "Windows capture is stubbed. Build the windows-capture "
                "Rust crate via PyO3; see capture/windows_wgc.py."
            ) from e
        return WindowsScreenSource(fps=fps, display_index=display_index, max_frames=max_frames)

    if sys.platform.startswith("linux"):
        try:
            from secondbrain.capture.linux_pw import LinuxScreenSource
        except Exception as e:  # pragma: no cover
            raise NotImplementedError(
                "Linux capture is stubbed. Wire xdg-desktop-portal "
                "ScreenCast with persistent RestoreToken; see "
                "capture/linux_pw.py."
            ) from e
        return LinuxScreenSource(fps=fps, display_index=display_index, max_frames=max_frames)

    raise RuntimeError(f"unsupported platform: {sys.platform}")

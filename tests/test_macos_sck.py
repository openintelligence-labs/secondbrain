"""macOS-only smoke test of the Swift sidecar bridge.

Runs only on darwin and only when the sidecar binary is present. Drives the
sidecar at 1 fps with --max-frames=2 and asserts the bridge yields valid
`Frame` objects with a non-empty image.

This test exercises the real ScreenCaptureKit path, so it requires Screen
Recording permission. CI runs on macOS GHA runners with permission denied;
expect the test to be SKIPPED there. Locally it should pass once you accept
the TCC prompt.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

if sys.platform != "darwin":
    pytest.skip("macOS-only test", allow_module_level=True)

from secondbrain.capture.macos_sck import MacOSScreenSource, _default_sidecar_path


def _sidecar_available() -> bool:
    try:
        return _default_sidecar_path().exists()
    except FileNotFoundError:
        return False


@pytest.mark.skipif(
    not _sidecar_available(),
    reason="Swift sidecar not built; cd swift/SecondBrainCapture && swift build -c release",
)
@pytest.mark.skipif(
    os.environ.get("SECONDBRAIN_SKIP_SCK_TEST") == "1",
    reason="Set SECONDBRAIN_SKIP_SCK_TEST=1 to skip (eg. headless CI without TCC)",
)
def test_sidecar_yields_frames():
    src = MacOSScreenSource(pixel_mode="png", fps=2, max_frames=2, max_restarts=0)

    async def collect():
        out = []
        async for frame in src.stream():
            out.append(frame)
            if len(out) >= 2:
                break
        await src.close()
        return out

    frames = asyncio.run(asyncio.wait_for(collect(), timeout=20))
    assert len(frames) == 2
    for f in frames:
        assert f.image.width > 0
        assert f.image.height > 0

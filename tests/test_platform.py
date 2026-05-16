"""Platform dispatch surface."""
from __future__ import annotations

import sys

import pytest

from secondbrain.capture.platform import make_screen_source


def test_dispatch_yields_source_or_raises_clearly():
    if sys.platform == "darwin":
        src = make_screen_source(fps=1, max_frames=1)
        assert src is not None
    elif sys.platform == "win32":
        with pytest.raises((NotImplementedError, RuntimeError)):
            make_screen_source(fps=1, max_frames=1)
    elif sys.platform.startswith("linux"):
        with pytest.raises((NotImplementedError, RuntimeError)):
            make_screen_source(fps=1, max_frames=1)
    else:
        with pytest.raises(RuntimeError):
            make_screen_source(fps=1, max_frames=1)

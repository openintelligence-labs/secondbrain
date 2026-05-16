"""Windows UIA3 AX walker (skeleton)."""
from __future__ import annotations

import sys

_MSG = (
    "Windows AX requires the `uiautomation` Python package on Windows; "
    "CacheRequest batching to be wired."
)


def snapshot_focused_app(*_args, **_kwargs):
    if sys.platform != "win32":
        raise RuntimeError("ax_windows: not on win32")
    raise NotImplementedError(_MSG)

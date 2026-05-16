"""Linux AT-SPI2 AX walker (skeleton)."""
from __future__ import annotations

import sys

_MSG = (
    "Linux AX requires the `atspi` Python package. Coverage "
    "expected to be GTK/Qt only — Electron-on-Wayland may need OCR fallback."
)


def snapshot_focused_app(*_args, **_kwargs):
    if not sys.platform.startswith("linux"):
        raise RuntimeError("ax_linux: not on linux")
    raise NotImplementedError(_MSG)

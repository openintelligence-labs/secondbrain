"""Windows.Media.Ocr wrapper (skeleton)."""

from __future__ import annotations

import sys
from pathlib import Path

_MSG = "Windows.Media.Ocr requires winrt-Windows.Media.Ocr."


def ocr_image(image_path: Path):
    if sys.platform != "win32":
        raise RuntimeError("windows_ocr: not on win32")
    raise NotImplementedError(_MSG)

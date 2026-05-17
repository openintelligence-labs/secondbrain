"""Apple Vision sidecar + selector.

Renders a known string with PIL, runs the sidecar, asserts text contains
the rendered string. macOS-only; skipped if the sidecar isn't built.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

if sys.platform != "darwin":
    pytest.skip("macOS-only", allow_module_level=True)

from secondbrain.ocr.apple_vision import _default_ocr_path, aocr_image
from secondbrain.ocr.selector import aselect_text


def _sidecar_available() -> bool:
    try:
        return _default_ocr_path().exists()
    except FileNotFoundError:
        return False


def _render(text: str, path: Path) -> None:
    img = Image.new("RGB", (640, 200), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except Exception:
        font = ImageFont.load_default()
    draw.text((40, 70), text, fill=(0, 0, 0), font=font)
    img.save(path)


@pytest.mark.skipif(
    not _sidecar_available(),
    reason="Swift OCR sidecar not built",
)
@pytest.mark.skipif(
    os.environ.get("SECONDBRAIN_SKIP_VISION_TEST") == "1",
    reason="Vision test skipped via env",
)
def test_apple_vision_reads_rendered_text(tmp_path: Path):
    img_path = tmp_path / "hello.png"
    _render("Hello SecondBrain Apple Vision", img_path)
    result = asyncio.run(aocr_image(img_path))
    assert result is not None
    assert "SecondBrain" in result.text or "Apple Vision" in result.text


@pytest.mark.skipif(
    not _sidecar_available(),
    reason="Swift OCR sidecar not built",
)
def test_selector_prefers_ax_text(tmp_path: Path):
    out = asyncio.run(aselect_text(ax_text="hello from accessibility", image_path=None))
    assert out.provider == "ax"
    assert out.text == "hello from accessibility"


@pytest.mark.skipif(
    not _sidecar_available(),
    reason="Swift OCR sidecar not built",
)
def test_selector_falls_back_to_apple_vision(tmp_path: Path):
    img_path = tmp_path / "hello.png"
    _render("Hybrid retrieval works", img_path)
    out = asyncio.run(aselect_text(ax_text=None, image_path=img_path))
    assert out.provider == "apple_vision"
    assert "Hybrid" in out.text or "retrieval" in out.text or "works" in out.text

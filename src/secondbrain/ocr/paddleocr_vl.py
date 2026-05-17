"""PaddleOCR-VL fallback (skeleton).

Selected during initial research as the SOTA OCR for dense pages
(#1 OmniDocBench v1.5 = 90.67, beats GPT-4o, Apache-2.0). Used as last-resort
fallback when native OCR returns low confidence on a visually-rich frame.

This module currently ships the interface; the actual model loader lands
later because the VL model is ~3GB and we don't want to make every install
pull it.
"""

from __future__ import annotations

from pathlib import Path

_MSG = (
    "PaddleOCR-VL requires `paddlepaddle` + `paddleocr-vl`; ~3GB weights. "
    "Plan to wire as an opt-in install extra: `pip install secondbrain[ocr-vl]`."
)


def ocr_image(image_path: Path):
    raise NotImplementedError(_MSG)

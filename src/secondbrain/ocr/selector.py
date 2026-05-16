"""OCR escalation policy.

    AX text → use it (free, structured, often best)
       │
       ▼ AX empty
    native OS OCR (Apple Vision / Win.Media.Ocr) → use if confidence >= threshold
       │
       ▼ confidence < threshold AND content is dense
    PaddleOCR-VL 0.9B  (needs GPU on Linux/Win, optional on mac)

This module owns the policy; backends own the work.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

OCRProvider = Literal["ax", "apple_vision", "windows_ocr", "paddleocr_vl", "none"]

NATIVE_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class OCROutcome:
    provider: OCRProvider
    text: str
    confidence: float = 1.0
    used_fallback: bool = False


async def aselect_text(
    *,
    ax_text: str | None,
    image_path: Path | None,
) -> OCROutcome:
    """Run the escalation policy. AX wins → native → fallback."""
    if ax_text and ax_text.strip():
        return OCROutcome(provider="ax", text=ax_text, confidence=1.0)

    if image_path is None:
        return OCROutcome(provider="none", text="", confidence=0.0)

    if sys.platform == "darwin":
        from secondbrain.ocr.apple_vision import aocr_image

        result = await aocr_image(image_path)
        if result and result.confidence_avg >= NATIVE_CONFIDENCE_THRESHOLD:
            return OCROutcome(
                provider="apple_vision",
                text=result.text,
                confidence=result.confidence_avg,
            )
        if result:
            # Below threshold — emit anyway but flag as low confidence so the
            # downstream pipeline can decide to re-run with PaddleOCR-VL later.
            return OCROutcome(
                provider="apple_vision",
                text=result.text,
                confidence=result.confidence_avg,
                used_fallback=True,
            )

    # Windows/Linux native OCR + PaddleOCR-VL fallback to be wired later.
    return OCROutcome(provider="none", text="", confidence=0.0)

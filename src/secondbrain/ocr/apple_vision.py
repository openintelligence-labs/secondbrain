"""Bridge to the `secondbrain-ocr` Swift sidecar (Apple Vision)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger()


def _default_ocr_path() -> Path:
    if env := os.environ.get("SECONDBRAIN_OCR_BIN"):
        return Path(env)
    repo_root = Path(__file__).resolve().parents[3]
    candidate = (
        repo_root / "swift" / "SecondBrainCapture" / ".build" / "release" / "secondbrain-ocr"
    )
    if candidate.exists():
        return candidate
    on_path = shutil.which("secondbrain-ocr")
    if on_path:
        return Path(on_path)
    raise FileNotFoundError("secondbrain-ocr binary not found")


@dataclass
class OCRResult:
    text: str
    confidence_avg: float
    n_lines: int = 0


async def aocr_image(image_path: Path) -> OCRResult | None:
    """Run Apple Vision on a path. Returns None if the sidecar errored."""
    if sys.platform != "darwin":
        return None
    try:
        binary = _default_ocr_path()
    except FileNotFoundError as e:
        log.warning("ocr.binary_missing", err=str(e))
        return None

    proc = await asyncio.create_subprocess_exec(
        str(binary),
        str(image_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await proc.communicate()
    if proc.returncode != 0:
        log.warning("ocr.exit_nonzero", rc=proc.returncode)
        return None

    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "ocr":
            return OCRResult(
                text=event.get("text", ""),
                confidence_avg=float(event.get("confidence_avg", 0.0)),
                n_lines=int(event.get("n_lines", 0)),
            )
    return None


def ocr_image(image_path: Path) -> OCRResult | None:
    return asyncio.run(aocr_image(image_path))

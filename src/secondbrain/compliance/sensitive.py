"""Sensitive-content classifier (skeleton).

Architecture's two-stage filter:
   1. Florence-2-base classifier (~80ms binary) — is this frame sensitive?
   2. Moondream-3 — generate a redaction mask when stage 1 is positive.

Today we ship the *interface* and a heuristic baseline that uses our
existing window-title deny-list output: any frame whose pre-cascade
deny-list match was triggered is flagged sensitive. The heavy VLMs plug in
behind `set_classifier()` later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass
class SensitiveDecision:
    is_sensitive: bool
    reason: str
    confidence: float = 1.0


class SensitiveClassifier(Protocol):
    def classify(self, image: Image.Image, *, hint: str = "") -> SensitiveDecision: ...


class HeuristicClassifier:
    """No-VLM baseline — returns is_sensitive=True only when caller passes a hint."""

    def classify(self, image: Image.Image, *, hint: str = "") -> SensitiveDecision:
        if hint:
            return SensitiveDecision(is_sensitive=True, reason=f"hint:{hint}", confidence=0.95)
        return SensitiveDecision(is_sensitive=False, reason="default", confidence=0.5)


_classifier: SensitiveClassifier = HeuristicClassifier()


def set_classifier(c: SensitiveClassifier) -> None:
    global _classifier
    _classifier = c


def classify(image: Image.Image, hint: str = "") -> SensitiveDecision:
    return _classifier.classify(image, hint=hint)

"""Sensitive-content classifier interface.

Two-stage filter:
   1. Florence-2-base classifier (~150ms p95) — does the frame show
      sensitive content (password field, OTP, card, SSN, medical)?
   2. (deferred) Moondream-3 mask generation when stage 1 is positive.

Today this module ships the Protocol and a heuristic baseline. The
Florence-backed implementation lands behind the `[redact]` extra in a
follow-up PR and plugs in via `set_classifier()`.
"""

from __future__ import annotations

from typing import Literal, Protocol

from PIL import Image
from pydantic import BaseModel, Field

SensitiveCategory = Literal[
    "password_field",
    "otp_code",
    "card_number",
    "ssn",
    "medical_record",
    "unknown",
]


class SensitiveDecision(BaseModel):
    is_sensitive: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    categories: list[SensitiveCategory] = Field(default_factory=list)
    model: str = "heuristic"
    latency_ms: int | None = None

    @property
    def reason(self) -> str:
        """Human-readable summary derived from categories.

        Kept as a property so existing call sites that did
        `decision.reason` keep working.
        """
        if not self.is_sensitive:
            return "clean"
        return ",".join(self.categories) if self.categories else "unknown"


class SensitiveClassifier(Protocol):
    def classify(
        self,
        image: Image.Image,
        *,
        hint: str = "",
        timeout_ms: int = 250,
    ) -> SensitiveDecision: ...


class HeuristicClassifier:
    """No-VLM baseline. Flags sensitive only when a hint is supplied.

    Used as the default before `[redact]` is installed and as the test
    double in the cascade gate tests.
    """

    def classify(
        self,
        image: Image.Image,
        *,
        hint: str = "",
        timeout_ms: int = 250,
    ) -> SensitiveDecision:
        if hint:
            return SensitiveDecision(
                is_sensitive=True,
                confidence=0.95,
                categories=["unknown"],
                model="heuristic",
            )
        return SensitiveDecision(
            is_sensitive=False,
            confidence=0.5,
            categories=[],
            model="heuristic",
        )


_classifier: SensitiveClassifier = HeuristicClassifier()


def set_classifier(c: SensitiveClassifier) -> None:
    global _classifier
    _classifier = c


def get_classifier() -> SensitiveClassifier:
    """Return the currently registered classifier instance."""
    return _classifier


def classify(
    image: Image.Image,
    hint: str = "",
    timeout_ms: int = 250,
) -> SensitiveDecision:
    return _classifier.classify(image, hint=hint, timeout_ms=timeout_ms)

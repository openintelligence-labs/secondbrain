"""Sensitive-content redaction gate in the dedup cascade, with no model loaded."""

from __future__ import annotations

import numpy as np
from PIL import Image

from secondbrain.capture.dedup import CascadeThresholds, Decision, DedupCascade
from secondbrain.compliance.sensitive import (
    HeuristicClassifier,
    SensitiveDecision,
)


def _img(seed: int, size: int = 64) -> Image.Image:
    """A deterministic noise frame, far in Hamming distance from any other seed."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
    return Image.fromarray(arr)


class _AlwaysSensitive:
    """Flags every frame at the given confidence."""

    def __init__(self, confidence: float = 0.9, categories=("password_field",)) -> None:
        self.confidence = confidence
        self.categories = list(categories)
        self.calls = 0

    def classify(self, image, *, hint="", timeout_ms=250) -> SensitiveDecision:
        self.calls += 1
        return SensitiveDecision(
            is_sensitive=True,
            confidence=self.confidence,
            categories=self.categories,
            model="test-always-sensitive",
        )


class _NeverSensitive:
    """Never flags a frame."""

    def __init__(self) -> None:
        self.calls = 0

    def classify(self, image, *, hint="", timeout_ms=250) -> SensitiveDecision:
        self.calls += 1
        return SensitiveDecision(
            is_sensitive=False,
            confidence=0.1,
            categories=[],
            model="test-never-sensitive",
        )


def test_classifier_none_means_no_redact_gate():
    """A cascade built without `classifier=` matches pre-redaction behavior."""
    cascade = DedupCascade()
    d = cascade.evaluate(_img(1))
    assert d.persist is True
    assert d.gate == "persist"
    assert d.redaction is None


def test_classifier_not_called_when_deny_list_short_circuits_upstream():
    """The deny-list gate lives in CapturePipeline, so this covers the cascade's
    own cheap-gate short-circuit instead."""
    clf = _AlwaysSensitive()
    cascade = DedupCascade(classifier=clf)

    first = _img(1)
    cascade.evaluate(first)
    decision = cascade.evaluate(first)

    assert decision.persist is False
    assert decision.gate == "dhash"
    assert clf.calls == 1, "classifier must not run on dHash-skipped frames"


def test_classifier_runs_only_after_ssim_survives():
    """Classifier sees the frame only when all cheap gates pass."""
    clf = _NeverSensitive()
    # A lax SSIM threshold plus wholly different images so dHash/pHash/SSIM all
    # let the frame through to the classifier.
    cascade = DedupCascade(
        thresholds=CascadeThresholds(ssim_skip_min=0.99),
        classifier=clf,
    )

    decision = cascade.evaluate(_img(1))
    assert decision.persist is True
    assert decision.gate == "persist"
    assert clf.calls == 1

    decision = cascade.evaluate(_img(99))
    assert decision.persist is True
    assert clf.calls == 2


def test_high_confidence_sensitive_redacts():
    clf = _AlwaysSensitive(confidence=0.9, categories=["password_field"])
    cascade = DedupCascade(classifier=clf, redact_threshold=0.6)

    decision: Decision = cascade.evaluate(_img(1))

    assert decision.persist is False
    assert decision.gate == "redacted"
    assert decision.redaction is not None
    assert decision.redaction.is_sensitive is True
    assert decision.redaction.confidence == 0.9
    assert decision.redaction.categories == ["password_field"]
    assert "password_field" in decision.detail


def test_below_threshold_sensitive_still_persists():
    """A user can dial recall/precision with --redact-threshold."""
    clf = _AlwaysSensitive(confidence=0.4)
    cascade = DedupCascade(classifier=clf, redact_threshold=0.6)

    decision = cascade.evaluate(_img(1))

    assert decision.persist is True
    assert decision.gate == "persist"
    assert decision.redaction is None


def test_redacted_frame_still_advances_dedup_state():
    """After a redact, the next identical frame must be dHash-skipped so the
    classifier isn't paid for twice on the same screen."""
    clf = _AlwaysSensitive(confidence=0.9)
    cascade = DedupCascade(classifier=clf)

    same = _img(1)
    d1 = cascade.evaluate(same)
    d2 = cascade.evaluate(same)

    assert d1.gate == "redacted"
    assert d2.gate == "dhash", "second identical frame must short-circuit before classifier"
    assert clf.calls == 1


def test_hint_is_forwarded_to_classifier():
    """The cascade's `hint` reaches the classifier as context."""

    seen_hints: list[str] = []

    class _Spy:
        def classify(self, image, *, hint="", timeout_ms=250):
            seen_hints.append(hint)
            return SensitiveDecision(is_sensitive=False, confidence=0.0, model="spy")

    cascade = DedupCascade(classifier=_Spy())
    cascade.evaluate(_img(1), hint="Safari — Bank Login")

    assert seen_hints == ["Safari — Bank Login"]


def test_heuristic_classifier_with_hint_redacts():
    """HeuristicClassifier flags any hinted frame, producing a redacted Decision."""
    cascade = DedupCascade(classifier=HeuristicClassifier(), redact_threshold=0.6)
    decision = cascade.evaluate(_img(1), hint="1Password")

    assert decision.gate == "redacted"
    assert decision.redaction is not None
    assert decision.redaction.model == "heuristic"

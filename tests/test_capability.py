from __future__ import annotations

import sqlite3

from secondbrain.capture.capability import CapabilityCache


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def test_first_observation_seeds_usable_when_ax_present():
    cache = CapabilityCache(_conn())
    rec = cache.record("com.electron.app", "MyApp", ax_text_present=True)
    assert rec.usable is True
    assert rec.ax_success == 1


def test_first_observation_not_usable_when_ax_absent():
    cache = CapabilityCache(_conn())
    rec = cache.record("com.figma.canvas", "Figma", ax_text_present=False)
    assert rec.usable is False


def test_flips_on_after_three_hits_majority():
    cache = CapabilityCache(_conn())
    cache.record("c", "n", False)
    cache.record("c", "n", True)
    cache.record("c", "n", True)
    rec = cache.record("c", "n", True)
    # 3 successes / 4 total = 0.75, ≥3 hits → usable
    assert rec.usable is True


def test_flips_off_after_five_consecutive_misses():
    cache = CapabilityCache(_conn())
    cache.record("c", "n", True)  # bootstrap usable=True
    for _ in range(5):
        rec = cache.record("c", "n", False)
    assert rec.usable is False


def test_is_usable_returns_none_for_unknown():
    cache = CapabilityCache(_conn())
    assert cache.is_usable("unknown.bundle", "Unknown") is None

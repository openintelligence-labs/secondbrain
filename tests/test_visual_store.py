"""Multivector store + MaxSim ranking, with deterministic embeds."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from secondbrain.store.visual import VisualStore


def _patches(seed: int, n_patches: int = 8) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p = rng.standard_normal((n_patches, 128)).astype(np.float32)
    p /= np.linalg.norm(p, axis=1, keepdims=True)
    return p


def test_visual_store_round_trip(tmp_path: Path):
    store = VisualStore(db_path=tmp_path / "vis")
    store.add("capA", _patches(1), created_at=1.0)
    store.add("capB", _patches(2), created_at=2.0)
    assert store.count() == 2


def test_maxsim_ranks_self_first(tmp_path: Path):
    store = VisualStore(db_path=tmp_path / "vis")
    a = _patches(1)
    b = _patches(2)
    store.add("capA", a, created_at=1.0)
    store.add("capB", b, created_at=2.0)
    # Query with capA's patches → capA must score highest.
    ranked = store.maxsim_search(a, limit=2)
    assert ranked[0][0] == "capA"
    assert ranked[0][1] > ranked[1][1]

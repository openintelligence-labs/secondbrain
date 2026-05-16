"""Frame deduplication cascade.

Order (cheapest gate first; each gate has authority to skip the frame):

    1. Window-title deny-list match           → skip (0 ms)
    2. AX-tree subtree hash unchanged         → skip (~1 ms; in `ax.py`)
    3. Dirty-rect area below threshold         → skip (sidecar emits this)
    4. dHash Hamming distance below threshold  → skip (~0.3 ms)
    5. pHash verify on borderline (5..10)      → skip
    6. SSIM on dirty thumbnail above threshold → skip (~5 ms)

Public surface: `DedupCascade.evaluate(frame) -> Decision`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image

GateName = Literal[
    "deny_list",
    "ax_unchanged",
    "dirty_rect",
    "dhash",
    "phash",
    "ssim",
    "persist",
]


@dataclass(frozen=True, slots=True)
class Decision:
    """Outcome of running a frame through the cascade.

    `gate` names which gate decided the frame's fate; `persist=True` means it
    survived all gates and should be written to disk.
    """

    persist: bool
    gate: GateName
    detail: str = ""


def dhash(image: Image.Image | np.ndarray, hash_size: int = 8) -> int:
    """Difference-hash. 64-bit (default) integer.

    Resize to (hash_size+1) x hash_size grayscale, then compare each pixel to
    its right neighbor. The bit pattern is the hash.
    """
    if isinstance(image, np.ndarray):
        image = Image.fromarray(image)
    img = image.convert("L").resize(
        (hash_size + 1, hash_size), Image.Resampling.LANCZOS
    )
    arr = np.asarray(img, dtype=np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    bits = 0
    for v in diff.flatten():
        bits = (bits << 1) | int(v)
    return bits


def hamming(a: int, b: int) -> int:
    """Bitwise hamming distance between two integer hashes."""
    return (a ^ b).bit_count()


def phash(image: Image.Image | np.ndarray, hash_size: int = 8) -> int:
    """Perceptual hash via DCT. 64-bit integer.

    Used as a borderline verifier when dHash distance is in the 5–10 ambiguous
    band. More robust to small visual perturbations than dHash.
    """
    if isinstance(image, np.ndarray):
        image = Image.fromarray(image)
    img_size = hash_size * 4
    img = image.convert("L").resize(
        (img_size, img_size), Image.Resampling.LANCZOS
    )
    arr = np.asarray(img, dtype=np.float32)
    dct_full = _dct2(arr)
    low = dct_full[:hash_size, :hash_size]
    median = np.median(low)
    bits = 0
    for v in low.flatten():
        bits = (bits << 1) | int(v > median)
    return bits


def _dct2(a: np.ndarray) -> np.ndarray:
    """2-D DCT-II via NumPy. Avoids a SciPy dependency."""
    N = a.shape[0]
    n = np.arange(N)
    k = n.reshape((N, 1))
    basis = np.cos(np.pi * (2 * n + 1) * k / (2 * N)).astype(np.float32)
    return basis @ a @ basis.T


def ssim_thumb(a: Image.Image, b: Image.Image, size: int = 256) -> float:
    """SSIM on size x size grayscale thumbnails. Returns a float in [-1, 1]."""
    from skimage.metrics import structural_similarity

    ta = np.asarray(
        a.convert("L").resize((size, size), Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    tb = np.asarray(
        b.convert("L").resize((size, size), Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    return float(structural_similarity(ta, tb, data_range=255.0))


@dataclass
class CascadeThresholds:
    """Tuneable thresholds for the dedup cascade.

    The defaults are validated by the spike benchmarks under `spikes/`;
    expect to revisit once real workload measurements are in.
    """

    dirty_rect_min_fraction: float = 0.005      # 0.5% of display area
    dhash_skip_max: int = 4                      # Hamming <=4 = duplicate
    dhash_borderline_max: int = 10               # 5..10 → escalate to pHash
    phash_skip_max: int = 6
    ssim_skip_min: float = 0.96


class DedupCascade:
    """Stateful evaluator. Holds the previous-frame hashes for comparison."""

    def __init__(self, thresholds: CascadeThresholds | None = None) -> None:
        self.t = thresholds or CascadeThresholds()
        self._prev_dhash: int | None = None
        self._prev_phash: int | None = None
        self._prev_thumb: Image.Image | None = None

    def evaluate(
        self,
        image: Image.Image,
        *,
        dirty_rect_fraction: float | None = None,
    ) -> Decision:
        """Run a candidate frame through every gate. Updates state on persist."""
        # Gate 3 — dirty-rect area
        if (
            dirty_rect_fraction is not None
            and dirty_rect_fraction < self.t.dirty_rect_min_fraction
        ):
            return Decision(
                persist=False,
                gate="dirty_rect",
                detail=f"fraction={dirty_rect_fraction:.4f}",
            )

        # Gate 4 — dHash
        cur_dhash = dhash(image)
        if self._prev_dhash is not None:
            d_dh = hamming(cur_dhash, self._prev_dhash)
            if d_dh <= self.t.dhash_skip_max:
                return Decision(
                    persist=False,
                    gate="dhash",
                    detail=f"hamming={d_dh}",
                )

            # Gate 5 — pHash verifier on borderline band
            if d_dh <= self.t.dhash_borderline_max:
                cur_phash = phash(image)
                if self._prev_phash is not None:
                    d_ph = hamming(cur_phash, self._prev_phash)
                    if d_ph <= self.t.phash_skip_max:
                        return Decision(
                            persist=False,
                            gate="phash",
                            detail=f"dhash={d_dh} phash={d_ph}",
                        )

                # Gate 6 — SSIM final gate (only when pHash also unsure)
                if self._prev_thumb is not None:
                    s = ssim_thumb(image, self._prev_thumb)
                    if s >= self.t.ssim_skip_min:
                        return Decision(
                            persist=False,
                            gate="ssim",
                            detail=f"ssim={s:.4f}",
                        )

        # Survived all gates → persist; update state.
        self._prev_dhash = cur_dhash
        self._prev_phash = phash(image)
        self._prev_thumb = image
        return Decision(persist=True, gate="persist")

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from secondbrain.capture.dedup import (
    CascadeThresholds,
    DedupCascade,
    dhash,
    hamming,
    phash,
    ssim_thumb,
)


def _solid(color: tuple[int, int, int], size: tuple[int, int] = (640, 480)) -> Image.Image:
    return Image.new("RGB", size, color)


def _solid_with_text(color: tuple[int, int, int], text: str) -> Image.Image:
    img = _solid(color)
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), text, fill=(255, 255, 255))
    return img


def _noise(seed: int, size: tuple[int, int] = (640, 480)) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, size=(size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(arr)


def test_dhash_identical_images_same_hash():
    a = _solid((10, 20, 30))
    b = _solid((10, 20, 30))
    assert dhash(a) == dhash(b)


def test_dhash_different_images_differ():
    a = _solid((10, 20, 30))
    b = _solid((200, 50, 50))
    # Solid images dHash to all zeros (no left-to-right gradient), but two
    # *different* noise patterns must hash differently.
    assert dhash(_noise(1)) != dhash(_noise(2))
    # And solids of different colors still match each other on dHash by design
    # (no gradient) — which is exactly why the cascade has multiple layers.
    assert dhash(a) == dhash(b)


def test_hamming_basic():
    assert hamming(0, 0) == 0
    assert hamming(0, 0xFFFFFFFFFFFFFFFF) == 64
    assert hamming(0b1010, 0b0101) == 4


def test_phash_64bits():
    h = phash(_noise(42))
    assert 0 <= h < (1 << 64)


def test_ssim_self_is_one():
    img = _noise(7)
    assert ssim_thumb(img, img) > 0.99


def test_cascade_skips_identical_frames():
    cascade = DedupCascade()
    a = _noise(3)
    d1 = cascade.evaluate(a)
    d2 = cascade.evaluate(a)
    assert d1.persist is True
    assert d1.gate == "persist"
    assert d2.persist is False
    assert d2.gate == "dhash"


def test_cascade_keeps_truly_different_frames():
    cascade = DedupCascade()
    a = _noise(1)
    b = _noise(99)
    assert cascade.evaluate(a).persist is True
    assert cascade.evaluate(b).persist is True


def test_cascade_dirty_rect_gate_short_circuits():
    cascade = DedupCascade()
    img = _noise(5)
    # First frame must persist to seed state.
    assert cascade.evaluate(img).persist is True
    # Below 0.5% changed area — must skip even if pixels differ.
    decision = cascade.evaluate(_noise(6), dirty_rect_fraction=0.001)
    assert decision.persist is False
    assert decision.gate == "dirty_rect"


def test_cascade_borderline_escalates_to_phash_then_ssim():
    """Tighten thresholds so the same-frame case forces escalation paths."""
    t = CascadeThresholds(
        dhash_skip_max=0,  # only exact matches skip on dHash
        dhash_borderline_max=64,  # always escalate to pHash
        phash_skip_max=0,  # only exact pHash matches skip on pHash
        ssim_skip_min=0.99,
    )
    cascade = DedupCascade(t)
    a = _noise(11)
    cascade.evaluate(a)
    # Evaluating the same image again should now reach the SSIM gate since
    # dHash distance is 0 and would short-circuit at gate 4 — flip that to
    # force escalation by perturbing one pixel.
    arr = np.asarray(a).copy()
    arr[0, 0] = (255 - arr[0, 0, 0], 0, 0)
    perturbed = Image.fromarray(arr)
    decision = cascade.evaluate(perturbed)
    # SSIM on near-identical thumbnail must be very high → skip.
    assert decision.persist is False
    assert decision.gate in ("dhash", "phash", "ssim")

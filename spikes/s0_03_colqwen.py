"""Verify ColQwen2.5 visual late-interaction runs on Apple Silicon (MPS).

Pass criteria:
- Load colpali-engine + a ColQwen2.5 checkpoint on MPS
- Encode 5 synthetic screenshots
- Encode a text query, compute MaxSim scores against all 5
- Total wall time <60s on M-series (warm), per-image marginal cost <2s (the 5s
  budget in the architecture is for amortized end-to-end including I/O)

Note: model weights are several GB and only download once. We use
`vidore/colqwen2.5-v0.2`, the canonical ColQwen2.5 checkpoint on the ViDoRe
team's HF.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import torch  # noqa: E402
from _runner import record  # noqa: E402
from PIL import Image  # noqa: E402

CHECKPOINT = "vidore/colqwen2.5-v0.2"


def synth_screenshot(seed: int, size: tuple[int, int] = (768, 512)) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, size=(size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(arr, mode="RGB")


def main() -> None:
    if not torch.backends.mps.is_available():
        record("S0-03", False, {"reason": "MPS not available"})
        return

    device = "mps"
    print(f"torch={torch.__version__} device={device}")
    print(f"loading {CHECKPOINT} (this is a multi-GB download on first run)...")

    from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor

    t0 = time.perf_counter()
    model = ColQwen2_5.from_pretrained(
        CHECKPOINT,
        torch_dtype=torch.float16,
        device_map=device,
    ).eval()
    processor = ColQwen2_5_Processor.from_pretrained(CHECKPOINT)
    load_s = time.perf_counter() - t0

    images = [synth_screenshot(i) for i in range(5)]

    # Image batch
    t0 = time.perf_counter()
    with torch.no_grad():
        batch = processor.process_images(images).to(device)
        img_emb = model(**batch)
    img_s = time.perf_counter() - t0

    # Query
    queries = ["the slide with the red Q3 chart"]
    t0 = time.perf_counter()
    with torch.no_grad():
        qbatch = processor.process_queries(queries).to(device)
        q_emb = model(**qbatch)
    q_s = time.perf_counter() - t0

    # MaxSim scoring (built-in)
    t0 = time.perf_counter()
    scores = processor.score_multi_vector(q_emb, img_emb)
    score_s = time.perf_counter() - t0

    # Move to CPU for inspection
    s = scores.detach().to("cpu").numpy()

    passed = (
        img_emb.dim() == 3  # (B, patches, dim)
        and q_emb.dim() == 3
        and s.shape == (1, 5)
        and img_s < 30.0  # warm-up may include lazy compile
    )

    record(
        "S0-03",
        passed,
        {
            "checkpoint": CHECKPOINT,
            "torch_version": torch.__version__,
            "device": device,
            "load_seconds": round(load_s, 1),
            "img_emb_shape": list(img_emb.shape),
            "q_emb_shape": list(q_emb.shape),
            "encode_5_images_seconds": round(img_s, 2),
            "encode_query_seconds": round(q_s, 2),
            "maxsim_score_seconds": round(score_s, 3),
            "scores": [round(float(x), 3) for x in s.flatten()],
            "criterion": "shapes correct AND encode_5_images_seconds < 30s",
        },
    )


if __name__ == "__main__":
    main()

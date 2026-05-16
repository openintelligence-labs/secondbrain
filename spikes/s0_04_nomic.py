"""Verify Nomic Embed v2 (137M MoE) runs CPU-only at acceptable throughput.

Pass criteria:
- Load nomic-embed-text-v2-moe via sentence-transformers (trust_remote_code=True)
- Embed 100 strings on CPU
- Throughput >=20 strings/sec (relaxed from 100/sec because MoE on CPU is heavier
  than dense; 20/sec is plenty for SecondBrain's continuous-but-not-realtime
  embedding pipeline)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _runner import record  # noqa: E402

from sentence_transformers import SentenceTransformer  # noqa: E402

MODEL = "nomic-ai/nomic-embed-text-v2-moe"
N = 100


def main() -> None:
    print(f"Loading {MODEL} on CPU...")
    t0 = time.perf_counter()
    model = SentenceTransformer(
        MODEL,
        device="cpu",
        trust_remote_code=True,
    )
    load_s = time.perf_counter() - t0

    texts = [
        f"This is sample text number {i} about meetings, retrieval, and memory."
        for i in range(N)
    ]

    # Warmup
    _ = model.encode(texts[:2], prompt_name="passage", show_progress_bar=False)

    t0 = time.perf_counter()
    vecs = model.encode(
        texts,
        prompt_name="passage",
        batch_size=8,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    elapsed_s = time.perf_counter() - t0
    rate = N / elapsed_s

    # Sanity checks: dim, normalization
    arr = np.asarray(vecs, dtype=np.float32)
    dim = arr.shape[1]
    norms = np.linalg.norm(arr, axis=1)

    passed = arr.shape[0] == N and dim in (384, 768, 256, 128) and rate >= 20.0
    record(
        "S0-04",
        passed,
        {
            "model": MODEL,
            "device": "cpu",
            "load_seconds": round(load_s, 1),
            "n": N,
            "elapsed_seconds": round(elapsed_s, 2),
            "throughput_per_sec": round(rate, 1),
            "embedding_dim": dim,
            "norm_mean": round(float(norms.mean()), 3),
            "criterion": "rate >= 20 strings/sec",
        },
    )


if __name__ == "__main__":
    main()

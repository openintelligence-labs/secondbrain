"""Visual embeddings — ColQwen2.5-v0.2 (the moat).

Validated by the initial spike on Apple Silicon (MPS): ~3.3s/image warm
encode, output shape (B, ~497 patches, 128-d). Ships behind a lazy loader so
headless tests and non-vision code paths don't pay the load cost.

Public surface:
    embedder = VisualEmbedder()
    patches = embedder.embed_images([PIL.Image, ...])   # (B, P, dim) torch.Tensor
    qpatches = embedder.embed_queries(["the slide with the red Q3 chart"])
    scores = embedder.score_multi_vector(qpatches, patches)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image

DEFAULT_CHECKPOINT = "vidore/colqwen2.5-v0.2"
PATCH_DIM = 128


@dataclass
class VisualEmbedderConfig:
    checkpoint: str = DEFAULT_CHECKPOINT
    device: str = "auto"  # 'mps' | 'cuda' | 'cpu' | 'auto'
    dtype: str = "float16"


class VisualEmbedder:
    """Lazy ColQwen2.5 wrapper. Heavy load deferred to first call."""

    def __init__(self, cfg: VisualEmbedderConfig | None = None) -> None:
        self.cfg = cfg or VisualEmbedderConfig()
        self._model: Any = None
        self._processor: Any = None
        self._device: str | None = None
        self._lock = threading.Lock()

    def _resolve_device(self) -> str:
        if self.cfg.device != "auto":
            return self.cfg.device
        try:
            import torch

            if torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            import torch
            from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor

            self._device = self._resolve_device()
            dtype = getattr(torch, self.cfg.dtype, torch.float16)
            self._model = ColQwen2_5.from_pretrained(
                self.cfg.checkpoint,
                torch_dtype=dtype,
                device_map=self._device,
            ).eval()
            self._processor = ColQwen2_5_Processor.from_pretrained(self.cfg.checkpoint)

    @property
    def device(self) -> str:
        self._ensure_loaded()
        assert self._device is not None
        return self._device

    def embed_images(self, images: list[Image.Image]) -> Any:
        """Returns a torch.Tensor of shape (B, P_b, dim)."""
        if not images:
            import torch

            return torch.empty(0)
        self._ensure_loaded()
        import torch

        with torch.no_grad():
            batch = self._processor.process_images(images).to(self._device)
            emb = self._model(**batch)
        return emb

    def embed_queries(self, queries: list[str]) -> Any:
        if not queries:
            import torch

            return torch.empty(0)
        self._ensure_loaded()
        import torch

        with torch.no_grad():
            batch = self._processor.process_queries(queries).to(self._device)
            emb = self._model(**batch)
        return emb

    def score_multi_vector(self, q_emb: Any, img_emb: Any) -> Any:
        """MaxSim scoring (delegates to processor)."""
        self._ensure_loaded()
        return self._processor.score_multi_vector(q_emb, img_emb)

"""Reranker stub — mxbai-rerank-base-v2.

Defers actual model load until first call. If the model fails to load (no
internet for first download), `Reranker.rerank` falls back to identity so the
search path never breaks.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "mixedbread-ai/mxbai-rerank-base-v2"


@dataclass
class RerankerConfig:
    model: str = DEFAULT_MODEL
    device: str = "cpu"
    enabled: bool = True


class Reranker:
    """CPU cross-encoder reranker. Lazy-loads."""

    def __init__(self, cfg: RerankerConfig | None = None) -> None:
        self.cfg = cfg or RerankerConfig()
        self._model = None
        self._tokenizer = None
        self._lock = threading.Lock()
        self._load_failed = False

    def _ensure_loaded(self) -> bool:
        if self._load_failed or not self.cfg.enabled:
            return False
        if self._model is not None:
            return True
        with self._lock:
            if self._model is not None:
                return True
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(
                    self.cfg.model,
                    device=self.cfg.device,
                )
            except Exception:
                self._load_failed = True
                return False
        return True

    def rerank(
        self,
        query: str,
        passages: list[str],
        *,
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """Return [(original_index, score), ...] sorted descending.

        If the model couldn't load, scores are 0.0 and original order is kept.
        """
        if not passages:
            return []
        if not self._ensure_loaded():
            return [(i, 0.0) for i in range(min(top_k or len(passages), len(passages)))]
        pairs = [[query, p] for p in passages]
        scores = self._model.predict(pairs).tolist()  # type: ignore[union-attr]
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        if top_k is not None:
            ranked = ranked[:top_k]
        return ranked

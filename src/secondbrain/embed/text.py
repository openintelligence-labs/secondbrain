"""Text embeddings — Nomic Embed v2 MoE on CPU by default.

Two backends, selected at construction:

  - `backend="actants"` (preferred when Ollama is up) — routes through
    `actants.Embeddings`, which gives you provider switching, tracing, and
    cost tracking for free. Default model is whatever Ollama serves under
    the same EmbeddingSettings; we ask for `nomic-embed-text` (the
    distilled-into-Ollama Nomic v1.5; the v2 MoE model is HF-only today).

  - `backend="local"` (default fallback) — direct `sentence-transformers`
    against `nomic-ai/nomic-embed-text-v2-moe` on CPU. Validated by the
    initial spike at 83.7 strings/sec on a laptop, 768-d normalized.

The `EMBEDDING_DIM` constant stays 768 because that's what every consumer
(`store/vector.py`, `embed/stub.py`) is sized for. If you switch to a
different actants model whose dim != 768, the LanceDB schema needs a
matching update.

Public surface:
    embedder = TextEmbedder()                       # local default
    embedder = TextEmbedder.via_actants()           # actants/Ollama path
    vecs = embedder.embed_passages(["..."])
    qvec = embedder.embed_query("...")
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v2-moe"
ACTANTS_DEFAULT_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768

Backend = Literal["local", "actants"]


@dataclass
class TextEmbedderConfig:
    model: str = DEFAULT_MODEL
    device: str = "cpu"
    batch_size: int = 8
    normalize: bool = True
    backend: Backend = "local"
    # When backend=="actants", we route through actants.Embeddings.
    # Model defaults to ACTANTS_DEFAULT_MODEL ("nomic-embed-text" via Ollama).
    actants_model: str = ACTANTS_DEFAULT_MODEL


def _l2_normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


class TextEmbedder:
    """Thread-safe Nomic v2 wrapper. Lazy-loads on first call."""

    def __init__(self, cfg: TextEmbedderConfig | None = None) -> None:
        self.cfg = cfg or TextEmbedderConfig()
        self._model: SentenceTransformer | None = None
        self._actants = None  # actants.Embeddings | None
        self._load_lock = threading.Lock()

    @classmethod
    def via_actants(
        cls,
        *,
        model: str = ACTANTS_DEFAULT_MODEL,
        normalize: bool = True,
    ) -> TextEmbedder:
        """Build an embedder that routes through actants (default Ollama)."""
        return cls(
            TextEmbedderConfig(
                backend="actants",
                actants_model=model,
                normalize=normalize,
            )
        )

    # ------- backend: local sentence-transformers -------
    def _ensure_local(self) -> SentenceTransformer:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ModuleNotFoundError as e:
                    raise ModuleNotFoundError(
                        "Local text embeddings require the [ml] extra. "
                        "Install with: pip install -e '.[ml]' "
                        "(or use --stub-embedder for tests/demos, or set "
                        "SECONDBRAIN_LLM_EMBEDDINGS=ollama to use Ollama)."
                    ) from e
                self._model = SentenceTransformer(
                    self.cfg.model,
                    device=self.cfg.device,
                    trust_remote_code=True,
                )
        return self._model

    # ------- backend: actants -------
    def _ensure_actants(self):
        if self._actants is not None:
            return self._actants
        with self._load_lock:
            if self._actants is None:
                from actants import Embeddings

                self._actants = Embeddings(model=self.cfg.actants_model)
        return self._actants

    @property
    def dim(self) -> int:
        return EMBEDDING_DIM

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        """Embed documents/chunks. Returns float32 (N, dim) ndarray."""
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        if self.cfg.backend == "actants":
            embeddings = self._ensure_actants()
            result = asyncio.run(embeddings.embed(list(texts)))
            arr = np.asarray(result.vectors, dtype=np.float32)
            if self.cfg.normalize:
                arr = _l2_normalize(arr)
            return arr

        model = self._ensure_local()
        vecs = model.encode(
            list(texts),
            prompt_name="passage",
            batch_size=self.cfg.batch_size,
            normalize_embeddings=self.cfg.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(vecs, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a single query string. Returns float32 (dim,) ndarray."""
        if self.cfg.backend == "actants":
            embeddings = self._ensure_actants()
            vec = asyncio.run(embeddings.embed_one(text))
            arr = np.asarray(vec, dtype=np.float32)
            if self.cfg.normalize:
                n = float(np.linalg.norm(arr)) or 1.0
                arr = arr / n
            return arr

        model = self._ensure_local()
        v = model.encode(
            [text],
            prompt_name="query",
            normalize_embeddings=self.cfg.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(v[0], dtype=np.float32)

    async def aembed_passages(self, texts: Sequence[str]) -> np.ndarray:
        if self.cfg.backend == "actants":
            embeddings = self._ensure_actants()
            result = await embeddings.embed(list(texts))
            arr = np.asarray(result.vectors, dtype=np.float32)
            if self.cfg.normalize:
                arr = _l2_normalize(arr)
            return arr
        return await asyncio.to_thread(self.embed_passages, texts)

    async def aembed_query(self, text: str) -> np.ndarray:
        if self.cfg.backend == "actants":
            embeddings = self._ensure_actants()
            vec = await embeddings.embed_one(text)
            arr = np.asarray(vec, dtype=np.float32)
            if self.cfg.normalize:
                n = float(np.linalg.norm(arr)) or 1.0
                arr = arr / n
            return arr
        return await asyncio.to_thread(self.embed_query, text)

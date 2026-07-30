"""Capture → chunk → embed → index pipeline.

Wires the embedder, chunker, vector store, and text index together in one
place so the daemon and CLI can share the exact same indexing path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from secondbrain.embed.chunker import chunks_for
from secondbrain.embed.text import TextEmbedder
from secondbrain.models import Capture
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


@dataclass
class Indexer:
    embedder: TextEmbedder
    vector: VectorStore
    text: TextIndex

    def index_capture(self, capture: Capture) -> int:
        """Index a single capture's text. Returns # chunks indexed."""
        chunks = self._chunks(capture)
        if not chunks:
            return 0

        vecs = self.embedder.embed_passages([c.text for c in chunks])
        rows = []
        for c, v in zip(chunks, vecs, strict=True):
            cuid = f"{c.capture_id}:{c.chunk_index}"
            rows.append(
                {
                    "capture_id": c.capture_id,
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    "vector": v,
                    "created_at": time.time(),
                }
            )
            self.text.add(
                chunk_uid=cuid,
                capture_id=c.capture_id,
                chunk_index=c.chunk_index,
                body=c.text,
            )

        self.vector.add_chunks(rows)
        self.text.commit()
        return len(chunks)

    def index_capture_keyword_only(self, capture: Capture) -> int:
        """BM25-only fallback: index into tantivy without embedding.

        For callers whose embedder is unavailable at write time (e.g. the
        gateway before the model is cached, or Ollama down). The capture must
        already be persisted to OLTP so the next `secondbrain index` bulk
        pass backfills the vector side through the normal embed path.
        """
        chunks = self._chunks(capture)
        if not chunks:
            return 0

        for c in chunks:
            self.text.add(
                chunk_uid=f"{c.capture_id}:{c.chunk_index}",
                capture_id=c.capture_id,
                chunk_index=c.chunk_index,
                body=c.text,
            )
        self.text.commit()
        return len(chunks)

    def _chunks(self, capture: Capture):
        body = capture.ax_text or capture.ocr_text
        if not body:
            return []
        return chunks_for(capture.id, body)

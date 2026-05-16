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
        body = capture.ax_text or capture.ocr_text
        if not body:
            return 0

        chunks = chunks_for(capture.id, body)
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

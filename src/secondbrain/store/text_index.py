"""tantivy BM25 index over chunks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tantivy


@dataclass
class TextIndex:
    index_path: Path

    def __post_init__(self) -> None:
        self.index_path.mkdir(parents=True, exist_ok=True)
        sb = tantivy.SchemaBuilder()
        sb.add_text_field("chunk_uid", stored=True)
        sb.add_text_field("capture_id", stored=True)
        sb.add_integer_field("chunk_index", stored=True, indexed=True)
        sb.add_text_field("body", stored=True)
        self.schema = sb.build()
        self._index = tantivy.Index(self.schema, path=str(self.index_path))
        self._writer = self._index.writer()

    def add(self, *, chunk_uid: str, capture_id: str, chunk_index: int, body: str) -> None:
        self._writer.add_document(
            tantivy.Document(
                chunk_uid=chunk_uid,
                capture_id=capture_id,
                chunk_index=chunk_index,
                body=body,
            )
        )

    def commit(self) -> None:
        self._writer.commit()
        self._index.reload()

    def search(self, query: str, *, limit: int = 50) -> list[dict]:
        searcher = self._index.searcher()
        try:
            parsed = self._index.parse_query(query, ["body"])
        except Exception:
            return []
        hits = searcher.search(parsed, limit).hits
        out: list[dict] = []
        for score, doc_addr in hits:
            doc = searcher.doc(doc_addr)
            out.append(
                {
                    "score": float(score),
                    "chunk_uid": doc["chunk_uid"][0],
                    "capture_id": doc["capture_id"][0],
                    "chunk_index": int(doc["chunk_index"][0]),
                    "body": doc["body"][0],
                }
            )
        return out

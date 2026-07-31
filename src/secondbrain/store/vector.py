"""LanceDB vector store.

Single `chunks` table:
    id            : uint64 (per-row monotonic)
    chunk_uid     : str    (capture_id + ':' + chunk_index, for joins)
    capture_id    : str
    chunk_index   : int
    text          : str
    vector        : list[float32, 768]  # Nomic v2
    created_at    : float
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lancedb
import numpy as np
import pyarrow as pa

VECTOR_DIM = 768


def _schema(dim: int = VECTOR_DIM) -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.uint64()),
            pa.field("chunk_uid", pa.string()),
            pa.field("capture_id", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("created_at", pa.float64()),
        ]
    )


@dataclass
class VectorStore:
    db_path: Path
    table_name: str = "chunks"
    dim: int = VECTOR_DIM

    def __post_init__(self) -> None:
        self.db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.db_path))
        listing = self._db.list_tables()
        # LanceDB returns either a list[str] or a ListTablesResponse depending
        # on version; handle both shapes.
        names = getattr(listing, "tables", listing)
        existing = set(names)
        if self.table_name not in existing:
            self._db.create_table(self.table_name, schema=_schema(self.dim), mode="create")
        self._tbl = self._db.open_table(self.table_name)
        self._next_id = self._compute_next_id()

    def _compute_next_id(self) -> int:
        try:
            n = self._tbl.count_rows()
        except Exception:
            n = 0
        return int(n)

    def add_chunks(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        if not rows:
            return
        prepared = []
        for r in rows:
            cuid = f"{r['capture_id']}:{r['chunk_index']}"
            vec = np.asarray(r["vector"], dtype=np.float32)
            prepared.append(
                {
                    "id": self._next_id,
                    "chunk_uid": cuid,
                    "capture_id": r["capture_id"],
                    "chunk_index": int(r["chunk_index"]),
                    "text": r["text"],
                    "vector": vec.tolist(),
                    "created_at": float(r.get("created_at", 0.0)),
                }
            )
            self._next_id += 1
        self._tbl.add(prepared)

    def search(
        self,
        query_vec: np.ndarray,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Cosine-similarity search. Returns rows with `_distance`."""
        q = np.asarray(query_vec, dtype=np.float32)
        result = self._tbl.search(q).metric("cosine").limit(limit).to_arrow()
        out: list[dict[str, Any]] = []
        cols = {name: result.column(name).to_pylist() for name in result.column_names}
        n = result.num_rows
        for i in range(n):
            out.append({k: cols[k][i] for k in cols})
        return out

    def count(self) -> int:
        return int(self._tbl.count_rows())

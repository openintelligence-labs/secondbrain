"""LanceDB multivector store for ColQwen patch embeddings.

One row per capture; `patches` is a list-of-list-of-float32 of shape (P, 128).
The initial spike validated insert + MaxSim ranking shape. The native LanceDB
MaxSim search API plug lands later; today we ship a Python MaxSim that's
correct and fast enough for ~10k captures.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa


PATCH_DIM = 128


def _schema(dim: int = PATCH_DIM) -> pa.Schema:
    return pa.schema(
        [
            pa.field("capture_id", pa.string()),
            pa.field("patches", pa.list_(pa.list_(pa.float32(), dim))),
            pa.field("created_at", pa.float64()),
        ]
    )


@dataclass
class VisualStore:
    db_path: Path
    table_name: str = "vis_chunks"
    dim: int = PATCH_DIM

    def __post_init__(self) -> None:
        self.db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.db_path))
        listing = self._db.list_tables()
        names = getattr(listing, "tables", listing)
        if self.table_name not in set(names):
            self._db.create_table(
                self.table_name, schema=_schema(self.dim), mode="create"
            )
        self._tbl = self._db.open_table(self.table_name)

    def add(self, capture_id: str, patches: np.ndarray, created_at: float) -> None:
        arr = np.asarray(patches, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] != self.dim:
            raise ValueError(
                f"patches must be (P, {self.dim}); got {arr.shape}"
            )
        self._tbl.add(
            [
                {
                    "capture_id": capture_id,
                    "patches": arr.tolist(),
                    "created_at": float(created_at),
                }
            ]
        )

    def maxsim_search(
        self,
        query_patches: np.ndarray,
        *,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Brute-force Python MaxSim. Sufficient for v0.x fleet sizes (~10k captures)."""
        q = np.asarray(query_patches, dtype=np.float32)
        if q.ndim != 2 or q.shape[1] != self.dim:
            raise ValueError(f"query_patches must be (Q, {self.dim}); got {q.shape}")

        arrow_tbl = self._tbl.to_arrow()
        if arrow_tbl.num_rows == 0:
            return []
        ids = arrow_tbl.column("capture_id").to_pylist()
        patches_col = arrow_tbl.column("patches").to_pylist()

        scores: list[tuple[str, float]] = []
        for cid, plist in zip(ids, patches_col, strict=True):
            doc = np.asarray(plist, dtype=np.float32)
            sim = q @ doc.T  # (Q, P)
            score = float(sim.max(axis=1).sum())
            scores.append((cid, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]

    def count(self) -> int:
        return int(self._tbl.count_rows())

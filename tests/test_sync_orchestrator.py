"""Sync orchestrator: push walks new memories, pull applies them, cursor advances."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from secondbrain.store.kg import KnowledgeGraph
from secondbrain.store.oltp import open_unencrypted
from secondbrain.sync.backend import SyncthingBackend
from secondbrain.sync.orchestrator import _read_cursor, pull, push


def _seed_kg(kg: KnowledgeGraph, n: int, start: datetime) -> list[str]:
    ids = []
    for i in range(n):
        mid = f"m{i:04d}"
        ig = start + timedelta(seconds=i)
        kg.upsert_memory(
            mid,
            "fact",
            f"memory body {i}",
            valid_from=ig,
            valid_to=None,
            ingested_at=ig,
            importance=1.0 + i * 0.1,
        )
        ids.append(mid)
    return ids


def test_push_pull_roundtrip(tmp_path: Path):
    psk = os.urandom(32)
    folder = tmp_path / "shared"
    folder.mkdir()

    # Device A: write memories, push.
    kg_a = KnowledgeGraph(db_path=tmp_path / "A" / "kg")
    oltp_a = open_unencrypted(tmp_path / "A" / "sb.db")
    start = datetime(2026, 5, 12, 12, 0, tzinfo=UTC)
    _seed_kg(kg_a, 3, start)
    backend_a = SyncthingBackend(folder=str(folder), psk=psk, device_id="A")
    result = push(kg=kg_a, oltp=oltp_a, backend=backend_a)
    assert result.pushed == 3
    assert result.skipped_by_policy == 0

    # Device B: pull.
    kg_b = KnowledgeGraph(db_path=tmp_path / "B" / "kg")
    backend_b = SyncthingBackend(folder=str(folder), psk=psk, device_id="B")
    pr = pull(kg=kg_b, backend=backend_b)
    assert pr.applied == 3
    assert pr.rejected == 0

    # B can read what A pushed.
    res = kg_b._conn.execute("MATCH (m:MemoryNode) RETURN count(m)")
    assert res.get_next()[0] == 3


def test_cursor_advances_so_repush_is_empty(tmp_path: Path):
    psk = os.urandom(32)
    folder = tmp_path / "shared"
    folder.mkdir()
    kg = KnowledgeGraph(db_path=tmp_path / "kg")
    oltp = open_unencrypted(tmp_path / "sb.db")
    _seed_kg(kg, 2, datetime(2026, 5, 12, 12, 0, tzinfo=UTC))
    backend = SyncthingBackend(folder=str(folder), psk=psk, device_id="A")

    r1 = push(kg=kg, oltp=oltp, backend=backend)
    assert r1.pushed == 2

    r2 = push(kg=kg, oltp=oltp, backend=backend)
    assert r2.pushed == 0
    assert _read_cursor(oltp, "syncthing") > 0


def test_pull_unknown_kind_is_rejected_not_crashed(tmp_path: Path):
    psk = os.urandom(32)
    folder = tmp_path / "shared"
    folder.mkdir()
    a = SyncthingBackend(folder=str(folder), psk=psk, device_id="A")
    # Push a kind we don't yet apply on pull.
    a.push("kg_edge", {"src": "m1", "dst": "p1", "kind": "MENTIONS"})

    kg = KnowledgeGraph(db_path=tmp_path / "kg")
    b = SyncthingBackend(folder=str(folder), psk=psk, device_id="B")
    r = pull(kg=kg, backend=b)
    assert r.applied == 0
    assert r.rejected == 1

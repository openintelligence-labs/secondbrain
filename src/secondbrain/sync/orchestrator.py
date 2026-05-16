"""Drives push/pull over a SyncBackend.

Push: walk MemoryNodes that were ingested since the last sync cursor, ship
each one through the backend, and advance the cursor.

Pull: read everything the backend has buffered, upsert into the local KG.

The policy filter from `sync/policy.py` is applied before any payload leaves
the device — `hevc_frame` and `audio_chunk` are categorically blocked.

Cursor storage: a tiny `sync_cursor` table in the OLTP DB. One row per
backend name. Created on first push.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

from secondbrain.store.kg import KnowledgeGraph
from secondbrain.sync.backend import SyncBackend
from secondbrain.sync.policy import SyncableKind, SyncPolicy

log = structlog.get_logger()


CURSOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_cursor (
    backend TEXT PRIMARY KEY,
    last_ingested_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
"""


def _ensure_cursor_table(oltp: sqlite3.Connection) -> None:
    oltp.executescript(CURSOR_SCHEMA)
    oltp.commit()


def _read_cursor(oltp: sqlite3.Connection, backend_name: str) -> float:
    _ensure_cursor_table(oltp)
    row = oltp.execute(
        "SELECT last_ingested_at FROM sync_cursor WHERE backend = ?",
        (backend_name,),
    ).fetchone()
    return float(row[0]) if row else 0.0


def _write_cursor(oltp: sqlite3.Connection, backend_name: str, ts: float) -> None:
    _ensure_cursor_table(oltp)
    now = datetime.now(timezone.utc).timestamp()
    oltp.execute(
        "INSERT INTO sync_cursor(backend, last_ingested_at, updated_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(backend) DO UPDATE SET "
        "last_ingested_at=excluded.last_ingested_at, updated_at=excluded.updated_at",
        (backend_name, ts, now),
    )
    oltp.commit()


@dataclass
class PushResult:
    pushed: int
    skipped_by_policy: int
    new_cursor: float


def push(
    *,
    kg: KnowledgeGraph,
    oltp: sqlite3.Connection,
    backend: SyncBackend,
    policy: SyncPolicy | None = None,
) -> PushResult:
    """Push memory_node + kg_edge records newer than the cursor."""
    policy = policy or SyncPolicy()
    cursor = _read_cursor(oltp, backend.name)

    # Walk Kùzu for memories ingested after cursor. Kùzu stores TIMESTAMP as
    # microseconds since epoch — convert.
    cursor_us = int(cursor * 1_000_000) if cursor else 0

    pushed = 0
    skipped = 0
    new_cursor = cursor

    # MemoryNodes.
    rows = kg._conn.execute(
        "MATCH (m:MemoryNode) "
        "WHERE m.ingested_at > timestamp($cursor_iso) "
        "RETURN m.id, m.type, m.content, m.valid_from, m.valid_to, "
        "m.ingested_at, m.importance, m.decay "
        "ORDER BY m.ingested_at",
        {"cursor_iso": datetime.fromtimestamp(cursor, tz=timezone.utc).isoformat()},
    )
    while rows.has_next():
        mid, mtype, content, vf, vt, ig, imp, decay = rows.get_next()
        kind: SyncableKind = "memory_node"
        if not policy.should_sync(kind):
            skipped += 1
            continue
        payload = {
            "id": mid,
            "type": mtype,
            "content": content,
            "valid_from": vf.isoformat() if vf else None,
            "valid_to": vt.isoformat() if vt else None,
            "ingested_at": ig.isoformat() if ig else None,
            "importance": imp,
            "decay": decay,
        }
        backend.push(kind, payload)
        pushed += 1
        if ig is not None:
            ig_ts = ig.replace(tzinfo=timezone.utc).timestamp() if ig.tzinfo is None else ig.timestamp()
            if ig_ts > new_cursor:
                new_cursor = ig_ts

    if new_cursor > cursor:
        _write_cursor(oltp, backend.name, new_cursor)
    log.info("sync.push", backend=backend.name, pushed=pushed, skipped=skipped)
    return PushResult(pushed=pushed, skipped_by_policy=skipped, new_cursor=new_cursor)


@dataclass
class PullResult:
    applied: int
    rejected: int


def pull(*, kg: KnowledgeGraph, backend: SyncBackend) -> PullResult:
    """Apply every record currently in the backend's inbox."""
    applied = 0
    rejected = 0
    for kind, payload in backend.pull():
        try:
            if kind == "memory_node":
                vf = _parse_iso(payload.get("valid_from")) or datetime.now(timezone.utc)
                vt = _parse_iso(payload.get("valid_to"))
                ig = _parse_iso(payload.get("ingested_at")) or vf
                kg.upsert_memory(
                    payload["id"],
                    payload.get("type") or "fact",
                    payload["content"],
                    valid_from=vf,
                    valid_to=vt,
                    ingested_at=ig,
                    importance=float(payload.get("importance") or 1.0),
                    decay=float(payload.get("decay") or 1.0),
                )
                applied += 1
            else:
                # We only synchronize memory_node in v1.0. Other kinds (person,
                # commitment, kg_edge) will land in v1.1 when we extend the
                # backend's payload schema.
                rejected += 1
        except Exception as e:
            log.warning("sync.pull_apply_failed", kind=kind, err=repr(e))
            rejected += 1
    log.info("sync.pull", backend=backend.name, applied=applied, rejected=rejected)
    return PullResult(applied=applied, rejected=rejected)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

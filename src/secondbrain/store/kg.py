"""Kùzu-backed bi-temporal knowledge graph.

Nodes:
    Capture        (id, source, captured_at, app_name, app_bundle_id)
    Person         (id, name, primary_email)
    Alias          (value, kind)            -- email/handle/etc, attached to Person
    MemoryNode     (id, type, content,
                    valid_from, valid_to, ingested_at,
                    superseded_by, importance, decay)
    Commitment     (id, content, owner_pid, due_at, status, valid_from, valid_to)

Edges (all bi-temporal: valid_from / valid_to / ingested_at on the rel):
    DERIVED_FROM   MemoryNode -> Capture            (provenance)
    MENTIONS       MemoryNode -> Person
    LINKED_TO      MemoryNode -> MemoryNode         (A-MEM Zettelkasten)
    HAS_ALIAS      Person -> Alias

Bi-temporal query pattern: every relation carries `valid_from` and `valid_to`,
so we can answer "what did the system know about X as of <date>?" via Cypher
filters on those bounds — validated by the initial spike at p50 0.41ms.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import kuzu


SCHEMA_DDL: list[str] = [
    # Nodes ----------------------------------------------------------------
    """CREATE NODE TABLE IF NOT EXISTS Capture(
        id STRING PRIMARY KEY,
        source STRING,
        captured_at TIMESTAMP,
        app_name STRING,
        app_bundle_id STRING
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Person(
        id STRING PRIMARY KEY,
        name STRING,
        primary_email STRING
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Alias(
        value STRING PRIMARY KEY,
        kind STRING
    )""",
    """CREATE NODE TABLE IF NOT EXISTS MemoryNode(
        id STRING PRIMARY KEY,
        type STRING,
        content STRING,
        valid_from TIMESTAMP,
        valid_to TIMESTAMP,
        ingested_at TIMESTAMP,
        superseded_by STRING,
        importance DOUBLE,
        decay DOUBLE
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Commitment(
        id STRING PRIMARY KEY,
        content STRING,
        owner_pid STRING,
        due_at TIMESTAMP,
        status STRING,
        valid_from TIMESTAMP,
        valid_to TIMESTAMP,
        ingested_at TIMESTAMP
    )""",
    # Edges ---------------------------------------------------------------
    """CREATE REL TABLE IF NOT EXISTS DERIVED_FROM(
        FROM MemoryNode TO Capture,
        ingested_at TIMESTAMP
    )""",
    """CREATE REL TABLE IF NOT EXISTS MENTIONS(
        FROM MemoryNode TO Person,
        valid_from TIMESTAMP,
        valid_to TIMESTAMP,
        ingested_at TIMESTAMP
    )""",
    """CREATE REL TABLE IF NOT EXISTS LINKED_TO(
        FROM MemoryNode TO MemoryNode,
        weight DOUBLE,
        ingested_at TIMESTAMP
    )""",
    """CREATE REL TABLE IF NOT EXISTS HAS_ALIAS(
        FROM Person TO Alias,
        ingested_at TIMESTAMP
    )""",
]


def _ts(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _from_ts(dt: datetime | None) -> datetime | None:
    """Re-attach UTC tz on the way out (Kùzu strips tzinfo on TIMESTAMP read)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class KnowledgeGraph:
    """Wrapper around Kùzu giving us a tiny, opinionated API."""

    db_path: Path
    _db: kuzu.Database = field(init=False)
    _conn: kuzu.Connection = field(init=False)

    def __post_init__(self) -> None:
        # Kùzu wants a *file* (it manages its own directory underneath); accept
        # either a directory (we add `kg.db` inside) or a file path.
        if self.db_path.suffix == "":
            self.db_path.mkdir(parents=True, exist_ok=True)
            db_file = self.db_path / "kg.db"
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            db_file = self.db_path
        # Kùzu's default `max_db_size` is 8 TB — a single virtual mmap that
        # works fine in isolation but exhausts virtual address space when a
        # test suite opens dozens of databases in one process. Cap to 16 GiB
        # (or env override) for production-realistic limits while keeping
        # parallel-test friendliness.
        import os
        max_gib = int(os.environ.get("SECONDBRAIN_KUZU_MAX_DB_GIB", "16"))
        self._db = kuzu.Database(
            str(db_file),
            max_db_size=max_gib * 1024 * 1024 * 1024,
        )
        self._conn = kuzu.Connection(self._db)
        for ddl in SCHEMA_DDL:
            self._conn.execute(ddl)

    # ----- Captures -------------------------------------------------------
    def upsert_capture(
        self,
        capture_id: str,
        source: str,
        captured_at: datetime,
        app_name: str | None,
        app_bundle_id: str | None,
    ) -> None:
        # MERGE-style: skip if already present.
        existing = self._conn.execute(
            "MATCH (c:Capture {id:$id}) RETURN count(c)",
            {"id": capture_id},
        )
        if existing.get_next()[0] > 0:
            return
        self._conn.execute(
            "CREATE (:Capture {id:$id, source:$src, captured_at:$ts, "
            "app_name:$app, app_bundle_id:$bid})",
            {
                "id": capture_id,
                "src": source,
                "ts": _ts(captured_at),
                "app": app_name or "",
                "bid": app_bundle_id or "",
            },
        )

    # ----- Persons --------------------------------------------------------
    def upsert_person(
        self, person_id: str, name: str, primary_email: str | None
    ) -> None:
        existing = self._conn.execute(
            "MATCH (p:Person {id:$id}) RETURN count(p)", {"id": person_id}
        )
        if existing.get_next()[0] > 0:
            return
        self._conn.execute(
            "CREATE (:Person {id:$id, name:$n, primary_email:$e})",
            {"id": person_id, "n": name, "e": primary_email or ""},
        )

    def add_alias(self, person_id: str, value: str, kind: str) -> None:
        existing = self._conn.execute(
            "MATCH (a:Alias {value:$v}) RETURN count(a)", {"v": value}
        )
        if existing.get_next()[0] == 0:
            self._conn.execute(
                "CREATE (:Alias {value:$v, kind:$k})", {"v": value, "k": kind}
            )
        self._conn.execute(
            "MATCH (p:Person {id:$pid}), (a:Alias {value:$v}) "
            "CREATE (p)-[:HAS_ALIAS {ingested_at:$ts}]->(a)",
            {"pid": person_id, "v": value, "ts": _ts(datetime.now(timezone.utc))},
        )

    def find_person_by_alias(self, value: str) -> str | None:
        r = self._conn.execute(
            "MATCH (p:Person)-[:HAS_ALIAS]->(a:Alias {value:$v}) RETURN p.id LIMIT 1",
            {"v": value},
        )
        if r.has_next():
            return r.get_next()[0]
        return None

    # ----- MemoryNodes ----------------------------------------------------
    def upsert_memory(
        self,
        node_id: str,
        type_: str,
        content: str,
        *,
        valid_from: datetime,
        valid_to: datetime | None,
        ingested_at: datetime,
        importance: float,
        decay: float = 1.0,
    ) -> None:
        existing = self._conn.execute(
            "MATCH (m:MemoryNode {id:$id}) RETURN count(m)", {"id": node_id}
        )
        if existing.get_next()[0] > 0:
            return
        self._conn.execute(
            "CREATE (:MemoryNode {id:$id, type:$t, content:$c, "
            "valid_from:$vf, valid_to:$vt, ingested_at:$ig, "
            "superseded_by:$sup, importance:$imp, decay:$d})",
            {
                "id": node_id,
                "t": type_,
                "c": content,
                "vf": _ts(valid_from),
                "vt": _ts(valid_to),
                "ig": _ts(ingested_at),
                "sup": "",
                "imp": float(importance),
                "d": float(decay),
            },
        )

    def link_memory_to_capture(
        self, memory_id: str, capture_id: str, ingested_at: datetime
    ) -> None:
        self._conn.execute(
            "MATCH (m:MemoryNode {id:$mid}), (c:Capture {id:$cid}) "
            "CREATE (m)-[:DERIVED_FROM {ingested_at:$ts}]->(c)",
            {"mid": memory_id, "cid": capture_id, "ts": _ts(ingested_at)},
        )

    def link_memory_to_person(
        self,
        memory_id: str,
        person_id: str,
        *,
        valid_from: datetime,
        ingested_at: datetime,
    ) -> None:
        self._conn.execute(
            "MATCH (m:MemoryNode {id:$mid}), (p:Person {id:$pid}) "
            "CREATE (m)-[:MENTIONS {valid_from:$vf, valid_to:NULL, ingested_at:$ig}]->(p)",
            {
                "mid": memory_id,
                "pid": person_id,
                "vf": _ts(valid_from),
                "ig": _ts(ingested_at),
            },
        )

    def link_memories(
        self, src_id: str, dst_id: str, *, weight: float, ingested_at: datetime
    ) -> None:
        self._conn.execute(
            "MATCH (a:MemoryNode {id:$s}), (b:MemoryNode {id:$d}) "
            "CREATE (a)-[:LINKED_TO {weight:$w, ingested_at:$ts}]->(b)",
            {"s": src_id, "d": dst_id, "w": float(weight), "ts": _ts(ingested_at)},
        )

    # ----- Commitments ----------------------------------------------------
    def upsert_commitment(
        self,
        commitment_id: str,
        content: str,
        *,
        owner_pid: str | None,
        due_at: datetime | None,
        valid_from: datetime,
        ingested_at: datetime,
        status: str = "open",
    ) -> None:
        existing = self._conn.execute(
            "MATCH (c:Commitment {id:$id}) RETURN count(c)", {"id": commitment_id}
        )
        if existing.get_next()[0] > 0:
            return
        self._conn.execute(
            "CREATE (:Commitment {id:$id, content:$c, owner_pid:$o, "
            "due_at:$d, status:$st, valid_from:$vf, valid_to:NULL, ingested_at:$ig})",
            {
                "id": commitment_id,
                "c": content,
                "o": owner_pid or "",
                "d": _ts(due_at),
                "st": status,
                "vf": _ts(valid_from),
                "ig": _ts(ingested_at),
            },
        )

    def commitments(
        self,
        *,
        status: str | None = None,
        due_before: datetime | None = None,
        limit: int = 50,
    ) -> list[dict]:
        cypher = "MATCH (c:Commitment) "
        params: dict = {"limit": limit}
        wheres = []
        if status is not None:
            wheres.append("c.status = $status")
            params["status"] = status
        if due_before is not None:
            wheres.append("c.due_at IS NOT NULL AND c.due_at <= $due_before")
            params["due_before"] = _ts(due_before)
        if wheres:
            cypher += "WHERE " + " AND ".join(wheres) + " "
        cypher += "RETURN c.id, c.content, c.due_at, c.status, c.owner_pid LIMIT $limit"
        r = self._conn.execute(cypher, params)
        out: list[dict] = []
        while r.has_next():
            row = r.get_next()
            out.append({
                "id": row[0],
                "content": row[1],
                "due_at": _from_ts(row[2]) if row[2] else None,
                "status": row[3],
                "owner_pid": row[4] or None,
            })
        return out

    # ----- Queries --------------------------------------------------------
    def facts_about(
        self,
        person_id: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pid": person_id, "limit": limit}
        if as_of is None:
            r = self._conn.execute(
                "MATCH (m:MemoryNode)-[mention:MENTIONS]->(p:Person {id:$pid}) "
                "RETURN m.id, m.content, m.valid_from, m.importance "
                "ORDER BY m.valid_from DESC LIMIT $limit",
                params,
            )
        else:
            params["t"] = _ts(as_of)
            r = self._conn.execute(
                "MATCH (m:MemoryNode)-[mention:MENTIONS]->(p:Person {id:$pid}) "
                "WHERE m.valid_from <= $t "
                "AND (m.valid_to IS NULL OR m.valid_to >= $t) "
                "RETURN m.id, m.content, m.valid_from, m.importance "
                "ORDER BY m.valid_from DESC LIMIT $limit",
                params,
            )
        out = []
        while r.has_next():
            row = r.get_next()
            out.append(
                {
                    "memory_id": row[0],
                    "content": row[1],
                    "valid_from": _from_ts(row[2]),
                    "importance": row[3],
                }
            )
        return out

    def events_at(
        self, start: datetime, end: datetime, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        r = self._conn.execute(
            "MATCH (m:MemoryNode) "
            "WHERE m.valid_from >= $s AND m.valid_from <= $e "
            "RETURN m.id, m.content, m.valid_from, m.importance "
            "ORDER BY m.valid_from ASC LIMIT $limit",
            {"s": _ts(start), "e": _ts(end), "limit": limit},
        )
        out: list[dict[str, Any]] = []
        while r.has_next():
            row = r.get_next()
            out.append(
                {
                    "memory_id": row[0],
                    "content": row[1],
                    "valid_from": _from_ts(row[2]),
                    "importance": row[3],
                }
            )
        return out

    def find_path(
        self, person_a: str, person_b: str, *, max_hops: int = 4
    ) -> list[str]:
        # Path via shared memories (m1 mentions A and B both)
        r = self._conn.execute(
            "MATCH (m:MemoryNode)-[:MENTIONS]->(a:Person {id:$a}), "
            "(m)-[:MENTIONS]->(b:Person {id:$b}) "
            "RETURN m.id LIMIT 5",
            {"a": person_a, "b": person_b},
        )
        out: list[str] = []
        while r.has_next():
            out.append(r.get_next()[0])
        return out

    def neighbors(self, memory_id: str, *, limit: int = 10) -> list[dict]:
        r = self._conn.execute(
            "MATCH (a:MemoryNode {id:$id})-[l:LINKED_TO]->(b:MemoryNode) "
            "RETURN b.id, b.content, l.weight "
            "ORDER BY l.weight DESC LIMIT $limit",
            {"id": memory_id, "limit": limit},
        )
        out: list[dict] = []
        while r.has_next():
            row = r.get_next()
            out.append(
                {"memory_id": row[0], "content": row[1], "weight": row[2]}
            )
        return out

    # ----- Cascading delete (GDPR) ---------------------------------------
    def forget_capture(self, capture_id: str) -> int:
        """Delete a Capture and any MemoryNodes solely derived from it.

        Returns the number of MemoryNodes deleted. KG edges go away by table
        constraint when the source/target node is deleted.
        """
        memories_only_from_this = self._conn.execute(
            "MATCH (m:MemoryNode)-[:DERIVED_FROM]->(c:Capture {id:$cid}) "
            "WHERE NOT EXISTS { "
            "  MATCH (m)-[:DERIVED_FROM]->(other:Capture) "
            "  WHERE other.id <> $cid"
            "} "
            "RETURN m.id",
            {"cid": capture_id},
        )
        ids: list[str] = []
        while memories_only_from_this.has_next():
            ids.append(memories_only_from_this.get_next()[0])
        for mid in ids:
            self._conn.execute(
                "MATCH (m:MemoryNode {id:$id}) DETACH DELETE m", {"id": mid}
            )
        self._conn.execute(
            "MATCH (c:Capture {id:$cid}) DETACH DELETE c", {"cid": capture_id}
        )
        return len(ids)

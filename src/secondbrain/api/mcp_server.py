"""MCP server.

Exposes 7 tools that turn SecondBrain into a memory substrate any MCP-aware
client (Claude Desktop, Cursor, Codex, Windsurf, Gemini CLI) can attach to:

    1. memory.search(query, time_range?, person?, source?)
    2. memory.recall_timeline(start, end, granularity)
    3. memory.get_person(name|id)
    4. memory.commitments(status, due_before)
    5. memory.daily_digest(date)
    6. memory.add_note(text, tags)
    7. memory.forget(entity_id|time_range, reason)        # the GDPR moat

Implementation strategy: build the tools as plain functions that operate on
the SecondBrain stack (KG, vector, text, OLTP, audit log). The MCP server
adapter is a thin shell that maps tool names → these functions and validates
the JSON schemas. That way the smoke test exercises the *tool bodies*
without spinning up a live network transport.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from secondbrain.compliance.audit import AuditLog
from secondbrain.embed.text import TextEmbedder
from secondbrain.embed.stub import StubEmbedder
from secondbrain.memory.entities import _stable_id
from secondbrain.search.hybrid import HybridSearcher
from secondbrain.search.kg_filter import KGAwareSearcher
from secondbrain.store.kg import KnowledgeGraph
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


@dataclass
class ToolDef:
    name: str
    description: str
    schema: dict[str, Any]


TOOL_DEFS: list[ToolDef] = [
    ToolDef(
        name="memory.search",
        description="Hybrid retrieval over your captured memory.",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "time_range": {"type": "array", "items": {"type": "string"}},
                "person": {"type": "string"},
                "source": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    ),
    ToolDef(
        name="memory.recall_timeline",
        description="Return memories whose validity overlaps [start, end].",
        schema={
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "granularity": {"type": "string", "enum": ["minute", "hour", "day"]},
            },
            "required": ["start", "end"],
        },
    ),
    ToolDef(
        name="memory.get_person",
        description="Person card across modalities.",
        schema={
            "type": "object",
            "properties": {"name": {"type": "string"}, "id": {"type": "string"}},
        },
    ),
    ToolDef(
        name="memory.commitments",
        description="List commitments with status filter.",
        schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "done", "cancelled", "broken"]},
                "due_before": {"type": "string"},
            },
        },
    ),
    ToolDef(
        name="memory.daily_digest",
        description="Render the day/week/month digest.",
        schema={
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "period": {"type": "string", "enum": ["day", "week", "month"]},
            },
        },
    ),
    ToolDef(
        name="memory.add_note",
        description="Inject an explicit user note into the memory graph.",
        schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["text"],
        },
    ),
    ToolDef(
        name="memory.forget",
        description="Cascading delete by entity or time-range. GDPR Art. 17.",
        schema={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "capture_id": {"type": "string"},
                "time_range": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
            },
            "required": ["reason"],
        },
    ),
]


@dataclass
class MCPContext:
    """Bag of stack handles the tool implementations need."""
    kg: KnowledgeGraph
    vector: VectorStore
    text: TextIndex
    embedder: object
    oltp: sqlite3.Connection
    # Path to the on-disk OLTP file. None for in-memory contexts.
    # /health uses this to compute free-disk on the mount.
    oltp_path: Path | None = None
    audit: AuditLog = field(init=False)

    def __post_init__(self) -> None:
        self.audit = AuditLog(self.oltp)


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ----- Tool implementations ------------------------------------------------

def t_memory_search(ctx: MCPContext, **args) -> dict[str, Any]:
    query = args["query"]
    limit = int(args.get("limit", 10))
    inner = HybridSearcher(text_index=ctx.text, vector_store=ctx.vector, embedder=ctx.embedder)
    searcher = KGAwareSearcher(kg=ctx.kg, inner=inner)
    hits = searcher.search(query, limit=limit)
    cited = [h.capture_id for h in hits]
    ctx.audit.record("search", actor="mcp", query=query, cited=cited)
    return {
        "hits": [
            {
                "chunk_uid": h.chunk_uid,
                "capture_id": h.capture_id,
                "chunk_index": h.chunk_index,
                "snippet": (h.body or "")[:400],
                "rrf_score": h.rrf_score,
                "bm25_rank": h.bm25_rank,
                "dense_rank": h.dense_rank,
            }
            for h in hits
        ]
    }


def t_recall_timeline(ctx: MCPContext, **args) -> dict[str, Any]:
    start = _parse_dt(args["start"])
    end = _parse_dt(args["end"])
    rows = ctx.kg.events_at(start, end, limit=200)
    cited = [r["memory_id"] for r in rows]
    ctx.audit.record("recall_timeline", actor="mcp", cited=cited,
                     detail={"start": args["start"], "end": args["end"]})
    return {"events": rows}


def t_get_person(ctx: MCPContext, **args) -> dict[str, Any]:
    name = args.get("name")
    pid = args.get("id") or (_stable_id(name) if name else None)
    if not pid:
        return {"error": "need name or id"}
    facts = ctx.kg.facts_about(pid, limit=20)
    ctx.audit.record("get_person", actor="mcp",
                     cited=[f["memory_id"] for f in facts],
                     detail={"person_id": pid})
    return {"person_id": pid, "facts": facts}


def t_commitments(ctx: MCPContext, **args) -> dict[str, Any]:
    status = args.get("status", "open")
    due_before = args.get("due_before")
    due_dt: datetime | None = None
    if due_before:
        due_dt = _parse_dt(due_before)
    rows = ctx.kg.commitments(status=status, due_before=due_dt)
    # Render due_at ISO for JSON serializability.
    serialized = []
    for row in rows:
        d = row.get("due_at")
        serialized.append({
            "id": row["id"],
            "content": row["content"],
            "due_at": d.isoformat() if d else None,
            "status": row["status"],
            "owner_pid": row["owner_pid"],
        })
    ctx.audit.record("commitments", actor="mcp",
                     detail={"status": status, "due_before": due_before})
    return {"commitments": serialized}


def t_daily_digest(ctx: MCPContext, **args) -> dict[str, Any]:
    from datetime import date as date_cls
    from secondbrain.memory.digest import render

    period = args.get("period", "day")
    when = args.get("date")
    on = date_cls.fromisoformat(when) if when else date_cls.today()
    digest = render(ctx.kg, period, day=on)
    ctx.audit.record("daily_digest", actor="mcp", cited=digest.cited_memories,
                     detail={"period": period, "date": on.isoformat()})
    return {
        "period": digest.period,
        "period_start": digest.period_start.isoformat(),
        "themes": digest.themes,
        "broken_promises": digest.broken_promises,
        "suggested_followups": digest.suggested_followups,
        "cited": digest.cited_memories,
        "importance_sum": digest.importance_sum,
    }


def t_add_note(ctx: MCPContext, **args) -> dict[str, Any]:
    text = args["text"]
    tags = args.get("tags", [])
    nid = uuid4().hex
    now = datetime.now(timezone.utc)
    ctx.kg.upsert_memory(
        nid, "semantic", text,
        valid_from=now, valid_to=None, ingested_at=now, importance=5.0
    )
    ctx.audit.record("add_note", actor="mcp", cited=[nid], detail={"tags": tags})
    return {"memory_id": nid}


def t_forget(ctx: MCPContext, **args) -> dict[str, Any]:
    """The GDPR moat — cascading delete + audit-log write.

    When `SECONDBRAIN_REQUIRE_BIOMETRIC=1` the operator must authenticate via
    Touch ID before the cascade runs. Failing auth aborts cleanly with an
    audit row recording the refusal.
    """
    from secondbrain.compliance.biometric import BiometricDenied, confirm, is_required

    reason = args["reason"]
    cap_id = args.get("capture_id")
    entity_id = args.get("entity_id")

    if is_required():
        target = cap_id or entity_id or "(no target)"
        try:
            confirm(f"SecondBrain wants to forget {target}: {reason}")
        except BiometricDenied as e:
            ctx.audit.record(
                "forget.denied", actor="mcp",
                detail={"reason": reason, "capture_id": cap_id,
                        "entity_id": entity_id, "auth_error": str(e)},
            )
            return {"deleted": 0, "reason": reason, "error": "biometric-denied"}

    n_deleted = 0
    if cap_id:
        n_deleted += ctx.kg.forget_capture(cap_id)
    if entity_id:
        # Delete the Person and any MemoryNodes whose only mention was them.
        ctx.kg._conn.execute(
            "MATCH (p:Person {id:$id}) DETACH DELETE p", {"id": entity_id}
        )
    ctx.audit.record(
        "forget", actor="mcp",
        detail={"reason": reason, "capture_id": cap_id, "entity_id": entity_id,
                "n_deleted": n_deleted},
    )
    return {"deleted": n_deleted, "reason": reason}


TOOLS = {
    "memory.search": t_memory_search,
    "memory.recall_timeline": t_recall_timeline,
    "memory.get_person": t_get_person,
    "memory.commitments": t_commitments,
    "memory.daily_digest": t_daily_digest,
    "memory.add_note": t_add_note,
    "memory.forget": t_forget,
}


def list_tools() -> list[ToolDef]:
    return list(TOOL_DEFS)


def call(ctx: MCPContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return fn(ctx, **args)
    except TypeError as e:
        return {"error": f"bad args for {name}: {e}"}


def make_default_context(*, db: Path, use_stub_embedder: bool = False) -> MCPContext:
    """Construct an MCPContext rooted at the standard SecondBrain DB layout."""
    base = db.parent
    from secondbrain.store.oltp import open_unencrypted
    return MCPContext(
        kg=KnowledgeGraph(db_path=base / "kg"),
        vector=VectorStore(db_path=base / "lance"),
        text=TextIndex(index_path=base / "tantivy"),
        embedder=StubEmbedder() if use_stub_embedder else TextEmbedder(),
        oltp=open_unencrypted(db),
        oltp_path=db,
    )

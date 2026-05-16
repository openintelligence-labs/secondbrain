"""T-02 — HTTP gateway exposes the same 7 tools as MCP, plus /health + /status.

Tests use aiohttp's TestClient so no real socket is opened.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from secondbrain.api.http import GatewayConfig, make_app
from secondbrain.api.mcp_server import MCPContext
from secondbrain.embed.stub import StubEmbedder
from secondbrain.indexing import Indexer
from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.models import Capture
from secondbrain.store.captures import insert as insert_capture
from secondbrain.store.kg import KnowledgeGraph
from secondbrain.store.oltp import open_unencrypted
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore


def _seed(tmp_path: Path) -> MCPContext:
    db = tmp_path / "secondbrain.db"
    base = db.parent
    embedder = StubEmbedder()
    vector = VectorStore(db_path=base / "lance")
    text = TextIndex(index_path=base / "tantivy")
    kg = KnowledgeGraph(db_path=base / "kg")
    indexer = Indexer(embedder=embedder, vector=vector, text=text)
    pipe = MemoryPipeline(
        kg=kg,
        linker=AMemLinker(embedder=embedder),
        resolver=EntityResolver(kg=kg),
    )
    oltp = open_unencrypted(db)
    cap = Capture(
        id="ui-test-1",
        captured_at=datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc),
        app_name="Slack",
        app_bundle_id="com.slack",
        ax_text="Sam Reed will ship the Snowflake migration by Friday.",
    )
    insert_capture(oltp, cap)
    indexer.index_capture(cap)
    pipe.ingest(cap)
    return MCPContext(kg=kg, vector=vector, text=text, embedder=embedder, oltp=oltp)


@pytest.fixture
async def client(tmp_path: Path):
    ctx = _seed(tmp_path)
    # Origin allow-listing is for production; in tests we send no Origin
    # header, which is itself allowed.
    app = make_app(ctx, cfg=GatewayConfig(require_origin=True))
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_health(client):
    r = await client.get("/health")
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True


async def test_search(client):
    r = await client.post("/search", json={"query": "Snowflake migration", "limit": 5})
    assert r.status == 200
    body = await r.json()
    assert "hits" in body
    assert any("Snowflake" in (h.get("snippet") or "") for h in body["hits"])


async def test_who(client):
    r = await client.post("/who", json={"name": "Sam Reed"})
    assert r.status == 200
    body = await r.json()
    assert "facts" in body
    assert any("Snowflake" in f["content"] for f in body["facts"])


async def test_digest(client):
    r = await client.post("/digest", json={"date": "2026-05-12", "period": "day"})
    assert r.status == 200
    body = await r.json()
    assert body["period"] == "day"
    assert "themes" in body


async def test_commitments(client):
    r = await client.post("/commitments", json={"status": "open"})
    assert r.status == 200
    body = await r.json()
    assert "commitments" in body
    # Sam's first-person promise should appear.
    assert any("send" in c["content"].lower() or "ship" in c["content"].lower()
               for c in body["commitments"])


async def test_status(client):
    r = await client.get("/status")
    assert r.status == 200
    body = await r.json()
    # No daemon attached in this test, so running=False.
    assert body["running"] is False


async def test_forget(client):
    r = await client.post(
        "/forget",
        json={"capture_id": "ui-test-1", "reason": "ui smoke"},
    )
    assert r.status == 200
    body = await r.json()
    assert "deleted" in body


async def test_origin_allowlist_blocks_unknown(tmp_path: Path):
    ctx = _seed(tmp_path)
    app = make_app(ctx, cfg=GatewayConfig(require_origin=True))
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/health", headers={"Origin": "https://evil.example"})
        assert r.status == 403


async def test_origin_allowlist_permits_tauri(tmp_path: Path):
    ctx = _seed(tmp_path)
    app = make_app(ctx, cfg=GatewayConfig(require_origin=True))
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/health", headers={"Origin": "tauri://localhost"})
        assert r.status == 200


async def test_add_note(client):
    r = await client.post("/add-note", json={"text": "test note from UI", "tags": ["ui"]})
    assert r.status == 200
    body = await r.json()
    assert "memory_id" in body


async def test_audit_log(client):
    # The seed already triggered audit rows via ingestion; even if not,
    # the endpoint should return a structured empty list rather than 500.
    r = await client.get("/audit-log?limit=10")
    assert r.status == 200
    body = await r.json()
    assert "entries" in body
    assert isinstance(body["entries"], list)


async def test_llm_config(client):
    r = await client.get("/llm-config")
    assert r.status == 200
    body = await r.json()
    assert "description" in body
    assert "sdk_state" in body


async def test_daemon_control_without_daemon(client):
    r = await client.post("/daemon", json={"action": "pause"})
    # No daemon attached → 409
    assert r.status == 409

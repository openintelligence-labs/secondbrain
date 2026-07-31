"""End-to-end production smoke test.

Hits every gateway endpoint the Tauri UI relies on (see app/src/api.ts) and
asserts the wire shape so that any future Python-side rename without a
matching TypeScript update will fail this test instead of silently breaking
the UI.

What this covers:
  * The synthetic daemon ingests captures.
  * The gateway exposes search, timeline, who, digest, commitments,
    add-note, forget, audit-log, llm-config, status, daemon control,
    /health (deep) and /metrics (Prometheus).
  * Response payloads contain the fields the TS client destructures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from secondbrain.api.http import make_app
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


def _seed_full_stack(tmp_path: Path) -> MCPContext:
    db = tmp_path / "secondbrain.db"
    base = db.parent
    embedder = StubEmbedder()
    vector = VectorStore(db_path=base / "lance")
    text = TextIndex(index_path=base / "tantivy")
    kg = KnowledgeGraph(db_path=base / "kg")
    indexer = Indexer(embedder=embedder, vector=vector, text=text)
    pipe = MemoryPipeline(
        kg=kg, linker=AMemLinker(embedder=embedder), resolver=EntityResolver(kg=kg)
    )
    oltp = open_unencrypted(db)
    samples = [
        ("e2e-1", "Slack", "com.slack", "Sam Reed will ship the Snowflake migration by Friday."),
        (
            "e2e-2",
            "Linear",
            "com.linear",
            "Kafka consumer lag spiked at 14:02 on the ingest pipeline.",
        ),
        (
            "e2e-3",
            "Mail",
            "com.apple.mail",
            "Stripe billing token expiry hotfix shipped Wednesday afternoon.",
        ),
    ]
    for idx, (cid, app, bundle, text_body) in enumerate(samples):
        cap = Capture(
            id=cid,
            captured_at=datetime(2026, 5, 12, 10 + idx, 0, tzinfo=UTC),
            app_name=app,
            app_bundle_id=bundle,
            ax_text=text_body,
        )
        insert_capture(oltp, cap)
        indexer.index_capture(cap)
        pipe.ingest(cap)
    return MCPContext(kg=kg, vector=vector, text=text, embedder=embedder, oltp=oltp, oltp_path=db)


@pytest.fixture
async def client(tmp_path: Path):
    ctx = _seed_full_stack(tmp_path)
    app = make_app(ctx)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_health_shape(client: TestClient):
    r = await client.get("/health")
    body = await r.json()
    assert {"ok", "ts", "checks"} <= set(body.keys())
    assert {"oltp", "disk"} <= set(body["checks"].keys())


async def test_status_shape_matches_StatusResponse(client: TestClient):
    r = await client.get("/status")
    body = await r.json()
    assert "running" in body
    assert isinstance(body["running"], bool)


async def test_search_shape_matches_SearchResponse(client: TestClient):
    r = await client.post("/search", json={"query": "snowflake", "limit": 5})
    body = await r.json()
    assert "hits" in body
    if body["hits"]:
        hit = body["hits"][0]
        # Every field the TS Hit interface destructures must be present.
        for key in (
            "chunk_uid",
            "capture_id",
            "chunk_index",
            "snippet",
            "rrf_score",
            "bm25_rank",
            "dense_rank",
        ):
            assert key in hit, f"/search hit missing {key!r}"


async def test_timeline_shape_matches_TimelineResponse(client: TestClient):
    r = await client.post(
        "/timeline",
        json={"start": "2026-05-12T00:00:00+00:00", "end": "2026-05-13T00:00:00+00:00"},
    )
    body = await r.json()
    assert "events" in body
    if body["events"]:
        for key in ("memory_id", "content", "valid_from", "importance"):
            assert key in body["events"][0], f"/timeline event missing {key!r}"


async def test_who_shape(client: TestClient):
    r = await client.post("/who", json={"name": "Sam Reed"})
    body = await r.json()
    assert "person_id" in body
    assert "facts" in body


async def test_digest_shape_matches_DigestResponse(client: TestClient):
    r = await client.post("/digest", json={"date": "2026-05-12", "period": "day"})
    body = await r.json()
    for key in (
        "period",
        "period_start",
        "themes",
        "broken_promises",
        "suggested_followups",
        "cited",
        "importance_sum",
    ):
        assert key in body, f"/digest missing {key!r}"


async def test_commitments_shape(client: TestClient):
    r = await client.post("/commitments", json={"status": "open"})
    body = await r.json()
    assert "commitments" in body
    for c in body["commitments"]:
        for key in ("id", "content", "due_at", "status", "owner_pid"):
            assert key in c


async def test_add_note_returns_memory_id(client: TestClient):
    r = await client.post("/add-note", json={"text": "test note", "tags": ["e2e"]})
    body = await r.json()
    assert "memory_id" in body


async def test_forget_returns_deleted_count(client: TestClient):
    r = await client.post("/forget", json={"capture_id": "e2e-3", "reason": "e2e test cleanup"})
    body = await r.json()
    assert "deleted" in body


async def test_audit_log_shape(client: TestClient):
    # Make sure something has happened that should produce audit rows.
    await client.post("/search", json={"query": "kafka", "limit": 3})
    r = await client.get("/audit-log?limit=10")
    body = await r.json()
    assert "entries" in body
    if body["entries"]:
        for key in ("id", "ts", "actor", "action", "query", "cited", "detail"):
            assert key in body["entries"][0]


async def test_llm_config_shape(client: TestClient):
    r = await client.get("/llm-config")
    body = await r.json()
    for key in ("provider", "model", "base_url", "api_key_set", "sdk_state", "description"):
        assert key in body


async def test_daemon_control_without_daemon_returns_409(client: TestClient):
    r = await client.post("/daemon", json={"action": "pause"})
    # No daemon attached to the fixture → graceful refusal.
    assert r.status == 409
    body = await r.json()
    assert body["ok"] is False


async def test_metrics_endpoint_serves_prometheus(client: TestClient):
    r = await client.get("/metrics")
    assert r.status == 200
    body = await r.text()
    assert "# TYPE" in body
    assert "secondbrain_audit_log_rows" in body

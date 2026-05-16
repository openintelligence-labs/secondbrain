"""HTTP observability endpoints: deep /health and Prometheus /metrics."""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from secondbrain.api.http import make_app
from secondbrain.api.mcp_server import make_default_context


@pytest.fixture
async def client(tmp_path: Path):
    db = tmp_path / "sb" / "secondbrain.db"
    ctx = make_default_context(db=db, use_stub_embedder=True)
    app = make_app(ctx)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_health_deep_checks_pass_on_fresh_db(client: TestClient):
    r = await client.get("/health")
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True
    assert "checks" in body
    assert body["checks"]["oltp"]["ok"] is True
    assert body["checks"]["disk"]["ok"] is True


async def test_health_503_when_oltp_closed(client: TestClient):
    # Close the OLTP connection out from under the gateway and assert /health
    # downgrades to 503.
    client.server.app["ctx"].oltp.close()
    r = await client.get("/health")
    assert r.status == 503
    body = await r.json()
    assert body["ok"] is False
    assert body["checks"]["oltp"]["ok"] is False


async def test_metrics_is_prometheus_text(client: TestClient):
    r = await client.get("/metrics")
    assert r.status == 200
    assert "text/plain" in r.headers["Content-Type"]
    body = await r.text()
    # Audit log gauge is the most reliable always-present metric on a fresh DB.
    assert "secondbrain_audit_log_rows" in body
    assert "# TYPE secondbrain_audit_log_rows gauge" in body

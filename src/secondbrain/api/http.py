"""127.0.0.1 HTTP gateway for the Tauri shell.

Architecture: every UI surface (menubar tray, ⌘-Space overlay, timeline view)
is a thin client over this gateway. The gateway runs in-process inside the
daemon, so it shares the daemon's KG / vector / text handles (no second
Kùzu connection needed — see `tests/test_forget_concurrency.py`).

Security:
  - Binds 127.0.0.1 only.
  - `Origin` header is validated against an allowlist (Tauri's
    `tauri://localhost`, plus the dev `http://localhost:<port>`).
  - DNS-rebinding defense: any non-loopback Host header is rejected.

This is intentionally tiny — every endpoint maps directly to an existing
in-process function. No new business logic.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from secondbrain.api.mcp_server import MCPContext, call as mcp_call


def _json_default(o):
    """Make datetime serializable so we can pass MCP tool output straight to
    `web.json_response`."""
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not JSON-serializable: {type(o).__name__}")


def _json(payload, status: int = 200) -> "web.Response":
    return web.json_response(payload, status=status, dumps=lambda v: json.dumps(v, default=_json_default))


_ALLOWED_ORIGINS = {
    "tauri://localhost",
    "http://localhost:1420",  # tauri dev server default
    "http://127.0.0.1:1420",
    "http://localhost:5173",  # vite default
    "http://127.0.0.1:5173",
}


@dataclass
class GatewayConfig:
    host: str = "127.0.0.1"
    port: int = 7821
    require_origin: bool = True


def _origin_ok(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    if origin is None:
        # Direct curl/local-only health checks have no Origin and that's fine.
        return True
    return origin in _ALLOWED_ORIGINS


def _host_ok(request: web.Request) -> bool:
    host = request.headers.get("Host", "")
    host_only = host.split(":")[0]
    return host_only in {"127.0.0.1", "localhost", "::1"}


@web.middleware
async def _guard(request: web.Request, handler):
    # Short-circuit CORS preflight from the webview.
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204), request)
    if not _host_ok(request):
        return _cors(
            web.json_response({"error": "non-loopback Host rejected"}, status=403),
            request,
        )
    if request.app["cfg"].require_origin and not _origin_ok(request):
        return _cors(
            web.json_response({"error": "origin not in allowlist"}, status=403),
            request,
        )
    response = await handler(request)
    return _cors(response, request)


def _cors(response: web.StreamResponse, request: web.Request) -> web.StreamResponse:
    """Echo Origin when on the allowlist so the Tauri webview can read us."""
    origin = request.headers.get("Origin")
    if origin and origin in _ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
    return response


# ---- Route handlers --------------------------------------------------------

def _disk_free_gib(path) -> float | None:
    try:
        import shutil

        st = shutil.disk_usage(str(path))
        return st.free / (1024**3)
    except Exception:
        return None


async def health(request: web.Request) -> web.Response:
    """Deep health: OLTP reachable, sidecar alive (if attached), disk space.

    Returns 200 with per-check status when everything's ok, 503 when any
    individual check failed. Operators can scrape this from launchd-style
    KeepAlive policies or external monitors.
    """
    ctx: MCPContext = request.app["ctx"]
    daemon = request.app.get("daemon")
    checks: dict[str, Any] = {}

    # OLTP — SELECT 1 round-trips the encryption + WAL + journal mode.
    try:
        ctx.oltp.execute("SELECT 1").fetchone()
        checks["oltp"] = {"ok": True}
    except Exception as e:
        checks["oltp"] = {"ok": False, "err": repr(e)}

    # Disk free on the OLTP path's mount.
    db_path = getattr(getattr(ctx, "oltp_path", None), "parent", None)
    free_gib = _disk_free_gib(db_path) if db_path is not None else None
    if free_gib is not None:
        checks["disk"] = {"ok": free_gib >= 1.0, "free_gib": round(free_gib, 2)}
    else:
        checks["disk"] = {"ok": True, "free_gib": None}

    # Daemon (optional).
    if daemon is not None:
        checks["daemon"] = {
            "ok": True,
            "paused": bool(getattr(daemon.metrics, "paused", False)),
        }

    ok = all(c.get("ok") for c in checks.values())
    return _json(
        {
            "ok": ok,
            "ts": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        },
        status=200 if ok else 503,
    )


async def search(request: web.Request) -> web.Response:
    body = await request.json()
    ctx: MCPContext = request.app["ctx"]
    out = mcp_call(ctx, "memory.search", {
        "query": body.get("query", ""),
        "limit": int(body.get("limit", 10)),
    })
    return _json(out)


async def who(request: web.Request) -> web.Response:
    body = await request.json()
    ctx: MCPContext = request.app["ctx"]
    out = mcp_call(ctx, "memory.get_person", {"name": body["name"]})
    return _json(out)


async def timeline(request: web.Request) -> web.Response:
    body = await request.json()
    ctx: MCPContext = request.app["ctx"]
    out = mcp_call(ctx, "memory.recall_timeline", {
        "start": body["start"],
        "end": body["end"],
    })
    return _json(out)


async def digest(request: web.Request) -> web.Response:
    body = await request.json()
    ctx: MCPContext = request.app["ctx"]
    out = mcp_call(ctx, "memory.daily_digest", {
        "date": body.get("date"),
        "period": body.get("period", "day"),
    })
    return _json(out)


async def commitments(request: web.Request) -> web.Response:
    body = await request.json()
    ctx: MCPContext = request.app["ctx"]
    out = mcp_call(ctx, "memory.commitments", {
        "status": body.get("status", "open"),
        "due_before": body.get("due_before"),
    })
    return _json(out)


async def status_endpoint(request: web.Request) -> web.Response:
    """Capture metrics — what the menubar tray shows."""
    daemon = request.app.get("daemon")
    if daemon is None:
        return _json({"running": False})
    return _json({
        "running": True,
        "metrics": daemon.metrics.as_dict(),
        "ts": datetime.now(timezone.utc).isoformat(),
    })


async def forget(request: web.Request) -> web.Response:
    body = await request.json()
    ctx: MCPContext = request.app["ctx"]
    out = mcp_call(ctx, "memory.forget", {
        "capture_id": body.get("capture_id"),
        "entity_id": body.get("entity_id"),
        "reason": body.get("reason", "ui-triggered"),
    })
    return _json(out)


async def add_note(request: web.Request) -> web.Response:
    body = await request.json()
    ctx: MCPContext = request.app["ctx"]
    out = mcp_call(ctx, "memory.add_note", {
        "text": body["text"],
        "tags": body.get("tags", []),
    })
    return _json(out)


async def audit_log(request: web.Request) -> web.Response:
    """Recent audit-log entries — Settings → Audit Log feeds this."""
    ctx: MCPContext = request.app["ctx"]
    limit = int(request.query.get("limit", 200))
    rows = ctx.oltp.execute(
        "SELECT id, ts, actor, action, query, cited_json, detail_json "
        "FROM audit_log ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    import json as _j
    entries = [
        {
            "id": r[0],
            "ts": r[1],
            "actor": r[2],
            "action": r[3],
            "query": r[4],
            "cited": _j.loads(r[5]) if r[5] else [],
            "detail": _j.loads(r[6]) if r[6] else {},
        }
        for r in rows
    ]
    return _json({"entries": entries})


async def llm_config(request: web.Request) -> web.Response:
    """Surface the BYO-LLM env config so the Settings UI shows what's live."""
    from secondbrain.llm_config import from_env
    cfg = from_env()
    import importlib.util as _ilu
    sdk_for = {
        "ollama": None, "openai": "openai", "anthropic": "anthropic",
        "gemini": None, "groq": "openai", "mistral": "openai",
    }
    prov = (cfg.provider or "ollama").lower()
    required = sdk_for.get(prov)
    sdk_state = (
        "ok-no-sdk-needed" if required is None
        else ("ok-importable" if _ilu.find_spec(required) is not None
              else f"missing:{required}")
    )
    return _json({
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "api_key_set": bool(cfg.api_key),
        "sdk_state": sdk_state,
        "description": cfg.describe(),
    })


def _render_prometheus(daemon: Any, ctx: MCPContext) -> str:
    """Hand-rolled Prometheus text format. No prometheus_client dep.

    Surfaces: capture cascade gate counters, AX-text ratio, paused flag,
    memory pipeline degradation counters (if a daemon is attached), and
    the audit-log row count. Histograms are out of scope for v1 — we
    expose counters and gauges only.
    """
    lines: list[str] = []

    def gauge(name: str, value: float, help_: str, **labels: str) -> None:
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} gauge")
        if labels:
            ls = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{ls}}} {value}")
        else:
            lines.append(f"{name} {value}")

    def counter(name: str, value: float, help_: str, **labels: str) -> None:
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} counter")
        if labels:
            ls = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{ls}}} {value}")
        else:
            lines.append(f"{name} {value}")

    if daemon is not None:
        m = daemon.metrics.as_dict()
        counter("secondbrain_frames_seen_total", m.get("seen", 0),
                "Frames the cascade has examined.")
        counter("secondbrain_captures_persisted_total", m.get("persisted", 0),
                "Frames that survived the cascade and got persisted.")
        for gate, n in (m.get("by_gate") or {}).items():
            counter(f"secondbrain_captures_by_gate_total", n,
                    "Per-cascade-gate decision counts.", gate=gate)
        gauge("secondbrain_ax_text_ratio", m.get("ax_text_ratio", 0.0),
              "Fraction of persisted captures that had AX text.")
        gauge("secondbrain_daemon_paused", 1 if m.get("paused") else 0,
              "1 when capture is paused via /daemon.")

        # Memory pipeline degradation counters, if the daemon attached one.
        mem = getattr(daemon, "_memory", None)
        if mem is not None:
            pm = mem.metrics.as_dict()
            counter("secondbrain_memory_linker_failures_total",
                    pm.get("linker_failures", 0),
                    "A-MEM linker failures that fell back to no neighbors.")
            counter("secondbrain_memory_commitment_failures_total",
                    pm.get("commitment_failures", 0),
                    "Commitment extractor failures that fell back to none.")

    # Audit log size — useful sanity gauge.
    try:
        n_audit = ctx.oltp.execute("SELECT COUNT(1) FROM audit_log").fetchone()[0]
        gauge("secondbrain_audit_log_rows", n_audit,
              "Total audit-log rows (search, recall, forget, etc.).")
    except Exception:
        # Table may not exist yet on a fresh DB; that's fine.
        pass

    return "\n".join(lines) + "\n"


async def metrics(request: web.Request) -> web.Response:
    """Prometheus-format metrics. Scrape with no auth (loopback-only)."""
    ctx: MCPContext = request.app["ctx"]
    daemon = request.app.get("daemon")
    body = _render_prometheus(daemon, ctx)
    return web.Response(text=body, content_type="text/plain", charset="utf-8")


async def daemon_control(request: web.Request) -> web.Response:
    """Pause/resume the in-process capture daemon, if one is attached."""
    body = await request.json()
    action = body.get("action", "")
    daemon = request.app.get("daemon")
    if daemon is None:
        return _json({"ok": False, "reason": "no daemon attached"}, status=409)
    if action == "pause":
        daemon.cfg.metrics.paused = True
        return _json({"ok": True, "state": "paused"})
    if action == "resume":
        daemon.cfg.metrics.paused = False
        return _json({"ok": True, "state": "running"})
    return _json({"ok": False, "reason": f"unknown action: {action}"}, status=400)


# ---- App construction ------------------------------------------------------

def make_app(ctx: MCPContext, *, daemon: Any = None, cfg: GatewayConfig | None = None) -> web.Application:
    app = web.Application(middlewares=[_guard])
    app["ctx"] = ctx
    app["cfg"] = cfg or GatewayConfig()
    app["daemon"] = daemon
    app.router.add_get("/health", health)
    app.router.add_post("/search", search)
    app.router.add_post("/who", who)
    app.router.add_post("/timeline", timeline)
    app.router.add_post("/digest", digest)
    app.router.add_post("/commitments", commitments)
    app.router.add_get("/status", status_endpoint)
    app.router.add_post("/forget", forget)
    app.router.add_post("/add-note", add_note)
    app.router.add_get("/audit-log", audit_log)
    app.router.add_get("/llm-config", llm_config)
    app.router.add_post("/daemon", daemon_control)
    app.router.add_get("/metrics", metrics)
    return app


async def serve(ctx: MCPContext, *, daemon: Any = None, cfg: GatewayConfig | None = None) -> None:
    """Run the gateway forever. Cancel-safe."""
    cfg = cfg or GatewayConfig()
    app = make_app(ctx, daemon=daemon, cfg=cfg)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, cfg.host, cfg.port)
    await site.start()
    try:
        # Block forever.
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()

"""Live-socket smoke test for the `secondbrain ui` wiring.

We can't launch Tauri in CI, but we can prove the daemon-attached gateway
works: spin up the same gateway + daemon coroutine on an ephemeral port,
hit /status to confirm the daemon is attached, then hit /daemon to toggle
paused and verify the daemon's metrics flipped. This is the exact path the
tray "Pause Capture" button takes.
"""
from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest
from aiohttp import web

from secondbrain.api.http import GatewayConfig, make_app
from secondbrain.capture.frame import Frame, SyntheticFrameSource, now as _now
from secondbrain.daemon import Daemon, DaemonConfig


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _synthetic_frame(i: int) -> Frame:
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(i)
    arr = rng.integers(0, 255, size=(48, 64, 3), dtype=np.uint8)
    return Frame(
        captured_at=_now(),
        image=Image.fromarray(arr),
        app_name=f"App{i}",
        app_bundle_id=f"com.test.app{i}",
        ax_text=f"Synthetic event #{i}",
        dirty_rect_fraction=0.5,
    )


async def test_ui_live_daemon_pause_resume(tmp_path: Path) -> None:
    db = tmp_path / "sb.db"
    cfg = DaemonConfig(
        db_path=db,
        use_encryption=False,
        use_stub_embedder=True,
        enable_memory=True,
    )
    daemon = Daemon(cfg)
    daemon.build_pipeline()
    ctx = daemon.mcp_context()

    port = _free_port()
    gw_cfg = GatewayConfig(host="127.0.0.1", port=port)
    app = make_app(ctx, daemon=daemon, cfg=gw_cfg)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    source = SyntheticFrameSource([_synthetic_frame(i) for i in range(5)])
    daemon_task = asyncio.create_task(daemon.run(source))

    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            # /status should report a daemon attached and running.
            r = await s.get(f"http://127.0.0.1:{port}/status")
            body = await r.json()
            assert body["running"] is True, body
            assert body["metrics"]["paused"] is False

            # /daemon pause — the tray button's exact call.
            r = await s.post(f"http://127.0.0.1:{port}/daemon", json={"action": "pause"})
            assert r.status == 200, await r.text()
            data = await r.json()
            assert data["ok"] is True
            assert data["state"] == "paused"

            # State must reflect on the daemon and through /status.
            assert daemon.cfg.metrics.paused is True
            r = await s.get(f"http://127.0.0.1:{port}/status")
            assert (await r.json())["metrics"]["paused"] is True

            # Toggle back.
            r = await s.post(f"http://127.0.0.1:{port}/daemon", json={"action": "resume"})
            assert r.status == 200
            assert (await r.json())["state"] == "running"
            assert daemon.cfg.metrics.paused is False
    finally:
        daemon.stop()
        await asyncio.wait_for(daemon_task, timeout=5)
        await runner.cleanup()

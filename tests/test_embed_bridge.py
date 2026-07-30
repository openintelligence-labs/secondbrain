"""`_run_coro_blocking` — the sync↔async bridge under `TextEmbedder`.

The actants embedding backend is async-only; the sync `embed_passages` /
`embed_query` surface used to call `asyncio.run`, which raises when a loop is
already running on the calling thread (aiohttp gateway handlers, the daemon's
consume loop). The bridge must work from both sync and async callers and
propagate exceptions unchanged.
"""

from __future__ import annotations

import pytest

from secondbrain.embed.text import _run_coro_blocking


async def _double(x: int) -> int:
    return x * 2


async def _boom() -> None:
    raise ValueError("kaput")


def test_bridge_without_running_loop():
    assert _run_coro_blocking(_double(21)) == 42


async def test_bridge_inside_running_loop():
    # pytest-asyncio auto mode: we are on a running loop here — the exact
    # situation the gateway's /add-note and /search handlers are in.
    assert _run_coro_blocking(_double(21)) == 42


async def test_bridge_propagates_exceptions():
    with pytest.raises(ValueError, match="kaput"):
        _run_coro_blocking(_boom())

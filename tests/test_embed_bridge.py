"""`_run_coro_blocking` — the sync↔async bridge under `TextEmbedder`.

It must work from both sync and async callers (aiohttp gateway handlers and the
daemon's consume loop already hold a running loop) and propagate exceptions
unchanged.
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
    # pytest-asyncio auto mode puts this on a running loop, matching the
    # gateway's /add-note and /search handlers.
    assert _run_coro_blocking(_double(21)) == 42


async def test_bridge_propagates_exceptions():
    with pytest.raises(ValueError, match="kaput"):
        _run_coro_blocking(_boom())

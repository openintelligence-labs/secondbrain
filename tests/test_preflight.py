"""Preflight checks: each check is a pure function over (db_path, env, fs).

We assert the *shape* of each check (status + actionable fix string) rather
than the result, because the result depends on the host. The gate function
must still classify correctly given synthetic Check lists.
"""

from __future__ import annotations

from pathlib import Path

from secondbrain.preflight import Check, gate, run_preflight


def test_run_preflight_returns_all_checks(tmp_path: Path) -> None:
    db = tmp_path / "sb" / "secondbrain.db"
    checks = run_preflight(db, probe_tcc=False)
    names = {c.name for c in checks}
    assert {
        "disk.free",
        "stores.writable",
        "keychain.access",
        "sck.sidecar",
        "ollama.reachable",
        "ollama.model",
        "embedder.model",
    } <= names


def test_stores_writable_passes_on_fresh_tmp(tmp_path: Path) -> None:
    db = tmp_path / "sb" / "secondbrain.db"
    checks = run_preflight(db, probe_tcc=False)
    sw = next(c for c in checks if c.name == "stores.writable")
    assert sw.status == "ok", sw


def test_gate_blocks_only_on_load_bearing_fails() -> None:
    # ollama failures are NOT blockers — heuristic fallback covers them.
    ok, blockers = gate(
        [
            Check("ollama.reachable", "fail", "down", "ollama serve"),
            Check("disk.free", "ok", "100GiB", None),
        ]
    )
    assert ok is True
    assert blockers == []

    # disk full IS a blocker.
    ok, blockers = gate(
        [
            Check("disk.free", "fail", "0.1 GiB free", "free space"),
            Check("ollama.reachable", "ok", "up", None),
        ]
    )
    assert ok is False
    assert len(blockers) == 1
    assert blockers[0].name == "disk.free"


def test_check_str_renders_glyph_and_fix() -> None:
    c = Check("test", "fail", "broken", fix="do x")
    s = str(c)
    assert "✗" in s
    assert "broken" in s
    assert "do x" in s

    c2 = Check("test", "ok", "fine", fix=None)
    assert "✓" in str(c2)
    assert "fix" not in str(c2)

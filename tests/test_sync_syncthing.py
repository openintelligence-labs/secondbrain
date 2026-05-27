"""Syncthing backend round-trip + isolation tests.

Simulates two devices pointing at the same watched folder (which is what
Syncthing would converge to in steady state) and asserts:
  - device A's push is readable by device B
  - device B does not re-receive its own pushes
  - pull is idempotent — calling twice returns nothing the second time
  - a foreign-keyed blob is silently skipped, not crashed on
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from secondbrain.store.crypt.age_files import encrypt_to_path
from secondbrain.sync.backend import SyncthingBackend


def _peer(folder: Path, device: str, psk: bytes) -> SyncthingBackend:
    return SyncthingBackend(folder=str(folder), psk=psk, device_id=device)


def test_push_then_pull_across_devices(tmp_path: Path) -> None:
    psk = os.urandom(32)
    a = _peer(tmp_path / "shared", "deviceA", psk)
    b = _peer(tmp_path / "shared", "deviceB", psk)

    a.push("memory_node", {"id": "m1", "content": "hello from A"})
    a.push("kg_edge", {"src": "m1", "dst": "p1", "kind": "MENTIONS"})

    received = b.pull()
    assert len(received) == 2
    kinds = {r[0] for r in received}
    assert kinds == {"memory_node", "kg_edge"}


def test_pull_is_idempotent(tmp_path: Path) -> None:
    psk = os.urandom(32)
    a = _peer(tmp_path / "shared", "deviceA", psk)
    b = _peer(tmp_path / "shared", "deviceB", psk)

    a.push("memory_node", {"id": "m1", "content": "once"})
    first = b.pull()
    second = b.pull()
    assert len(first) == 1
    assert second == []


def test_device_does_not_receive_its_own_pushes(tmp_path: Path) -> None:
    psk = os.urandom(32)
    a = _peer(tmp_path / "shared", "deviceA", psk)
    a.push("memory_node", {"id": "self", "content": "echo"})
    assert a.pull() == []


def test_foreign_key_blob_is_skipped(tmp_path: Path) -> None:
    psk = os.urandom(32)
    other_psk = os.urandom(32)
    b = _peer(tmp_path / "shared", "deviceB", psk)

    # A blob written under a foreign key — encrypts with other_psk.
    bad = tmp_path / "shared" / "deviceC-1234-aaaa.sbsync"
    encrypt_to_path(b'{"kind":"memory_node","payload":{}}', bad, key32=other_psk)

    # Should pull nothing and not raise.
    assert b.pull() == []


def test_psk_length_validated() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SyncthingBackend(folder="/tmp/whatever", psk=b"short")


def test_status_reports_counts(tmp_path: Path) -> None:
    psk = os.urandom(32)
    a = _peer(tmp_path / "shared", "deviceA", psk)
    a.push("memory_node", {"x": 1})
    a.push("memory_node", {"x": 2})
    st = a.status()
    assert st["backend"] == "syncthing"
    assert st["blobs_in_folder"] == 2
    assert st["device_id"] == "deviceA"

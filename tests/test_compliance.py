from __future__ import annotations

import os
import socket
import sqlite3

import pytest

from secondbrain.compliance.air_gap import AirGapViolation, airgap, disengage, engage
from secondbrain.compliance.audit import AuditLog


def test_audit_log_round_trip_and_signature():
    conn = sqlite3.connect(":memory:")
    log = AuditLog(conn)
    log.record("search", query="snowflake", cited=["c1", "c2"])
    log.record("forget", query=None, detail={"target": "c1"})
    out = log.export_signed(signing_key32=os.urandom(32))
    assert out["schema"] == "secondbrain.audit.v1"
    assert len(out["entries"]) == 2
    assert isinstance(out["signature_hmac_sha256"], str)
    assert out["entries"][0]["cited"] == ["c1", "c2"]


def test_air_gap_blocks_outbound():
    with airgap():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(AirGapViolation):
            s.connect(("8.8.8.8", 53))
        s.close()


def test_air_gap_allows_loopback():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        with airgap():
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect(("127.0.0.1", port))
            client.close()
    finally:
        server.close()


def test_air_gap_disengages():
    engage()
    disengage()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.1)
    try:
        s.connect(("127.0.0.1", 65500))
    except OSError:
        pass  # connection refused is fine; we just need no AirGapViolation
    finally:
        s.close()

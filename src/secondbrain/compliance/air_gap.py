"""Air-gap mode.

When `--offline` is set, the daemon installs a socket guard that blocks any
non-127.0.0.1 / non-::1 connection. The guard wraps `socket.socket.connect`
so every code path (including transitive HTTP libs) is covered.

Production hardening will additionally drop CAP_NET_RAW on Linux and use
endpoint security on macOS. For now the Python-level guard is sufficient and
testable in CI.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_engaged = False
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_lock = threading.Lock()


class AirGapViolation(RuntimeError):
    """Raised when air-gap is engaged and code tries to dial out."""


def _check_addr(addr) -> None:
    host = None
    if isinstance(addr, tuple):
        host = addr[0]
    if host is None:
        return
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="ignore")
    if host in _LOCAL_HOSTS:
        return
    if host.startswith("127.") or host == "::1":
        return
    raise AirGapViolation(f"air-gap: outbound connect blocked to {host}")


def _wrapped_connect(self, address):
    _check_addr(address)
    return _orig_connect(self, address)


def _wrapped_connect_ex(self, address):
    _check_addr(address)
    return _orig_connect_ex(self, address)


def engage() -> None:
    """Engage the air-gap. Idempotent."""
    global _engaged
    with _lock:
        if _engaged:
            return
        socket.socket.connect = _wrapped_connect  # type: ignore[assignment]
        socket.socket.connect_ex = _wrapped_connect_ex  # type: ignore[assignment]
        _engaged = True


def disengage() -> None:
    global _engaged
    with _lock:
        if not _engaged:
            return
        socket.socket.connect = _orig_connect  # type: ignore[assignment]
        socket.socket.connect_ex = _orig_connect_ex  # type: ignore[assignment]
        _engaged = False


def is_engaged() -> bool:
    return _engaged


@contextmanager
def airgap() -> Iterator[None]:
    engage()
    try:
        yield
    finally:
        disengage()

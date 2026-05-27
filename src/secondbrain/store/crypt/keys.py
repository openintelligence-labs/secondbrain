"""Key management.

Tier 1 (today): device root key in OS Keychain (validated by initial spike).
Tier 2 (next): wrap a Secure-Enclave-backed key on Apple Silicon.
Tier 3 (later): per-record DEKs derived via HKDF; biometric-gated session keys.

This module owns the Python-visible primitives. Native paths (Swift sidecar
for Secure Enclave, pywin32 for DPAPI/TPM) plug in over the same surface.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
from dataclasses import dataclass, field

import keyring


@dataclass
class KeyConfig:
    service: str = "secondbrain.device_root_key"
    user: str = "default"


def get_or_create_root_key(cfg: KeyConfig | None = None) -> str:
    """Return the device root key (hex). Creates one if missing."""
    cfg = cfg or KeyConfig()
    existing = keyring.get_password(cfg.service, cfg.user)
    if existing:
        return existing
    fresh = secrets.token_hex(32)
    keyring.set_password(cfg.service, cfg.user, fresh)
    return fresh


def rotate_root_key(cfg: KeyConfig | None = None) -> tuple[str, str]:
    """Generate a new key, return (old_hex, new_hex). Caller is responsible
    for re-encrypting any data that depended on the old key."""
    cfg = cfg or KeyConfig()
    old = keyring.get_password(cfg.service, cfg.user)
    new = secrets.token_hex(32)
    keyring.set_password(cfg.service, cfg.user, new)
    return (old or "", new)


def derive_dek(root_hex: str, label: bytes) -> bytes:
    """HKDF-style derive a Data Encryption Key from the root key + label.

    Use a stable label per data class (e.g. b"oltp-v1", b"frame-v1") so we can
    rotate one key at a time without forcing a global rewrap.
    """
    root = bytes.fromhex(root_hex)
    return hmac.new(root, label, hashlib.sha256).digest()


@dataclass
class ZeroizingBuffer:
    """Bytes-like that wipes itself on close — used for biometric-gated session
    keys. Approximate; Python doesn't guarantee memory clearing but we do
    everything we can."""

    data: bytearray
    _closed: bool = field(default=False, init=False)

    @classmethod
    def of(cls, data: bytes) -> ZeroizingBuffer:
        return cls(bytearray(data))

    def __enter__(self) -> ZeroizingBuffer:
        return self

    def __exit__(self, *_a) -> None:
        self.zero()

    def zero(self) -> None:
        if self._closed:
            return
        for i in range(len(self.data)):
            self.data[i] = 0
        self._closed = True

    def view(self) -> bytes:
        if self._closed:
            raise RuntimeError("buffer already zeroed")
        return bytes(self.data)


_session_lock = threading.Lock()
_session_key_buffer: ZeroizingBuffer | None = None


def open_session_key(root_hex: str) -> ZeroizingBuffer:
    """Derive a per-session DEK, hold it in a zeroizing buffer."""
    global _session_key_buffer
    with _session_lock:
        if _session_key_buffer is not None and not _session_key_buffer._closed:
            return _session_key_buffer
        salt = os.urandom(16)
        dek = hmac.new(bytes.fromhex(root_hex), salt, hashlib.sha256).digest()
        _session_key_buffer = ZeroizingBuffer.of(dek)
        return _session_key_buffer


def close_session_key() -> None:
    global _session_key_buffer
    with _session_lock:
        if _session_key_buffer is not None:
            _session_key_buffer.zero()
            _session_key_buffer = None

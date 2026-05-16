"""Persistence for device pairing identity + the derived sync PSK.

Lives outside `pairing.py` so that module remains a pure crypto kernel
(no I/O, no globals). All disk + Keychain access goes through here.

Layout:
  ~/.secondbrain/identity.key       — raw 32-byte X25519 private key (mode 0600)
  Keychain service "secondbrain.sync.psk", account "default" — 32-byte PSK hex
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import keyring
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from secondbrain.sync.pairing import DeviceIdentity, derive_shared_key

IDENTITY_FILE = Path.home() / ".secondbrain" / "identity.key"
PSK_KEYRING_SERVICE = "secondbrain.sync.psk"
PSK_KEYRING_ACCOUNT = "default"


def load_or_create_identity(path: Path | None = None) -> DeviceIdentity:
    """Read the device's X25519 private key, generating one on first run.

    The file is `chmod 600` after creation so the key isn't world-readable.
    On macOS, prefer storing it in the Keychain (covered in v1.1); for now
    the encrypted-home directory is the trust boundary.
    """
    # Read at call time so tests can monkeypatch IDENTITY_FILE.
    path = path if path is not None else IDENTITY_FILE
    if path.exists():
        raw = path.read_bytes()
        if len(raw) != 32:
            raise ValueError(
                f"{path} is {len(raw)} bytes; expected 32. Delete it and re-pair."
            )
        sk = X25519PrivateKey.from_private_bytes(raw)
        return DeviceIdentity(
            private_key=sk,
            public_key_bytes=sk.public_key().public_bytes_raw(),
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    ident = DeviceIdentity.fresh()
    # Persist the raw private key bytes. X25519PrivateKey doesn't expose them
    # directly; use the serialization API.
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    raw = ident.private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    path.write_bytes(raw)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return ident


def store_psk(psk: bytes) -> None:
    if len(psk) != 32:
        raise ValueError("psk must be 32 bytes")
    keyring.set_password(PSK_KEYRING_SERVICE, PSK_KEYRING_ACCOUNT, psk.hex())


def load_psk() -> bytes | None:
    hex_ = keyring.get_password(PSK_KEYRING_SERVICE, PSK_KEYRING_ACCOUNT)
    if not hex_:
        return None
    try:
        b = bytes.fromhex(hex_)
    except ValueError:
        return None
    if len(b) != 32:
        return None
    return b


def clear_psk() -> None:
    try:
        keyring.delete_password(PSK_KEYRING_SERVICE, PSK_KEYRING_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


def complete_pairing(peer_pubkey_hex: str) -> bytes:
    """Run DH against a peer's hex-encoded public key and store the PSK."""
    peer_pub = bytes.fromhex(peer_pubkey_hex.strip())
    if len(peer_pub) != 32:
        raise ValueError("peer pubkey must be 32 bytes (64 hex chars)")
    ident = load_or_create_identity()
    psk = derive_shared_key(ident.private_key, peer_pub)
    store_psk(psk)
    return psk

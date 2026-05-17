"""age-encrypted file blobs.

Use the `age` binary if installed (preferred — audited C/Rust tool) and fall
back to ChaCha20-Poly1305 in Python so the codepath is testable without a
runtime dependency.

Backend selection:
  - if `age` is on PATH → pipe through it.
  - else → raw ChaCha20-Poly1305 from `cryptography`.

Either way the on-disk header records the backend so files are self-describing.
"""

from __future__ import annotations

import os
import shutil
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

MAGIC = b"SBAGE\x00"
HEADER_VERSION = 1


def _age_binary() -> str | None:
    return shutil.which("age")


def encrypt_to_path(plaintext: bytes, dest: Path, *, key32: bytes) -> None:
    if len(key32) != 32:
        raise ValueError("key32 must be 32 bytes")
    nonce = os.urandom(12)
    aead = ChaCha20Poly1305(key32)
    ct = aead.encrypt(nonce, plaintext, MAGIC)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        f.write(MAGIC)
        f.write(struct.pack(">B", HEADER_VERSION))
        f.write(nonce)
        f.write(ct)


def decrypt_from_path(path: Path, *, key32: bytes) -> bytes:
    if len(key32) != 32:
        raise ValueError("key32 must be 32 bytes")
    raw = path.read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError("not a SecondBrain age blob")
    version = raw[len(MAGIC)]
    if version != HEADER_VERSION:
        raise ValueError(f"unsupported version: {version}")
    nonce = raw[len(MAGIC) + 1 : len(MAGIC) + 1 + 12]
    ct = raw[len(MAGIC) + 1 + 12 :]
    aead = ChaCha20Poly1305(key32)
    return aead.decrypt(nonce, ct, MAGIC)


def is_encrypted_blob(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False

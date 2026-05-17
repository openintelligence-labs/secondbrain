from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from secondbrain.store.crypt.age_files import (
    decrypt_from_path,
    encrypt_to_path,
    is_encrypted_blob,
)
from secondbrain.store.crypt.keys import (
    ZeroizingBuffer,
    derive_dek,
)


def test_encrypt_decrypt_round_trip(tmp_path: Path):
    key = os.urandom(32)
    dest = tmp_path / "secret.bin"
    encrypt_to_path(b"hello secondbrain", dest, key32=key)
    assert is_encrypted_blob(dest)
    out = decrypt_from_path(dest, key32=key)
    assert out == b"hello secondbrain"


def test_wrong_key_fails(tmp_path: Path):
    dest = tmp_path / "secret.bin"
    encrypt_to_path(b"hello", dest, key32=os.urandom(32))
    with pytest.raises(InvalidTag):
        decrypt_from_path(dest, key32=os.urandom(32))


def test_derive_dek_distinct_per_label():
    root = "00" * 32
    a = derive_dek(root, b"oltp-v1")
    b = derive_dek(root, b"frame-v1")
    assert a != b
    assert len(a) == 32 and len(b) == 32


def test_zeroizing_buffer_clears():
    buf = ZeroizingBuffer.of(b"\xff" * 16)
    assert buf.view() == b"\xff" * 16
    buf.zero()
    with pytest.raises(RuntimeError):
        buf.view()

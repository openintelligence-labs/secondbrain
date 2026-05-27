"""Pair-store: identity persistence + PSK roundtrip via Keychain (mocked)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from secondbrain.sync import pair_store
from secondbrain.sync.pair_store import (
    clear_psk,
    complete_pairing,
    load_or_create_identity,
    load_psk,
    store_psk,
)
from secondbrain.sync.pairing import DeviceIdentity


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pair_store, "IDENTITY_FILE", tmp_path / "identity.key")
    # Use an in-memory keyring backend so tests don't touch the real Keychain.
    fake_store: dict[tuple[str, str], str] = {}

    class _Fake:
        def get_password(self, service, account):
            return fake_store.get((service, account))

        def set_password(self, service, account, value):
            fake_store[(service, account)] = value

        def delete_password(self, service, account):
            fake_store.pop((service, account), None)

    fake = _Fake()
    monkeypatch.setattr(pair_store.keyring, "get_password", fake.get_password)
    monkeypatch.setattr(pair_store.keyring, "set_password", fake.set_password)
    monkeypatch.setattr(pair_store.keyring, "delete_password", fake.delete_password)
    return tmp_path


def test_identity_is_created_and_persisted(isolated_paths: Path):
    ident1 = load_or_create_identity()
    assert isinstance(ident1, DeviceIdentity)
    assert (isolated_paths / "identity.key").exists()

    # File is chmod 600.
    mode = stat.S_IMODE((isolated_paths / "identity.key").stat().st_mode)
    assert mode == 0o600

    # Reloading gives the same identity.
    ident2 = load_or_create_identity()
    assert ident2.public_key_bytes == ident1.public_key_bytes


def test_complete_pairing_roundtrip(isolated_paths: Path):
    # Both "devices" use the in-memory keyring shim and the same identity file.
    a = DeviceIdentity.fresh()
    b = load_or_create_identity()  # this device

    psk = complete_pairing(a.public_key_bytes.hex())
    assert len(psk) == 32
    assert load_psk() == psk

    # The other device, running the same DH against b's pubkey, must derive
    # the same PSK.
    from secondbrain.sync.pairing import derive_shared_key

    psk_from_a = derive_shared_key(a.private_key, b.public_key_bytes)
    assert psk_from_a == psk


def test_clear_psk_removes_it(isolated_paths: Path):
    store_psk(os.urandom(32))
    assert load_psk() is not None
    clear_psk()
    assert load_psk() is None


def test_invalid_pubkey_hex_rejected(isolated_paths: Path):
    with pytest.raises(ValueError):
        complete_pairing("not-hex")
    with pytest.raises(ValueError, match="32 bytes"):
        complete_pairing("aabb")
